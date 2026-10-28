"""PhotoShare — Phase 2 architecture, as code (mingrammer `diagrams`).

Renders TWO views (PNG + SVG) from the Phase 2 topology in
../iac/photoshare-phase2.yaml, to keep each uncluttered:

  1. photoshare_phase2.*           — main: request + data + security + image pipeline
  2. photoshare_phase2_build_ops.* — build & ops: CodeBuild/ECR, CloudWatch, Session Manager

Run:
    python -m venv .venv && source .venv/bin/activate
    pip install diagrams            # requires Graphviz: `brew install graphviz`
    python photoshare_phase2.py     # -> *.png and *.svg
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import Users
from diagrams.aws.network import InternetGateway, NATGateway, ElbApplicationLoadBalancer
from diagrams.aws.compute import EC2, Lambda, EC2ContainerRegistry
from diagrams.aws.database import RDS
from diagrams.aws.storage import S3
from diagrams.aws.security import SecretsManager, KeyManagementService
from diagrams.aws.integration import SQS
from diagrams.aws.management import Cloudwatch, SystemsManager
from diagrams.aws.devtools import Codebuild

graph_attr = {"fontsize": "20", "bgcolor": "white", "nodesep": "0.6", "ranksep": "1.1"}
OUT = ["png", "svg"]

# --------------------------------------------------------------------------- #
# View 1 — MAIN: request path + data tier + security + image pipeline
# --------------------------------------------------------------------------- #
with Diagram(
    "PhotoShare - Phase 2 (main)",
    filename="photoshare_phase2",
    outformat=OUT,
    show=False,
    direction="TB",
    graph_attr=graph_attr,
):
    user = Users("Internet user / browser")

    with Cluster("AWS Region: us-east-1"):
        igw = InternetGateway("Internet Gateway")

        with Cluster("VPC 10.0.0.0/16"):
            with Cluster("AZ us-east-1a"):
                with Cluster("Public subnet 10.0.1.0/24"):
                    alb_a = ElbApplicationLoadBalancer("ALB node")
                    nat = NATGateway("NAT Gateway")
                with Cluster("Private subnet 10.0.2.0/24"):
                    ec2_a = EC2("EC2 web (ASG)")
                    rds_p = RDS("RDS MySQL\nPRIMARY")
            with Cluster("AZ us-east-1b"):
                with Cluster("Public subnet 10.0.3.0/24"):
                    alb_b = ElbApplicationLoadBalancer("ALB node")
                with Cluster("Private subnet 10.0.4.0/24"):
                    ec2_b = EC2("EC2 web (ASG)")
                    rds_s = RDS("RDS MySQL\nSTANDBY")

        with Cluster("Managed services (outside the VPC)"):
            s3 = S3("S3 image bucket\n(Block Public Access)")
            lam = Lambda("Lambda image\nprocessor (no VPC)")
            dlq = SQS("SQS DLQ")
            sm = SecretsManager("Secrets Manager\nDB credentials")
            kms = KeyManagementService("KMS\naws/secretsmanager")

    # Bias layout so AZ us-east-1a sits left of us-east-1b.
    alb_a >> Edge(style="invis") >> alb_b

    # Request path
    user >> Edge(label="HTTPS") >> igw
    igw >> alb_a
    igw >> alb_b
    alb_a >> Edge(label="HTTP") >> ec2_a
    alb_b >> Edge(label="HTTP") >> ec2_b

    # Data tier (private) + Multi-AZ
    ec2_a >> Edge(label="MySQL 3306") >> rds_p
    ec2_b >> Edge(label="MySQL 3306") >> rds_p
    rds_p - Edge(label="synchronous standby", style="dashed", color="firebrick") - rds_s

    # Outbound egress via the single NAT (AZ-a)
    ec2_a >> Edge(label="outbound") >> nat
    ec2_b >> Edge(label="outbound") >> nat
    nat >> igw

    # Secrets at runtime (the no-hardcoded-creds story)
    ec2_a >> Edge(label="read DB password") >> sm
    sm >> Edge(label="decrypt") >> kms

    # Image pipeline: S3 event -> Lambda -> callback through the ALB
    ec2_a >> Edge(label="upload / serve photos") >> s3
    s3 >> Edge(label="ObjectCreated") >> lam
    lam >> Edge(label="callback via ALB DNS") >> igw
    lam >> Edge(label="on repeated failure") >> dlq

# --------------------------------------------------------------------------- #
# View 2 — BUILD & OPS: image pipeline to the fleet, logging, admin
# --------------------------------------------------------------------------- #
with Diagram(
    "PhotoShare - Phase 2 (build & ops)",
    filename="photoshare_phase2_build_ops",
    outformat=OUT,
    show=False,
    direction="LR",
    graph_attr=graph_attr,
):
    cb = Codebuild("CodeBuild\nbuilds image")
    ecr = EC2ContainerRegistry("ECR\napp image")
    ssm = SystemsManager("Session Manager\nadmin, no SSH")
    cw = Cloudwatch("CloudWatch\nlogs, metrics, alarms")

    with Cluster("VPC — private subnets"):
        ec2 = EC2("EC2 web (ASG)")

    lam = Lambda("Lambda image\nprocessor")

    cb >> Edge(label="push") >> ecr >> Edge(label="image pull on launch") >> ec2
    ssm >> Edge(label="admin session", style="dashed") >> ec2
    ec2 >> Edge(label="logs / metrics") >> cw
    lam >> Edge(label="logs / metrics") >> cw
