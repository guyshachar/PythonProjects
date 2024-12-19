import os
import boto3
from botocore.exceptions import ClientError
import json
import time

def split_text(text, size_limit):
    """
    Splits text into chunks by words while retaining newlines.

    :param text: The original text.
    :param size_limit: Maximum size of each chunk.
    :return: A list of text chunks.
    """
    chunks = []
    current_chunk = ""

    for line in text.splitlines(keepends=True):  # Retain newlines in the split
        for word in line.split():
            # Check if adding this word exceeds the size limit
            if len(current_chunk) + len(word) + 1 > size_limit:  # +1 for space/newline
                chunks.append(current_chunk.strip())
                current_chunk = ""
            current_chunk += word + " "
        current_chunk += "\n"
        if False and current_chunk.endswith("\n"):  # Ensure newlines are respected
            chunks.append(current_chunk.strip())
            current_chunk = ""

    if current_chunk:  # Add any remaining text
        chunks.append(current_chunk.strip())

    return chunks

def get_secret(self, secretName):
    secret_file_path = os.getenv("MY_SECRET_FILE", f"/run/secrets/")
    secret_file_path = secret_file_path + secretName

    try:
        with open(secret_file_path, 'r') as secret_file:
            secret = secret_file.read().strip()
        return secret
    except FileNotFoundError:
        self.logger.error(f"Secret: file not found: {secret_file_path}")
        return None
    except Exception as e:
        self.logger.error(f'secret: {e}')

def get_secret1(self, secretName):
    self.logger.debug(f'secret: {secretName}')
    region_name = "il-central-1"
    secret = None

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        self.logger.debug(f'secret: Get Value')
        get_secret_value_response = client.get_secret_value(
            SecretId=secretName
        )
        self.logger.debug(f'secret: Get Value String')
        secretStr = get_secret_value_response['SecretString']
        #self.logger.info(f'secretStr: {secretStr}')
        secret = json.loads(secretStr)
        #self.logger.info(f'secretStr: {secret}')
        return secret

    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        #raise e
        self.logger.error(f'secret clientError: {e}')
        pass
    except Exception as e:
        self.logger.error(f'secret: {e}')
        pass

    return None

def stopwatch_start(self, name):
    self.swDic[name] = time.perf_counter()

def stopwatch_stop(self, name, level=None):
    elapsedTime = int((time.perf_counter() - self.swDic[name])*1000)
    if level:
        eval(f'self.logger.{level}')(f'sw {name}={elapsedTime}')
    else:
        self.logger.debug(f'sw {name}={elapsedTime}')
    return elapsedTime