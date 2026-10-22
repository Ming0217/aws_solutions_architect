#!/usr/bin/env python3
"""CDK app entrypoint for the hardened video-streaming platform.

Three stacks, split along lifecycle/teardown boundaries (see DESIGN.md "CDK
stack decomposition"):

* ``VideoNetworkStack`` -- VPC, subnets, NAT, VPC endpoints, security groups.
* ``VideoDataStack``    -- S3 buckets, DynamoDB, SQS + DLQ, signing-key secret.
* ``VideoAppStack``     -- ALB, ASGs, CloudFront, DLQ-marker Lambda, outputs.

The account/region are pinned explicitly so synth stays credential-free: the
in-stack VPC resolves deterministic subnet CIDRs and the buckets resolve their
fixed ``<account>-<region>`` names without any AWS context lookup.
"""
import aws_cdk as cdk

from stacks.app_stack import VideoAppStack
from stacks.data_stack import VideoDataStack
from stacks.network_stack import VideoNetworkStack

ENV = cdk.Environment(account="678602035067", region="us-east-1")

app = cdk.App()

network = VideoNetworkStack(app, "VideoNetworkStack", env=ENV)
data = VideoDataStack(app, "VideoDataStack", env=ENV)
VideoAppStack(
    app,
    "VideoAppStack",
    network=network,
    data=data,
    env=ENV,
)

app.synth()
