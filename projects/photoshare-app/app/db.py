"""
Database helper — fetches RDS credentials from Secrets Manager at runtime and
opens a MySQL connection. No credentials ever live in code or env files.

The secret (photoshare/db-credentials) is populated by CloudFormation's
SecretTargetAttachment, so after the RDS instance exists it contains:
  host, port, username, password, dbname, engine

LOCAL MODE (testing only): set LOCAL_DB=1 to read DB config straight from env
vars (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME) and skip Secrets Manager.
This exists so the app can be smoke-tested locally without any AWS dependency.
"""
import json
import os

import pymysql

LOCAL_DB = os.environ.get("LOCAL_DB") == "1"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SECRET_NAME = os.environ.get("AWS_SECRET_NAME")  # required only in AWS mode

_cache: dict | None = None
_secrets = None  # lazy boto3 client (not imported/created in local mode)


def _load_secret() -> dict:
    global _cache, _secrets
    if _cache is None:
        import boto3  # imported lazily so local mode needs no AWS at all
        if _secrets is None:
            _secrets = boto3.client("secretsmanager", region_name=AWS_REGION)
        raw = _secrets.get_secret_value(SecretId=SECRET_NAME)["SecretString"]
        _cache = json.loads(raw)
    return _cache


def get_conn():
    if LOCAL_DB:
        return pymysql.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_PASSWORD", ""),
            database=os.environ.get("DB_NAME", "photoshare"),
            connect_timeout=5,
            autocommit=False,
        )
    s = _load_secret()
    return pymysql.connect(
        host=s["host"],
        port=int(s.get("port", 3306)),
        user=s["username"],
        password=s["password"],
        database=s.get("dbname", os.environ.get("DB_NAME", "photoshare")),
        connect_timeout=5,
        autocommit=False,
    )


def init_schema():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS photos (
                    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
                    title        VARCHAR(255),
                    s3_key       VARCHAR(512) NOT NULL UNIQUE,
                    content_type VARCHAR(128),
                    size_bytes   BIGINT,
                    width        INT,
                    height       INT,
                    image_format VARCHAR(16),
                    status       VARCHAR(32) NOT NULL DEFAULT 'uploaded',
                    created_at   DATETIME NOT NULL
                )
                """
            )
        conn.commit()
    finally:
        conn.close()
