"""
Minimal AWS Secrets Manager access for local CLI scripts (e.g. Docker Hub push).
Only depends on boto3 — avoids importing shared.helpers (ics, PIL, thefuzz, …).
Behavior matches helpers.get_secret for Lambda vs file-based secrets.
"""
from __future__ import annotations

import json
import os
import sys


def _use_secrets_manager() -> bool:
    """True when push2dockerhub.sh sets AWS_LAMBDA_FUNCTION_NAME to force SM path."""
    return os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None


def get_secret(secret_key: str):
    """
    Read a key from AWS Secrets Manager JSON secret, or from MY_SECRET_FILE/<key> on disk.
    """
    if _use_secrets_manager():
        import boto3

        session = boto3.session.Session()
        client = session.client(
            service_name="secretsmanager",
            region_name=os.getenv("awsRegion"),
        )
        response = client.get_secret_value(
            SecretId=os.getenv("awsSecretName", "prod/refPortalSecret")
        )
        pairs = json.loads(response["SecretString"])
        return pairs.get(secret_key)

    base = os.getenv("MY_SECRET_FOLDER", "/run/secrets/")
    path = base + secret_key
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error Secret: file not found: {path}", file=sys.stderr)
        return None
    except OSError as e:
        print(f"Error secret: {e}", file=sys.stderr)
        return None
