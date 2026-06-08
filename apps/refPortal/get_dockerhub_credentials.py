#!/usr/bin/env python3
"""
Docker Hub credentials from AWS Secrets Manager (or MY_SECRET_FILE).
Uses shared.aws_secrets_minimal (boto3 only) — no full helpers import.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from shared.aws_secrets_minimal import get_secret


def get_dockerhub_credentials():
    try:
        username = get_secret("dockerhub_username")
        password = get_secret("dockerhub_password")

        if not username or not password:
            print("Error: Docker Hub credentials not found in AWS Secrets Manager", file=sys.stderr)
            print("Required secrets: dockerhub_username, dockerhub_password", file=sys.stderr)
            return None, None

        return username, password

    except Exception as e:
        print(f"Error retrieving Docker Hub credentials: {e}", file=sys.stderr)
        print("Make sure AWS credentials are configured and the secret exists", file=sys.stderr)
        return None, None


def main():
    username, password = get_dockerhub_credentials()

    if username and password:
        print(f"DOCKER_HUB_USERNAME={username}")
        print(f"DOCKER_HUB_PASSWORD={password}")
        return 0

    print("Error: Could not retrieve Docker Hub credentials", file=sys.stderr)
    print("Please ensure:", file=sys.stderr)
    print("1. AWS credentials are configured", file=sys.stderr)
    print("2. The secret 'prod/refPortalSecret' exists in AWS Secrets Manager", file=sys.stderr)
    print("3. The secret contains 'dockerhub_username' and 'dockerhub_password'", file=sys.stderr)
    print("4. boto3 is installed: pip install -r requirements-push2dockerhub.txt", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
