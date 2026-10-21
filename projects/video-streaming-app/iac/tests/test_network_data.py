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
