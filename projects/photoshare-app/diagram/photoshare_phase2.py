"""PhotoShare — Phase 2 architecture, as code (mingrammer `diagrams`).

Renders THREE focused views (PNG + SVG) from the Phase 2 topology in
../iac/photoshare-phase2.yaml, so each stays readable:

  1. photoshare_phase2.*           — main: request path + data tier (Multi-AZ) + security
  2. photoshare_phase2_build_ops.* — build & ops: CodeBuild/ECR, Session Manager, CloudWatch
  3. photoshare_phase2_pipeline.*  — async image pipeline: S3 event -> Lambda -> ALB callback

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
# View 1 — MAIN: request path (left->right) + data tier (Multi-AZ) + security
# --------------------------------------------------------------------------- #
with Diagram(
    "",
    filename="photoshare_phase2",
    outformat=OUT,
    show=False,
    direction="LR",
    graph_attr=graph_attr,
):
    user = Users("Internet user / browser")

    with Cluster("AWS Region: us-east-1"):
        igw = InternetGateway("Internet Gateway")

        with Cluster("VPC 10.0.0.0/16"):
            with Cluster("Public subnets (AZ-1a + 1b)"):
                alb = ElbApplicationLoadBalancer("Application Load Balancer\n(spans 2 AZs)")
                nat = NATGateway("NAT Gateway\n(AZ-1a)")
            with Cluster("AZ us-east-1a - private 10.0.2.0/24"):
                ec2_a = EC2("EC2 web (ASG)")
                rds_p = RDS("RDS MySQL\nPRIMARY")
            with Cluster("AZ us-east-1b - private 10.0.4.0/24"):
                ec2_b = EC2("EC2 web (ASG)")
                rds_s = RDS("RDS MySQL\nSTANDBY")

        with Cluster("Managed services (outside the VPC)"):
            s3 = S3("S3 image bucket\n(Block Public Access)")
            sm = SecretsManager("Secrets Manager")
            kms = KeyManagementService("KMS")

    # Request path reads left-to-right: user and IGW sit together on the entry side.
    user >> Edge(label="HTTPS") >> igw >> Edge(label="HTTP") >> alb
    alb >> ec2_a
    alb >> ec2_b

    # Data tier (private) + Multi-AZ
    ec2_a >> Edge(label="3306") >> rds_p
    ec2_b >> Edge(label="3306") >> rds_p
    rds_p - Edge(label="sync standby", style="dashed", color="firebrick") - rds_s

    # Outbound egress via the single NAT, then back out the IGW
    ec2_a >> Edge(label="egress") >> nat
    nat >> igw

    # Secrets at runtime (no hardcoded creds)
    ec2_a >> Edge(label="secret") >> sm >> Edge(label="decrypt") >> kms

    # Web tier stores / serves photos in S3 (async processing is in view 3)
    ec2_a >> Edge(label="photos") >> s3

# --------------------------------------------------------------------------- #
# View 2 — BUILD & OPS: image to the fleet, logging, admin
# --------------------------------------------------------------------------- #
with Diagram(
    "",
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

# --------------------------------------------------------------------------- #
# View 3 — ASYNC IMAGE PIPELINE: S3 event -> Lambda -> callback through the ALB
# --------------------------------------------------------------------------- #
with Diagram(
    "",
    filename="photoshare_phase2_pipeline",
    outformat=OUT,
    show=False,
    direction="LR",
    graph_attr=graph_attr,
):
    s3 = S3("S3 image bucket")
    lam = Lambda("Lambda image\nprocessor (no VPC)")
    alb = ElbApplicationLoadBalancer("ALB\n(web app callback)")
    dlq = SQS("SQS DLQ")

    s3 >> Edge(label="ObjectCreated event") >> lam
    lam >> Edge(label="callback via ALB public DNS\n(web app writes metadata to RDS)") >> alb
    lam >> Edge(label="on repeated failure") >> dlq
