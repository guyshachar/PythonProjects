#!/usr/bin/env python3.12
"""
Simple example showing required injection pattern for WebhookLLMEnhancer
"""

import os
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.logger import Logger
from shared.db import DynamodbClient
from shared.bedrockClient import BedrockClient
from rpApi.webhook_llm_integration import create_llm_webhook_integration, create_webhook_llm_enhancer, create_llm_webhook_handler, WebhookLLMEnhancer

def main():
    """Simple example of required injection pattern"""
    
    # Create basic dependencies
    logger = Logger()
    db_client = DynamodbClient(
        env=os.getenv('app_env', 'development'),
        logger=logger,
        awsRegion=os.getenv('awsRegion', 'il-central-1')
    )
    bedrock_client = BedrockClient(
        logger=logger,
        awsRegion=os.getenv('awsRegion', 'il-central-1')
    )
    
    config = {
        'LLM': {
            'enabled': os.getenv('LLM_ENABLED', 'False') == 'True',
            'bedrockModelId': os.getenv('BEDROCK_MODEL_ID'),
        },
        'docsServiceUrlBase': os.getenv('docsServiceUrlBase', '')
    }
    
    print("=== Required Injection Pattern Example ===\n")
    
    # Step 1: Create LLMWebhookIntegration (required)
    print("1. Creating LLMWebhookIntegration...")
    llm_integration = create_llm_webhook_integration(
        logger=logger,
        bedrock_client=bedrock_client,
        db_client=db_client,
        config=config
    )
    
    if llm_integration:
        print("   ✅ LLMWebhookIntegration created successfully")
        print(f"   Type: {type(llm_integration)}")
    else:
        print("   ❌ LLMWebhookIntegration creation failed")
        return
    
    # Step 2: Create LLMWebhookHandler (required)
    print("\n2. Creating LLMWebhookHandler...")
    webhook_handler = create_llm_webhook_handler(llm_integration)
    
    if webhook_handler:
        print("   ✅ LLMWebhookHandler created successfully")
        print(f"   Type: {type(webhook_handler)}")
    else:
        print("   ❌ LLMWebhookHandler creation failed")
        return
    
    # Step 3: Create WebhookLLMEnhancer with injected components (required)
    print("\n3. Creating WebhookLLMEnhancer with injected LLMWebhookIntegration and LLMWebhookHandler...")
    llm_enhancer = create_webhook_llm_enhancer(
        logger=logger,
        cacheService=db_client,
        llm_integration=llm_integration,  # Required parameter
        webhook_handler=webhook_handler,  # Required parameter
        config=config
    )
    
    if llm_enhancer:
        print("   ✅ WebhookLLMEnhancer created successfully")
        print(f"   Type: {type(llm_enhancer)}")
        print(f"   Using injected integration: {llm_enhancer.llm_integration is llm_integration}")
        
        # Step 4: Use the enhancer
        print("\n4. WebhookLLMEnhancer is ready to use!")
        print("   Available methods:")
        print("   - enhance_incoming_webhook()")
        print("   - process_complex_query()")
    else:
        print("   ❌ WebhookLLMEnhancer creation failed")

if __name__ == "__main__":
    main()
