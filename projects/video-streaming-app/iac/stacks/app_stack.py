"""VideoAppStack -- ALB, ASGs, CloudFront, DLQ-marker Lambda, outputs.

Wires every piece the other two stacks exposed into the running system. See
DESIGN.md sections "CDK stack decomposition" (AppStack), "IAM - two
least-privilege per-server roles", "Worker ASG - queue-depth scaling",
"Web-tier ASG sizing", "SQS + DLQ", "CloudFront + signed-cookie playback",
and "Clean teardown + outputs".

Carries the FEAT-005 MUST-FIX items: the ``CfPublicKeyId`` output and the
``CF_KEY_PAIR_ID`` web-env injection (the signer needs the PUBLIC KEY id, not
the key-group id); a ResponseHeadersPolicy CORS on ``/media/*`` plus S3 CORS on
the Output bucket so local HLS segment fetches succeed; and gp3 block devices on
both launch templates.

Finding-3 remediation: the ``/api/*`` hop no longer uses a CloudFront VPC origin
to the internal ALB (which would not pass edge->ALB traffic live). Instead
CloudFront's ``/api/*`` behaviour targets an **API Gateway HTTP API** over HTTPS
(its AWS-managed ``execute-api`` endpoint), which forwards through a **VPC Link**
to the still-internal ALB. The HTTP API strips the ``/api`` prefix via a path
parameter mapping so the FastAPI app keeps its unprefixed routes.
"""
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigw_integrations
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from stacks.data_stack import VideoDataStack
from stacks.network_stack import WEB_PORT, VideoNetworkStack

# Local dev origins allowed to pull HLS segments cross-origin from CloudFront.
# Production is same-origin (SPA, API, media all under the one CloudFront
# domain) and needs none of this. MUST-FIX MED_local_media_cors.
LOCAL_DEV_ORIGINS = ["http://127.0.0.1:5500", "http://localhost:5500"]

# 2 GB upload cap (matches api MAX_UPLOAD_BYTES default) -- sizes the gp3 root
# volumes with headroom for the spooled upload + the transcode scratch dir.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
WEB_VOLUME_GIB = 20
WORKER_VOLUME_GIB = 30

# Fixed worker ASG + lifecycle-hook names. Literal (not CDK-generated) so the
# launch-template user-data can embed ASG_NAME / LIFECYCLE_HOOK_NAME without a
# launch-template <-> ASG dependency cycle, and so the worker role can scope its
# autoscaling grant to the exact ASG ARN.
WORKER_ASG_NAME = "video-worker-asg"
WORKER_DRAIN_HOOK = "video-worker-drain"


class VideoAppStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: VideoNetworkStack,
        data: VideoDataStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = network.vpc
        private_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )
        region = self.region
        account = self.account

        # ---- Explicit CloudWatch log groups (teardown-friendly) ------------
        logs.LogGroup(
            self, "WebLogGroup", log_group_name="/video/web",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        logs.LogGroup(
            self, "WorkerLogGroup", log_group_name="/video/worker",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        dlq_log_group = logs.LogGroup(
            self, "DlqMarkerLogGroup", log_group_name="/video/dlq-marker",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---- IAM: two asymmetric least-privilege instance roles ------------
        web_role = iam.Role(
            self, "WebRole",
            role_name="video-web-role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                )
            ],
        )
        # Upload the raw object; read HLS back (fallback/debug); delete both
        # prefixes on DELETE /videos/{id}. No SQS -- S3 fires the event.
        web_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutObject"],
            resources=[data.input_bucket.arn_for_objects("input/*")],
        ))
        web_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[data.output_bucket.arn_for_objects("output/*")],
        ))
        web_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"],
            resources=[data.input_bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": ["input/*"]}},
        ))
        web_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"],
            resources=[data.output_bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": ["output/*"]}},
        ))
        web_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:DeleteObject"],
            resources=[
                data.input_bucket.arn_for_objects("input/*"),
                data.output_bucket.arn_for_objects("output/*"),
            ],
        ))
        web_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem",
                "dynamodb:Query", "dynamodb:DeleteItem",
            ],
            resources=[data.table.table_arn, f"{data.table.table_arn}/index/*"],
        ))
        web_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[data.signing_key_secret.secret_arn],
        ))

        worker_role = iam.Role(
            self, "WorkerRole",
            role_name="video-worker-role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                )
            ],
        )
        worker_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "sqs:ReceiveMessage", "sqs:DeleteMessage",
                "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility",
            ],
            resources=[data.queue.queue_arn],
        ))
        # Download the raw input + the pinned FFmpeg build; write HLS output.
        # No PutObject to Input, no SendMessage -- the worker never ingests.
        worker_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[
                data.input_bucket.arn_for_objects("input/*"),
                data.artifact_bucket.arn_for_objects("*"),
            ],
        ))
        worker_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutObject"],
            resources=[data.output_bucket.arn_for_objects("output/*")],
        ))
        worker_role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:UpdateItem", "dynamodb:GetItem"],
            resources=[data.table.table_arn],
        ))

        # ---- Internal ALB (private subnets, no public IP) ------------------
        alb = elbv2.ApplicationLoadBalancer(
            self, "WebAlb",
            vpc=vpc,
            internet_facing=False,
            security_group=network.alb_sg,
            vpc_subnets=private_subnets,
        )
        listener = alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            open=False,  # alb-sg ingress is the VPC-Link SG rule, not 0.0.0.0/0
        )

        # ---- API Gateway HTTP API -> VPC Link -> internal ALB --------------
        # Finding-3 remediation. CloudFront's /api/* behaviour targets this
        # HTTP API's AWS-managed https endpoint (below); the HTTP API forwards
        # through a VPC Link (ENIs in the private subnets, vpclink-sg) to the
        # still-internal ALB. The ALB keeps no public IP and never becomes
        # internet-facing. The route strips the /api prefix via a path
        # parameter mapping so the FastAPI app keeps its unprefixed routes
        # (/videos, /health, ...): CloudFront forwards /api/videos ->
        # HTTP API route ANY /api/{proxy+} -> overwrite:path=/${proxy} ->
        # the ALB receives /videos.
        vpc_link = apigwv2.VpcLink(
            self, "ApiVpcLink",
            vpc=vpc,
            subnets=private_subnets,
            security_groups=[network.vpclink_sg],
            vpc_link_name="video-api-vpclink",
        )
        api_alb_integration = apigw_integrations.HttpAlbIntegration(
            "ApiAlbIntegration",
            listener,
            vpc_link=vpc_link,
            method=apigwv2.HttpMethod.ANY,
            parameter_mapping=apigwv2.ParameterMapping().overwrite_path(
                apigwv2.MappingValue.custom("/${request.path.proxy}")
            ),
        )
        http_api = apigwv2.HttpApi(
            self, "ApiHttpApi",
            api_name="video-api",
            # CloudFront is the public surface; the execute-api endpoint is an
            # internal origin reached only from CloudFront over HTTPS.
            create_default_stage=True,
        )
        http_api.add_routes(
            path="/api/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=api_alb_integration,
        )
        # The HTTP API default ($default) stage serves at the root of the
        # AWS-managed endpoint, which carries a valid AWS TLS cert -- so
        # CloudFront can use it as an HTTPS custom origin with no custom domain.
        api_origin_domain = (
            f"{http_api.http_api_id}.execute-api.{region}.amazonaws.com"
        )

        # The web ASG is built AFTER the distribution: its user-data embeds the
        # CloudFront domain + public-key id, which are tokens from the
        # distribution. The ALB does not depend on the web launch template, so
        # this stays acyclic.

        # ---- CloudFront public key + key group (signed cookies) ------------
        public_key = cloudfront.PublicKey(
            self, "CfPublicKey",
            encoded_key=Path("keys/cf_public.pem").read_text(),
            comment="video-streaming signed-cookie public key",
        )
        key_group = cloudfront.KeyGroup(
            self, "CfKeyGroup",
            items=[public_key],
            comment="video-streaming trusted key group (/media/*)",
        )

        # ResponseHeadersPolicy CORS for /media/* so local HLS segment fetches
        # (cross-origin from the localhost dev server) succeed. MUST-FIX.
        media_cors = cloudfront.ResponseHeadersPolicy(
            self, "MediaCorsPolicy",
            response_headers_policy_name="video-media-cors",
            comment="CORS for local HLS segment fetches (/media/*)",
            cors_behavior=cloudfront.ResponseHeadersCorsBehavior(
                access_control_allow_credentials=True,
                access_control_allow_headers=["Range", "Origin", "Accept"],
                access_control_allow_methods=["GET", "HEAD", "OPTIONS"],
                access_control_allow_origins=LOCAL_DEV_ORIGINS,
                origin_override=True,
            ),
        )

        # ---- CloudFront distribution: 3 origins ----------------------------
        # The site + output buckets live in VideoDataStack. If the OAC helper
        # auto-attached its exact-distribution-ARN bucket policy to those
        # (DataStack) buckets, DataStack would depend on this stack's
        # distribution while this stack already depends on DataStack's bucket
        # ARNs -- an unresolvable CloudFormation dependency cycle. We therefore
        # (a) reference the buckets by their literal names for the origins (no
        # cross-stack ref), and (b) add the OAC read policy ourselves, scoped to
        # aws:SourceArn arn:aws:cloudfront::<account>:distribution/* -- an
        # account-literal that keeps the cross-account confused-deputy guard
        # without importing the distribution ARN back into DataStack.
        site_bucket_ref = s3.Bucket.from_bucket_name(
            self, "SiteBucketOriginRef", data.site_bucket.bucket_name
        )
        output_bucket_ref = s3.Bucket.from_bucket_name(
            self, "OutputBucketOriginRef", data.output_bucket.bucket_name
        )
        dist_source_arn = f"arn:aws:cloudfront::{account}:distribution/*"
        for bucket in (data.site_bucket, data.output_bucket):
            bucket.add_to_resource_policy(iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[bucket.arn_for_objects("*")],
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                conditions={"StringLike": {"AWS:SourceArn": dist_source_arn}},
            ))

        site_origin = origins.S3BucketOrigin.with_origin_access_control(
            site_bucket_ref
        )
        media_origin = origins.S3BucketOrigin.with_origin_access_control(
            output_bucket_ref
        )
        # The public playback contract is /media/<id>/* (the API signs cookies
        # and returns play-urls under that prefix), but the worker writes the
        # HLS output to the output bucket under output/<id>/*. Nothing mapped
        # one to the other, so CloudFront asked S3 for media/<id>/playlist.m3u8
        # (a key that never exists) and S3 returned 403 AFTER the signed-cookie
        # check passed -- playback failed with status "Ready". A viewer-request
        # CloudFront Function rewrites the /media/ prefix to /output/ so the
        # edge fetches the real key. Origin-path cannot do this: it prepends to
        # the URI, it cannot strip the matched /media segment.
        media_prefix_rewrite = cloudfront.Function(
            self, "MediaPrefixRewrite",
            comment="Rewrite public /media/<id>/* to output/<id>/* S3 keys",
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {\n"
                "  var request = event.request;\n"
                "  request.uri = request.uri.replace('/media/', '/output/');\n"
                "  return request;\n"
                "}\n"
            ),
        )
        # /api/* origin: the API Gateway HTTP API over HTTPS. HTTPS_ONLY keeps
        # the CloudFront->origin hop (which carries the signed-cookie
        # Set-Cookie) encrypted; the execute-api endpoint's AWS-managed cert
        # terminates it. The HTTP API then reaches the internal ALB privately
        # via the VPC Link.
        api_origin = origins.HttpOrigin(
            api_origin_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            comment="video-streaming single public surface",
            # Serve index.html for the bare root `/` (otherwise S3 returns 403).
            # This is the default (site) behavior only -- it does NOT touch the
            # /media/* signed-cookie 403 refresh path or the /api/* behavior,
            # and deliberately avoids a distribution-wide 403->index mapping.
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=site_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/media/*": cloudfront.BehaviorOptions(
                    origin=media_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    trusted_key_groups=[key_group],
                    response_headers_policy=media_cors,
                    function_associations=[cloudfront.FunctionAssociation(
                        function=media_prefix_rewrite,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )],
                ),
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    # Forward everything EXCEPT the Host header: an API Gateway
                    # custom origin needs the Host to be its own execute-api
                    # domain (SNI + host-based routing), so the viewer Host (the
                    # CloudFront domain) must not override it.
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
            # SPA deep-link fallback: serve index.html for 404s only. We do NOT
            # map 403 -> index.html: CloudFront custom error responses are
            # distribution-wide, so a 403->index.html rule would also rewrite
            # the 403 the /media/* trusted-key-group returns on a missing or
            # expired signed cookie, turning it into a 200 serving index.html.
            # hls.js would then never see the 403 and player.js's cookie-refresh
            # path (onRefresh) would never fire. Keeping only 404->index.html
            # lets genuine /media/* 403s reach the player.
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )

        # S3 CORS on the Output bucket for the localhost dev origins (the other
        # half of MUST-FIX MED_local_media_cors; production is same-origin).
        data.output_bucket.add_cors_rule(
            allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.HEAD],
            allowed_origins=LOCAL_DEV_ORIGINS,
            allowed_headers=["*"],
            max_age=3000,
        )

        # ---- Web-tier ASG (built now that CF domain/key id exist) ----------
        web_user_data = self._web_user_data(
            data=data,
            cf_domain=distribution.distribution_domain_name,
            cf_key_pair_id=public_key.public_key_id,
            role=web_role,
        )
        web_lt = ec2.LaunchTemplate(
            self, "WebLaunchTemplate",
            instance_type=ec2.InstanceType("t3.small"),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            role=web_role,
            security_group=network.web_sg,
            user_data=web_user_data,
            require_imdsv2=True,
            block_devices=[self._gp3_root(WEB_VOLUME_GIB)],
        )
        web_asg = autoscaling.AutoScalingGroup(
            self, "WebAsg",
            vpc=vpc,
            vpc_subnets=private_subnets,
            launch_template=web_lt,
            min_capacity=1,
            max_capacity=2,
            desired_capacity=1,
        )
        web_asg.scale_on_cpu_utilization(
            "WebCpuScaling", target_utilization_percent=60
        )
        listener.add_targets(
            "WebTargets",
            port=WEB_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[web_asg],
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
            ),
        )

        # ---- Worker ASG (c7i.large, min0/max4/desired0) --------------------
        worker_user_data = self._worker_user_data(data=data, role=worker_role)
        worker_lt = ec2.LaunchTemplate(
            self, "WorkerLaunchTemplate",
            instance_type=ec2.InstanceType("c7i.large"),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            role=worker_role,
            security_group=network.worker_sg,
            user_data=worker_user_data,
            require_imdsv2=True,
            block_devices=[self._gp3_root(WORKER_VOLUME_GIB)],
        )
        worker_asg = autoscaling.AutoScalingGroup(
            self, "WorkerAsg",
            vpc=vpc,
            vpc_subnets=private_subnets,
            launch_template=worker_lt,
            min_capacity=0,
            max_capacity=4,
            desired_capacity=0,
        )
        # Pin the physical ASG name so user-data can embed it (above) and the
        # worker role can scope the autoscaling grant to this exact ARN.
        worker_asg.node.default_child.auto_scaling_group_name = WORKER_ASG_NAME
        worker_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "autoscaling:RecordLifecycleActionHeartbeat",
                "autoscaling:CompleteLifecycleAction",
            ],
            resources=[
                (
                    f"arn:aws:autoscaling:{region}:{account}:autoScalingGroup:"
                    f"*:autoScalingGroupName/{WORKER_ASG_NAME}"
                )
            ],
        ))

        # Graceful-drain lifecycle hook (EC2_INSTANCE_TERMINATING, 900s).
        autoscaling.LifecycleHook(
            self, "WorkerDrainHook",
            auto_scaling_group=worker_asg,
            lifecycle_hook_name=WORKER_DRAIN_HOOK,
            lifecycle_transition=autoscaling.LifecycleTransition.INSTANCE_TERMINATING,
            heartbeat_timeout=Duration.seconds(900),
            default_result=autoscaling.DefaultResult.CONTINUE,
        )

        # ---- Worker step scaling: two disjoint one-sided policies ----------
        self._wire_worker_scaling(worker_asg, data.queue)

        # ---- S3 -> SQS event notification ----------------------------------
        self._wire_s3_to_sqs(data)

        # ---- DLQ-marker Lambda ---------------------------------------------
        self._dlq_marker_lambda(data, dlq_log_group)

        # ---- SPA BucketDeployment (invalidates the distribution) -----------
        s3deploy.BucketDeployment(
            self, "SpaDeployment",
            sources=[
                s3deploy.Source.asset(
                    "../frontend",
                    exclude=["config.local.json", "config.json", ".gitignore"],
                ),
                s3deploy.Source.json_data(
                    "config.json",
                    {
                        "apiBaseUrl": "/api",
                        "playbackMode": "cookie",
                        "region": "us-east-1",
                    },
                ),
            ],
            destination_bucket=data.site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ---- Outputs -------------------------------------------------------
        CfnOutput(self, "InputBucketName", value=data.input_bucket.bucket_name)
        CfnOutput(self, "OutputBucketName", value=data.output_bucket.bucket_name)
        CfnOutput(self, "SiteBucketName", value=data.site_bucket.bucket_name)
        CfnOutput(self, "ArtifactBucketName", value=data.artifact_bucket.bucket_name)
        CfnOutput(self, "TableName", value=data.table.table_name)
        CfnOutput(self, "QueueUrl", value=data.queue.queue_url)
        CfnOutput(self, "DlqUrl", value=data.dlq.queue_url)
        CfnOutput(self, "AlbDnsName", value=alb.load_balancer_dns_name)
        CfnOutput(self, "CloudFrontDomain", value=distribution.distribution_domain_name)
        CfnOutput(self, "CfKeyGroupId", value=key_group.key_group_id)
        # MUST-FIX HIGH_cf_public_key_id: the signer needs the PUBLIC KEY id.
        CfnOutput(self, "CfPublicKeyId", value=public_key.public_key_id)
        CfnOutput(self, "CfKeySecretArn", value=data.signing_key_secret.secret_arn)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _gp3_root(size_gib: int) -> ec2.BlockDevice:
        """gp3 root volume sized for the 2 GB upload cap + scratch headroom."""
        return ec2.BlockDevice(
            device_name="/dev/xvda",
            volume=ec2.BlockDeviceVolume.ebs(
                size_gib,
                volume_type=ec2.EbsDeviceVolumeType.GP3,
                encrypted=True,
                delete_on_termination=True,
            ),
        )

    def _stage_and_run(
        self,
        user_data: ec2.UserData,
        assets: list[tuple[str, str, str]],
        role: iam.IRole,
        script_path: str,
        replacements: dict[str, str],
    ) -> None:
        """Download the code assets to /tmp, then run the substituted user-data
        shell script. The @@PLACEHOLDER@@ substitution keeps the deployed env var
        names identical to local dev (NIT_env_injection)."""
        for construct_id, local_path, dest in assets:
            asset = s3_assets.Asset(self, construct_id, path=local_path)
            asset.grant_read(role)
            user_data.add_s3_download_command(
                bucket=asset.bucket,
                bucket_key=asset.s3_object_key,
                local_file=dest,
            )
        script = Path(script_path).read_text()
        for placeholder, value in replacements.items():
            script = script.replace(placeholder, value)
        user_data.add_commands(script)

    def _web_user_data(
        self,
        *,
        data: VideoDataStack,
        cf_domain: str,
        cf_key_pair_id: str,
        role: iam.IRole,
    ) -> ec2.UserData:
        user_data = ec2.UserData.for_linux()
        self._stage_and_run(
            user_data,
            assets=[
                ("WebMainAsset", "../api/main.py", "/tmp/main.py"),
                ("WebSigningAsset", "../api/signing.py", "/tmp/signing.py"),
                ("WebReqAsset", "../api/requirements.txt", "/tmp/requirements.txt"),
                ("WebServiceAsset", "../api/video-web.service", "/tmp/video-web.service"),
            ],
            role=role,
            script_path="../api/user-data.sh",
            replacements={
                "@@INPUT_BUCKET@@": data.input_bucket.bucket_name,
                "@@OUTPUT_BUCKET@@": data.output_bucket.bucket_name,
                "@@TABLE_NAME@@": data.table.table_name,
                "@@ARTIFACT_BUCKET@@": data.artifact_bucket.bucket_name,
                "@@CF_KEY_SECRET_ARN@@": data.signing_key_secret.secret_arn,
                "@@CF_DOMAIN@@": cf_domain,
                "@@CF_KEY_PAIR_ID@@": cf_key_pair_id,
                "@@PLAYBACK_MODE@@": "cookie",
                "@@AWS_REGION@@": "us-east-1",
                "@@MAX_UPLOAD_BYTES@@": str(MAX_UPLOAD_BYTES),
            },
        )
        return user_data

    def _worker_user_data(
        self, *, data: VideoDataStack, role: iam.IRole
    ) -> ec2.UserData:
        user_data = ec2.UserData.for_linux()
        self._stage_and_run(
            user_data,
            assets=[
                ("WorkerCodeAsset", "../worker/worker.py", "/tmp/worker.py"),
                ("WorkerReqAsset", "../worker/requirements.txt", "/tmp/requirements.txt"),
                ("WorkerServiceAsset", "../worker/video-worker.service",
                 "/tmp/video-worker.service"),
            ],
            role=role,
            script_path="../worker/user-data.sh",
            replacements={
                "@@QUEUE_URL@@": data.queue.queue_url,
                "@@INPUT_BUCKET@@": data.input_bucket.bucket_name,
                "@@OUTPUT_BUCKET@@": data.output_bucket.bucket_name,
                "@@TABLE_NAME@@": data.table.table_name,
                "@@ASG_NAME@@": WORKER_ASG_NAME,
                "@@LIFECYCLE_HOOK_NAME@@": WORKER_DRAIN_HOOK,
                "@@ARTIFACT_BUCKET@@": data.artifact_bucket.bucket_name,
                "@@AWS_REGION@@": "us-east-1",
            },
        )
        return user_data

    def _wire_worker_scaling(
        self, worker_asg: autoscaling.AutoScalingGroup, queue
    ) -> None:
        # Scale-out (owns 0->N): visible-backlog bands, set exact capacity.
        backlog = queue.metric_approximate_number_of_messages_visible(
            statistic="Sum", period=Duration.seconds(60)
        )
        scale_out = autoscaling.StepScalingAction(
            self, "WorkerScaleOut",
            auto_scaling_group=worker_asg,
            adjustment_type=autoscaling.AdjustmentType.EXACT_CAPACITY,
        )
        # Bounds are relative to the alarm threshold (1 visible message):
        #   visible 1..19 -> 1, 20..49 -> 2, >=50 -> 4.
        scale_out.add_adjustment(adjustment=1, lower_bound=0, upper_bound=19)
        scale_out.add_adjustment(adjustment=2, lower_bound=19, upper_bound=49)
        scale_out.add_adjustment(adjustment=4, lower_bound=49)
        backlog_alarm = cloudwatch.Alarm(
            self, "QueueBacklogAlarm",
            alarm_name="video-queue-backlog",
            metric=backlog,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        backlog_alarm.add_alarm_action(cw_actions.AutoScalingAction(scale_out))

        # Scale-in (owns N->0): visible + in-flight == 0 for 15 sustained min.
        idle = cloudwatch.MathExpression(
            expression="visible + notvisible",
            using_metrics={
                "visible": queue.metric_approximate_number_of_messages_visible(
                    statistic="Sum", period=Duration.seconds(60)
                ),
                "notvisible": queue.metric_approximate_number_of_messages_not_visible(
                    statistic="Sum", period=Duration.seconds(60)
                ),
            },
            period=Duration.seconds(60),
        )
        scale_in = autoscaling.StepScalingAction(
            self, "WorkerScaleIn",
            auto_scaling_group=worker_asg,
            adjustment_type=autoscaling.AdjustmentType.EXACT_CAPACITY,
        )
        scale_in.add_adjustment(adjustment=0, upper_bound=0)
        idle_alarm = cloudwatch.Alarm(
            self, "QueueIdleAlarm",
            alarm_name="video-queue-idle",
            metric=idle,
            threshold=0,
            evaluation_periods=15,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        idle_alarm.add_alarm_action(cw_actions.AutoScalingAction(scale_in))

    def _wire_s3_to_sqs(self, data: VideoDataStack) -> None:
        # Imported lazily so the module import list stays flat; injects the
        # SourceArn-scoped queue policy automatically.
        from aws_cdk import aws_s3_notifications as s3n

        data.input_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(data.queue),
            s3.NotificationKeyFilter(prefix="input/"),
        )

    def _dlq_marker_lambda(
        self, data: VideoDataStack, log_group: logs.LogGroup
    ) -> None:
        dlq_role = iam.Role(
            self, "DlqMarkerRole",
            role_name="video-dlq-marker-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        # Exactly UpdateItem on the table (no index) + DLQ consume + own logs.
        dlq_role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:UpdateItem"],
            resources=[data.table.table_arn],
        ))
        dlq_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "sqs:ReceiveMessage", "sqs:DeleteMessage",
                "sqs:GetQueueAttributes",
            ],
            resources=[data.dlq.queue_arn],
        ))
        log_group.grant_write(dlq_role)

        fn = lambda_.Function(
            self, "DlqMarkerFunction",
            function_name="video-dlq-failed-marker",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                "lambda/dlq_marker",
                exclude=["tests", "__pycache__", "*.pyc"],
            ),
            role=dlq_role,
            log_group=log_group,
            timeout=Duration.seconds(30),
            environment={"TABLE_NAME": data.table.table_name},
        )
        fn.add_event_source(lambda_sources.SqsEventSource(data.dlq, batch_size=10))
