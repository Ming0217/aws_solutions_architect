"""VideoDataStack -- S3 buckets, DynamoDB, SQS + DLQ, signing-key secret.

See DESIGN.md "Named resources", "S3 lifecycle", "DynamoDB", "SQS + DLQ",
"CloudFront signing-key lifecycle", and "FFmpeg sourcing". Every stateful
resource sets ``removal_policy=DESTROY`` (buckets also ``auto_delete_objects``)
so a single ``cdk destroy`` removes the lot.
"""
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Size,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct


class VideoDataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Account/region are pinned in app.py, so these resolve to literal names
        # at synth -- the IAM policies in AppStack can stay literal ARNs.
        suffix = f"{self.account}-{self.region}"

        bucket_defaults = {
            "block_public_access": s3.BlockPublicAccess.BLOCK_ALL,
            "enforce_ssl": True,
            "encryption": s3.BucketEncryption.S3_MANAGED,
            "removal_policy": RemovalPolicy.DESTROY,
            "auto_delete_objects": True,
        }

        # Input bucket: raw uploads under input/. Tier cold source to IA@30d and
        # Glacier@90d; abort stray multipart uploads after 7d.
        self.input_bucket = s3.Bucket(
            self,
            "InputBucket",
            bucket_name=f"video-input-{suffix}",
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="input-tiering",
                    prefix="input/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        ),
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(90),
                        ),
                    ],
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
            **bucket_defaults,
        )

        # Output bucket: served HLS artifacts (hot), no tiering; MPU cleanup only.
        self.output_bucket = s3.Bucket(
            self,
            "OutputBucket",
            bucket_name=f"video-output-{suffix}",
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="output-mpu-cleanup",
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
            **bucket_defaults,
        )

        # Frontend (SPA) bucket, served privately through CloudFront OAC.
        self.site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=f"video-site-{suffix}",
            **bucket_defaults,
        )

        # FFmpeg artifact bucket -- the pinned static build is deployed here.
        self.artifact_bucket = s3.Bucket(
            self,
            "ArtifactBucket",
            bucket_name=f"video-artifacts-{suffix}",
            **bucket_defaults,
        )

        # --- DynamoDB --------------------------------------------------------
        # Primary key is the video_id; a single-partition GSI serves newest-first
        # listing via Query (gsi_pk="VIDEO", sort by created_at) -- no table scan.
        self.table = dynamodb.Table(
            self,
            "VideoCatalog",
            table_name="VideoCatalog",
            partition_key=dynamodb.Attribute(
                name="video_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.table.add_global_secondary_index(
            index_name="by-status-created",
            partition_key=dynamodb.Attribute(
                name="gsi_pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # --- SQS + DLQ -------------------------------------------------------
        # DLQ: 14-day retention so a human can inspect quarantined poison pills.
        self.dlq = sqs.Queue(
            self,
            "VideoQueueDlq",
            queue_name="VideoQueue-DLQ",
            retention_period=Duration.days(14),
        )
        # Main queue: 900s visibility (exceeds worst-case transcode), 20s long
        # polling, redrive to the DLQ after 3 failed receives.
        self.queue = sqs.Queue(
            self,
            "VideoQueue",
            queue_name="VideoQueue",
            visibility_timeout=Duration.seconds(900),
            receive_message_wait_time=Duration.seconds(20),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=self.dlq),
        )

        # --- CloudFront signing-key secret ----------------------------------
        # Empty at synth; the operator loads the private PEM out of band after
        # deploy (see README). removal_policy=DESTROY so teardown removes it.
        self.signing_key_secret = secretsmanager.Secret(
            self,
            "CfSigningKey",
            secret_name="video/cf-signing-key",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- FFmpeg artifact deployment --------------------------------------
        # The pinned static build is staged into assets/ffmpeg/bin by
        # scripts/fetch-ffmpeg.sh before synth (synth fails if that dir is empty,
        # by design). ~80-100 MB payload needs more than the deployer defaults.
        s3deploy.BucketDeployment(
            self,
            "FfmpegDeployment",
            sources=[s3deploy.Source.asset("assets/ffmpeg/bin")],
            destination_bucket=self.artifact_bucket,
            destination_key_prefix="ffmpeg/",
            memory_limit=1024,
            ephemeral_storage_size=Size.gibibytes(2),
        )
