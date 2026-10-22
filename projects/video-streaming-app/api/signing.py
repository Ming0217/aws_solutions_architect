"""CloudFront signing for the video web tier.

The private RSA key is loaded ONCE at startup (from the FastAPI lifespan hook)
and cached as an in-memory ``RSAPrivateKey`` with a 12h TTL refresh -- it is
never read per request. Playback credentials are signed against a per-video
custom policy:

  - production playback uses CloudFront **signed cookies** scoped to
    ``/media/{video_id}/*`` (one signing op for the whole HLS fan-out);
  - local-dev playback uses CloudFront **signed URLs** plus a rewritten
    playlist whose segment lines are each an absolute signed URL.

Both vehicles use the SAME key and set ``CloudFront-Key-Pair-Id`` to
``CF_KEY_PAIR_ID`` -- the CloudFront **public key** id, not the key-group id
(see DESIGN.md "CloudFront + signed-cookie playback" and the HIGH carry-forward
``HIGH_cf_public_key_id``).

Design: DESIGN.md sections "CloudFront + signed-cookie playback" (Signing-key
caching), "Local-dev approach" (signed-URL rewrite).
"""
from __future__ import annotations

import base64
import json
import logging
import time

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

LOG = logging.getLogger("video-web.signing")

# Re-read the cached key if it is older than this (an operator rotating the
# secret without a redeploy is picked up within one window).
DEFAULT_REFRESH_SECONDS = 12 * 60 * 60

# CloudFront requires RSA-SHA1 over the policy document (not a security hash choice).
_HASH = hashes.SHA1()


def _cf_b64(data: bytes) -> str:
    """Base64 with CloudFront's URL-safe substitutions (+ -> -, = -> _, / -> ~)."""
    return (
        base64.b64encode(data)
        .decode("ascii")
        .replace("+", "-")
        .replace("=", "_")
        .replace("/", "~")
    )


def build_custom_policy(resource: str, ttl: int) -> str:
    """Compact CloudFront custom-policy JSON for one resource, expiring now+ttl."""
    expiry = int(time.time()) + int(ttl)
    policy = {
        "Statement": [
            {
                "Resource": resource,
                "Condition": {"DateLessThan": {"AWS:EpochTime": expiry}},
            }
        ]
    }
    return json.dumps(policy, separators=(",", ":"))


class Signer:
    """Holds the cached private key + the public-key id, and signs playback creds.

    The key is loaded from Secrets Manager (``secret_arn``) in production. For
    local dev / offline smoke, set ``key_file`` to a PEM path and the key is read
    from disk instead -- the production path never sets ``key_file``.
    """

    def __init__(
        self,
        secret_arn: str,
        key_pair_id: str,
        *,
        region: str = "us-east-1",
        key_file: str | None = None,
        refresh_seconds: int = DEFAULT_REFRESH_SECONDS,
        secrets_client: object | None = None,
    ) -> None:
        self._secret_arn = secret_arn
        self.key_pair_id = key_pair_id
        self._region = region
        self._key_file = key_file
        self._refresh_seconds = refresh_seconds
        self._secrets = secrets_client
        self._private_key: rsa.RSAPrivateKey | None = None
        self._loaded_at: float | None = None

    @property
    def loaded(self) -> bool:
        return self._private_key is not None

    def _secrets_client(self) -> object:
        if self._secrets is None:
            self._secrets = boto3.client("secretsmanager", region_name=self._region)
        return self._secrets

    def _read_pem(self) -> bytes:
        """Return the private PEM bytes. Never log the result."""
        if self._key_file:
            with open(self._key_file, "rb") as handle:
                return handle.read()
        resp = self._secrets_client().get_secret_value(SecretId=self._secret_arn)
        material = resp.get("SecretString")
        if material is None:
            material = resp["SecretBinary"]
        return material.encode("utf-8") if isinstance(material, str) else material

    def load(self) -> None:
        """Fetch + parse the private key, replacing any cached copy.

        Raises on failure (ClientError / OSError / ValueError) so the caller can
        decide to fail the health check. The key material is never logged.
        """
        pem = self._read_pem()
        self._private_key = serialization.load_pem_private_key(pem, password=None)
        self._loaded_at = time.time()

    def ensure_fresh(self) -> None:
        """Re-load if the cached key is older than the refresh TTL (best effort)."""
        if self._private_key is None or self._loaded_at is None:
            return
        if (time.time() - self._loaded_at) < self._refresh_seconds:
            return
        try:
            self.load()
        except (ClientError, OSError, ValueError):
            LOG.warning("signing-key refresh failed; reusing cached key", exc_info=True)

    def _sign(self, data: bytes) -> bytes:
        if self._private_key is None:
            raise RuntimeError("signing key not loaded")
        return self._private_key.sign(data, padding.PKCS1v15(), _HASH)

    def sign_cookies(self, resource: str, ttl: int) -> dict[str, str]:
        """Return the three CloudFront signed cookies for a custom policy."""
        self.ensure_fresh()
        policy = build_custom_policy(resource, ttl).encode("utf-8")
        signature = self._sign(policy)
        return {
            "CloudFront-Policy": _cf_b64(policy),
            "CloudFront-Signature": _cf_b64(signature),
            "CloudFront-Key-Pair-Id": self.key_pair_id,
        }

    def sign_url(self, url: str, ttl: int) -> str:
        """Return ``url`` with CloudFront custom-policy signing query params."""
        self.ensure_fresh()
        policy = build_custom_policy(url, ttl).encode("utf-8")
        signature = self._sign(policy)
        params = (
            f"Policy={_cf_b64(policy)}"
            f"&Signature={_cf_b64(signature)}"
            f"&Key-Pair-Id={self.key_pair_id}"
        )
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{params}"


def rewrite_playlist(
    playlist_text: str, media_base_url: str, signer: Signer, ttl: int
) -> str:
    """Rewrite each relative segment line to an absolute CloudFront signed URL.

    Local-dev only: a browser on 127.0.0.1 cannot attach a CloudFront-domain
    cookie, so the playlist is rewritten to per-segment signed URLs. Comment /
    tag lines (``#...``) and blank lines are passed through unchanged.
    """
    base = media_base_url.rstrip("/")
    out: list[str] = []
    for line in playlist_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.append(signer.sign_url(f"{base}/{stripped}", ttl))
        else:
            out.append(line)
    return "\n".join(out) + "\n"
