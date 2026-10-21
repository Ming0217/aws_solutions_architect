#!/bin/bash
# Web-tier launch-template user-data. Runs once on first boot (Amazon Linux 2023).
#
# Placeholders in @@...@@ are substituted by the CDK launch template from
# resolved references (FEAT-005) so the deployed EnvironmentFile uses the exact
# same env var names the app reads locally:
#   @@INPUT_BUCKET@@ @@OUTPUT_BUCKET@@ @@TABLE_NAME@@ @@ARTIFACT_BUCKET@@
#   @@CF_KEY_SECRET_ARN@@ @@CF_DOMAIN@@ @@CF_KEY_PAIR_ID@@ @@PLAYBACK_MODE@@
#   @@AWS_REGION@@ @@MAX_UPLOAD_BYTES@@
# CF_SIGNING_KEY_FILE is deliberately NOT written here: in AWS the private PEM
# is read from Secrets Manager (CF_KEY_SECRET_ARN).
set -euo pipefail

# --- unprivileged service account -------------------------------------------
if ! id appuser >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin appuser
fi

# --- app code + venv ---------------------------------------------------------
install -d -o appuser -g appuser /opt/video-web
install -o appuser -g appuser -m 0644 /tmp/main.py    /opt/video-web/main.py
install -o appuser -g appuser -m 0644 /tmp/signing.py /opt/video-web/signing.py
install -o appuser -g appuser -m 0644 /tmp/requirements.txt /opt/video-web/requirements.txt

python3 -m venv /opt/video-web/.venv
/opt/video-web/.venv/bin/pip install --upgrade pip
/opt/video-web/.venv/bin/pip install -r /opt/video-web/requirements.txt
chown -R appuser:appuser /opt/video-web/.venv

# --- systemd EnvironmentFile from CDK-injected values ------------------------
# Same var names as local dev so one code path serves both.
cat > /etc/video-web.env <<EOF
INPUT_BUCKET=@@INPUT_BUCKET@@
OUTPUT_BUCKET=@@OUTPUT_BUCKET@@
TABLE_NAME=@@TABLE_NAME@@
ARTIFACT_BUCKET=@@ARTIFACT_BUCKET@@
CF_KEY_SECRET_ARN=@@CF_KEY_SECRET_ARN@@
CF_DOMAIN=@@CF_DOMAIN@@
CF_KEY_PAIR_ID=@@CF_KEY_PAIR_ID@@
PLAYBACK_MODE=@@PLAYBACK_MODE@@
AWS_REGION=@@AWS_REGION@@
MAX_UPLOAD_BYTES=@@MAX_UPLOAD_BYTES@@
EOF
chmod 0640 /etc/video-web.env
chown root:appuser /etc/video-web.env

# --- systemd unit ------------------------------------------------------------
install -m 0644 /tmp/video-web.service /etc/systemd/system/video-web.service
systemctl daemon-reload
systemctl enable --now video-web.service
