import boto3
import json
import time
import logging
from datetime import datetime
from pymemcache.client import base

def lambda_handler(event, context):
    # TODO implement
    mcClient = initializeMemCacheConnection()

    key = f"foo{datetime.now().second}"
    mcClient.set(key, "bar")
    val = mcClient.get(key)
    print(f'{key}={val}')

    importToKeyval(mcClient)

    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }

def initializeMemCacheConnection():
    # Replace with your Memcached endpoint
    MEMCACHED_ENDPOINT = "refportal-memcache-test-rqgspm.serverless.ilc1.cache.amazonaws.com"
    MEMCACHED_PORT = 6379

    # Connect to Memcached
    return base.Client((MEMCACHED_ENDPOINT, MEMCACHED_PORT), connect_timeout=60)

def importToKeyval(mcClient):
    # AWS S3 Configuration
    S3_BUCKET = "refereex-refportal-bucket"
    S3_KEY = "imports/redis_export.json"  # Example: JSON file

    # Initialize clients
    s3_client = boto3.client("s3")

    logging.info("Fetching file from S3...")
    response = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    data = response["Body"].read().decode("utf-8")
    dataJson = json.loads(data)

    """Store key-value pairs in Memcached."""
    for key, value in dataJson.items():
        mcClient.set(key, value)
        logging.info(f"Stored {key} -> {value}")

    logging.info("Import completed.")

def lambda_handler2(event, context):

    # Get query string parameter "param1"
    query_params = event.get("queryStringParameters", {})
    param1 = query_params.get("param1", "default_value")  # Default if not found

    # Get JSON body and extract "param2"
    try:
        body = event.get("body", "{}")  # Handle empty body gracefully
        bodyJson = json.loads(body)
        param2 = bodyJson.get("param2", "default_value")
    except json.JSONDecodeError:
        return {
            "statusCode": 401,
            "body": json.dumps({'error': "Invalid JSON body"})
        }
    except Exception as e:
        return {
            "statusCode": 402,
            "body": f"={body}={json.dumps({'error': str(e)})}"
        }

    # Return extracted values
    return {
        "statusCode": 200,
        "body": json.dumps({
            "query_param1": param1,
            "body": body,
            "json_param2": param2
        })
    }

    # Return extracted values
    return {
        "statusCode": 200,
        "body": json.dumps({
            "query_param1": param1,
            "json_param2": param2
        })
    }

#lambda_client = boto3.client("lambda")

def lambda_handler1(event, context):
    print("Received event:", event)

    # Simulate async response
    response = {
        "statusCode": 202,  # 202 Accepted
        "body": json.dumps({"message": "Processing started"})
    }
    
    # Run process in the background (synchronously inside Lambda)
    process_long_task()

    return response

async def process_long_task():
    print("Starting long task...")
    time.sleep(100)  # Simulating 10 min task
    print("Task completed")

#importToKeyval(None)