#!/bin/bash
# Worker launch-template user-data. Runs once on first boot (Amazon Linux 2023).
#
# Placeholders in @@...@@ are substituted by the CDK launch template from
# resolved references (FEAT-005) so the deployed EnvironmentFile uses the exact
# same env var names the worker reads locally:
#   @@QUEUE_URL@@ @@INPUT_BUCKET@@ @@OUTPUT_BUCKET@@ @@TABLE_NAME@@
#   @@ASG_NAME@@ @@LIFECYCLE_HOOK_NAME@@ @@ARTIFACT_BUCKET@@ @@AWS_REGION@@
set -euo pipefail

ARTIFACT_BUCKET="@@ARTIFACT_BUCKET@@"
AWS_REGION="@@AWS_REGION@@"

# --- FFmpeg: pull the pinned static build from our own artifact bucket -------
# (served over the S3 gateway endpoint; never the flaky third-party host).
aws s3 cp "s3://${ARTIFACT_BUCKET}/ffmpeg/ffmpeg"  /usr/local/bin/ffmpeg  --region "${AWS_REGION}"
aws s3 cp "s3://${ARTIFACT_BUCKET}/ffmpeg/ffprobe" /usr/local/bin/ffprobe --region "${AWS_REGION}"
chmod 0755 /usr/local/bin/ffmpeg /usr/local/bin/ffprobe

# --- unprivileged service account -------------------------------------------
if ! id appuser >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin appuser
fi

# --- worker code -------------------------------------------------------------
install -d -o appuser -g appuser /opt/video-worker
install -o appuser -g appuser -m 0644 /tmp/worker.py /opt/video-worker/worker.py

# --- systemd EnvironmentFile from CDK-injected values ------------------------
# Same var names as local dev so one code path serves both.
cat > /etc/video-worker.env <<EOF
QUEUE_URL=@@QUEUE_URL@@
INPUT_BUCKET=@@INPUT_BUCKET@@
OUTPUT_BUCKET=@@OUTPUT_BUCKET@@
TABLE_NAME=@@TABLE_NAME@@
ASG_NAME=@@ASG_NAME@@
LIFECYCLE_HOOK_NAME=@@LIFECYCLE_HOOK_NAME@@
AWS_REGION=@@AWS_REGION@@
FFMPEG_BIN=/usr/local/bin/ffmpeg
EOF
chmod 0640 /etc/video-worker.env
chown root:appuser /etc/video-worker.env

# --- systemd unit ------------------------------------------------------------
install -m 0644 /tmp/video-worker.service /etc/systemd/system/video-worker.service
systemctl daemon-reload
systemctl enable --now video-worker.service
