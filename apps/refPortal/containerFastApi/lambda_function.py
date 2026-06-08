from mangum import Mangum
import sys
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Import the FastAPI application factory
from rpApi.refPortalFastApiDI import RefPortalFastApi

# Create the FastAPI application without lifespan protocol
ref_portal_fast_api = RefPortalFastApi()
app = ref_portal_fast_api.create_app_without_lifespan()

# Create Mangum handler for AWS Lambda
handler = Mangum(app, lifespan="off")

def lambda_handler(event, context):
    return handler(event, context)
