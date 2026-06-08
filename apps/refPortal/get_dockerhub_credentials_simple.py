#!/usr/bin/env python3
"""
Docker Hub credentials via AWS Secrets Manager (or MY_SECRET_FILE), using only boto3.
Does not import shared.helpers (avoids ics, PIL, thefuzz, …).
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
            print("Please add these to your AWS Secrets Manager secret: prod/refPortalSecret", file=sys.stderr)
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
