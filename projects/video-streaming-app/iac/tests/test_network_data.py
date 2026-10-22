"""Template assertions for VideoNetworkStack + VideoDataStack (FEAT-001)."""
import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.data_stack import VideoDataStack
from stacks.network_stack import VideoNetworkStack

ENV = cdk.Environment(account="678602035067", region="us-east-1")

_NET: Template | None = None
_DATA: Template | None = None


def _templates() -> tuple[Template, Template]:
    """Synthesize both stacks once and cache the templates."""
    global _NET, _DATA
    if _NET is None or _DATA is None:
        app = cdk.App()
        net = VideoNetworkStack(app, "VideoNetworkStack", env=ENV)
        data = VideoDataStack(app, "VideoDataStack", env=ENV)
        _NET = Template.from_stack(net)
        _DATA = Template.from_stack(data)
    return _NET, _DATA


def test_queue_visibility_timeout_is_900():
    _, data = _templates()
    data.has_resource_properties("AWS::SQS::Queue", {"VisibilityTimeout": 900})


def test_dlq_max_receive_count_is_3():
    _, data = _templates()
    data.has_resource_properties(
        "AWS::SQS::Queue",
        {"RedrivePolicy": Match.object_like({"maxReceiveCount": 3})},
    )


def test_all_four_buckets_block_public_access():
    _, data = _templates()
    buckets = data.find_resources("AWS::S3::Bucket")
    assert len(buckets) == 4
    for res in buckets.values():
        bpa = res["Properties"]["PublicAccessBlockConfiguration"]
        assert bpa["BlockPublicAcls"] is True
        assert bpa["BlockPublicPolicy"] is True
        assert bpa["IgnorePublicAcls"] is True
        assert bpa["RestrictPublicBuckets"] is True


def test_table_has_by_status_created_gsi():
    _, data = _templates()
    data.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "GlobalSecondaryIndexes": Match.array_with(
                [Match.object_like({"IndexName": "by-status-created"})]
            )
        },
    )


def test_no_security_group_opens_port_22():
    net, _ = _templates()
    for res in net.find_resources("AWS::EC2::SecurityGroup").values():
        for rule in res["Properties"].get("SecurityGroupIngress", []):
            from_port = rule.get("FromPort")
            to_port = rule.get("ToPort")
            if from_port is not None and to_port is not None:
                assert not (from_port <= 22 <= to_port), f"port 22 exposed: {rule}"


def _all_ingress_rules(net: Template) -> list[dict]:
    """Inline SG ingress plus standalone SecurityGroupIngress resources."""
    rules: list[dict] = []
    for res in net.find_resources("AWS::EC2::SecurityGroup").values():
        rules.extend(res["Properties"].get("SecurityGroupIngress", []))
    for res in net.find_resources("AWS::EC2::SecurityGroupIngress").values():
        rules.append(res["Properties"])
    return rules


def test_no_security_group_opens_the_alb_to_the_internet():
    # Finding-3 remediation: the ALB ingress is the VPC Link SG only -- no rule
    # may grant 0.0.0.0/0 on the ALB listener port (80).
    net, _ = _templates()
    for rule in _all_ingress_rules(net):
        if rule.get("CidrIp") == "0.0.0.0/0":
            from_port = rule.get("FromPort")
            to_port = rule.get("ToPort")
            if from_port is not None and to_port is not None:
                assert not (from_port <= 80 <= to_port), f"ALB open: {rule}"


def test_alb_ingress_is_the_vpc_link_sg():
    # The VPC Link SG exists and the ALB admits TCP 80 from a source SG (the
    # VPC Link), never a CIDR. The old private-subnet-CIDR ingress is gone.
    net, _ = _templates()
    sgs = net.find_resources("AWS::EC2::SecurityGroup")
    assert any(
        "VPC Link" in sg["Properties"].get("GroupDescription", "")
        for sg in sgs.values()
    ), "VPC Link SG missing"
    port80 = [
        r for r in _all_ingress_rules(net)
        if r.get("FromPort") == 80 and r.get("ToPort") == 80
    ]
    assert port80, "no TCP 80 ingress on the ALB"
    for rule in port80:
        assert "CidrIp" not in rule, f"ALB 80 ingress uses a CIDR: {rule}"
        assert "SourceSecurityGroupId" in rule, f"not SG-sourced: {rule}"
