"""VideoNetworkStack -- VPC, subnets, NAT, VPC endpoints, security groups.

See DESIGN.md "VPC / subnet / NAT / VPC-endpoint layout" and "VPC security
groups". The VPC is defined IN-STACK (no ``from_lookup``) so synth resolves
deterministic subnet CIDRs with no AWS context lookup. Admin access is Session
Manager only -- no security group anywhere opens port 22.
"""
from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

# gunicorn/uvicorn port the web tier listens on behind the ALB.
WEB_PORT = 8000


class VideoNetworkStack(Stack):
    @property
    def availability_zones(self) -> list[str]:
        # Pin the two AZs so the in-stack VPC resolves deterministically at synth
        # without hitting the availability-zones context provider (which assumes
        # the CDK lookup role and needs live credentials). Keeps synth
        # credential-free, per the QUIRK in the task context.
        return ["us-east-1a", "us-east-1b"]

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # One VPC, two AZs. Public subnets host only the single NAT gateway; the
        # internal ALB, web ASG, and worker ASG all live in the private subnets.
        self.vpc = ec2.Vpc(
            self,
            "VideoVpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # Gateway endpoints (free) -- S3/DynamoDB traffic stays off NAT.
        self.vpc.add_gateway_endpoint(
            "S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3
        )
        self.vpc.add_gateway_endpoint(
            "DynamoDbEndpoint", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB
        )

        # Interface endpoints -- SQS, Secrets Manager (signing-key reads stay on
        # the AWS network), and the three SSM endpoints so Session Manager works
        # with no inbound path.
        self.vpc.add_interface_endpoint(
            "SqsEndpoint", service=ec2.InterfaceVpcEndpointAwsService.SQS
        )
        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        )
        self.vpc.add_interface_endpoint(
            "SsmEndpoint", service=ec2.InterfaceVpcEndpointAwsService.SSM
        )
        self.vpc.add_interface_endpoint(
            "SsmMessagesEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES,
        )
        self.vpc.add_interface_endpoint(
            "Ec2MessagesEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES,
        )

        # --- Security groups (private-by-default, least ingress) -------------
        self.alb_sg = ec2.SecurityGroup(
            self,
            "AlbSg",
            vpc=self.vpc,
            description="Internal ALB: inbound 80 from the API Gateway VPC Link only",
            allow_all_outbound=False,
        )
        self.web_sg = ec2.SecurityGroup(
            self,
            "WebSg",
            vpc=self.vpc,
            description="Web tier: inbound 8000 from alb-sg only",
            allow_all_outbound=True,
        )
        self.worker_sg = ec2.SecurityGroup(
            self,
            "WorkerSg",
            vpc=self.vpc,
            description="Worker: no inbound",
            allow_all_outbound=True,
        )
        # The API Gateway HTTP API reaches the internal ALB through a VPC Link
        # whose ENIs live in the private subnets carrying this SG. It is the
        # only peer allowed into the ALB (the ALB stays internal, no public IP).
        self.vpclink_sg = ec2.SecurityGroup(
            self,
            "VpcLinkSg",
            vpc=self.vpc,
            description="API Gateway HTTP API VPC Link ENIs (private subnets)",
            allow_all_outbound=False,
        )

        # alb-sg inbound TCP 80 from the VPC Link SG only -- NOT 0.0.0.0/0 and
        # not a private-CIDR range. The HTTP API VPC Link is the sole path from
        # CloudFront's /api/* behaviour (CloudFront -> API Gateway over HTTPS ->
        # VPC Link -> internal ALB), so its SG is the exact, referenceable
        # ingress source. See DESIGN.md "security groups -> alb-sg".
        self.alb_sg.add_ingress_rule(
            peer=self.vpclink_sg,
            connection=ec2.Port.tcp(80),
            description="From API Gateway VPC Link only",
        )

        # VPC Link egress to the internal ALB on the listener port only.
        self.vpclink_sg.add_egress_rule(
            peer=self.alb_sg,
            connection=ec2.Port.tcp(80),
            description="To internal ALB (HTTP listener)",
        )

        # alb-sg egress to the web tier on the app port only.
        self.alb_sg.add_egress_rule(
            peer=self.web_sg,
            connection=ec2.Port.tcp(WEB_PORT),
            description="To web tier (gunicorn/uvicorn)",
        )

        # web-sg inbound only from alb-sg on the app port.
        self.web_sg.add_ingress_rule(
            peer=self.alb_sg,
            connection=ec2.Port.tcp(WEB_PORT),
            description="From internal ALB only",
        )

        # worker-sg: no inbound rules at all (intentionally none added).
