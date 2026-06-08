import json

def lambda_handler(event, context):
    # Parse incoming request
    if event.get("httpMethod") == "POST":
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Hello from Lambda!"}),
            "headers": {"Content-Type": "application/json"}
        }
    
    return {
        "statusCode": 400,
        "body": json.dumps({"error": "Unsupported method"}),
        "headers": {"Content-Type": "application/json"}
    }
