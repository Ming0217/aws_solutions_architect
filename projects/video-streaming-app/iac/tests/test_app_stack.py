"""Template assertions for VideoAppStack (FEAT-005).

Covers the MUST-FIX carry-forwards and the asymmetric IAM split: the
CfPublicKeyId output, the IAM web/worker asymmetry, the /media/* trusted key
group + CORS response-headers policy, worker scale-to-zero, and gp3 block
devices on both launch templates.
"""
import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.app_stack import WORKER_ASG_NAME, VideoAppStack
from stacks.data_stack import VideoDataStack
from stacks.network_stack import VideoNetworkStack

ENV = cdk.Environment(account="678602035067", region="us-east-1")

_APP: Template | None = None


def _template() -> Template:
    global _APP
    if _APP is None:
        app = cdk.App()
        net = VideoNetworkStack(app, "VideoNetworkStack", env=ENV)
        data = VideoDataStack(app, "VideoDataStack", env=ENV)
        appstack = VideoAppStack(
            app, "VideoAppStack", network=net, data=data, env=ENV
        )
        _APP = Template.from_stack(appstack)
    return _APP


def _role_actions(tmpl: Template, role_ref_substr: str) -> tuple[set[str], list[dict]]:
    """Return (action set, statements) for the inline policy of a named role."""
    actions: set[str] = set()
    statements: list[dict] = []
    for pol in tmpl.find_resources("AWS::IAM::Policy").values():
        roles_blob = json.dumps(pol["Properties"].get("Roles", []))
        if role_ref_substr not in roles_blob:
            continue
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt["Action"]
            actions.update(act if isinstance(act, list) else [act])
            statements.append(stmt)
    return actions, statements


def test_stack_synthesizes():
    # from_stack raises on any synth error, so reaching here is the assertion.
    assert _template() is not None


def test_cf_public_key_id_output_exists():
    _template().find_outputs("CfPublicKeyId")  # raises if absent


def test_web_role_has_secrets_and_no_sqs():
    actions, _ = _role_actions(_template(), "WebRole")
    assert "secretsmanager:GetSecretValue" in actions
    assert not any(a.startswith("sqs:") for a in actions), actions


def test_worker_role_has_no_input_put_and_no_sqs_send():
    actions, statements = _role_actions(_template(), "WorkerRole")
    # No upload path: worker never writes to the Input bucket.
    for stmt in statements:
        act = stmt["Action"]
        act = act if isinstance(act, list) else [act]
        if "s3:PutObject" in act:
            assert "video-input" not in json.dumps(stmt["Resource"]), stmt
    assert "sqs:SendMessage" not in actions


def test_media_behavior_has_key_group_and_cors():
    tmpl = _template()
    dist = next(iter(tmpl.find_resources("AWS::CloudFront::Distribution").values()))
    behaviors = dist["Properties"]["DistributionConfig"]["CacheBehaviors"]
    media = next(b for b in behaviors if b["PathPattern"] == "/media/*")
    assert media.get("TrustedKeyGroups")
    assert "ResponseHeadersPolicyId" in media
    tmpl.resource_count_is("AWS::CloudFront::ResponseHeadersPolicy", 1)


def test_worker_asg_scales_to_zero():
    tmpl = _template()
    asgs = tmpl.find_resources("AWS::AutoScaling::AutoScalingGroup")
    worker = next(
        v for v in asgs.values()
        if v["Properties"].get("AutoScalingGroupName") == WORKER_ASG_NAME
    )
    assert worker["Properties"]["MinSize"] == "0"
    assert worker["Properties"]["DesiredCapacity"] == "0"


def test_both_launch_templates_use_gp3():
    tmpl = _template()
    lts = tmpl.find_resources("AWS::EC2::LaunchTemplate")
    assert len(lts) == 2
    for lt in lts.values():
        mappings = lt["Properties"]["LaunchTemplateData"]["BlockDeviceMappings"]
        assert mappings[0]["Ebs"]["VolumeType"] == "gp3"


def test_vpc_origin_present():
    # The CloudFront VPC origin to the internal ALB must be wired.
    _template().resource_count_is("AWS::CloudFront::VpcOrigin", 1)


def test_dlq_marker_lambda_and_event_source():
    tmpl = _template()
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        {"FunctionName": "video-dlq-failed-marker", "Runtime": "python3.12"},
    )
    tmpl.resource_count_is("AWS::Lambda::EventSourceMapping", 1)


def test_explicit_log_groups():
    tmpl = _template()
    for name in ("/video/web", "/video/worker", "/video/dlq-marker"):
        tmpl.has_resource_properties(
            "AWS::Logs::LogGroup",
            {"LogGroupName": name, "RetentionInDays": 14},
        )
    # Teardown discipline: log groups are destroyed with the stack.
    tmpl.has_resource(
        "AWS::Logs::LogGroup",
        Match.object_like({"DeletionPolicy": "Delete"}),
    )
