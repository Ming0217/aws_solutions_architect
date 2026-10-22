"""Empty conftest at the api/ root so pytest adds this directory to sys.path,
making `main` and `signing` importable from tests/.

It also sets dummy AWS credentials + the stub env the app reads at import time,
so `import main` works offline (botocore.stub.Stubber short-circuits the calls).
"""
import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")

os.environ.setdefault("INPUT_BUCKET", "video-input-678602035067-us-east-1")
os.environ.setdefault("OUTPUT_BUCKET", "video-output-678602035067-us-east-1")
os.environ.setdefault("TABLE_NAME", "VideoCatalog")
os.environ.setdefault("ARTIFACT_BUCKET", "video-artifacts-678602035067-us-east-1")
os.environ.setdefault(
    "CF_KEY_SECRET_ARN",
    "arn:aws:secretsmanager:us-east-1:678602035067:secret:video/cf-signing-key",
)
os.environ.setdefault("CF_DOMAIN", "d123456abcdef.cloudfront.net")
os.environ.setdefault("CF_KEY_PAIR_ID", "K2EXAMPLEKEYID")
