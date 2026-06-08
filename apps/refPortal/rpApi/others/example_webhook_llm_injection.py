#!/usr/bin/env python3.12
"""
Example of using WebhookLLMEnhancer with dependency injection
"""

import os
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.appContainer import AppContainer
from shared.configurationDI import configDI
from rpApi.webhook_llm_integration import create_webhook_llm_enhancer, create_llm_webhook_integration, create_llm_webhook_handler, WebhookLLMEnhancer

def example_direct_injection():
    """Example of directly creating and injecting WebhookLLMEnhancer"""
    
    # Create container and get dependencies
    container = AppContainer()
    container.config.from_dict(configDI)
    container.init_resources()
    
    try:
        # Get dependencies from container
        logger = container.logger()
        db_client = container.db_client()
        bedrock_client = container.bedrock_client()
        config = container.config()
        
        # Create LLMWebhookIntegration first
        llm_integration = create_llm_webhook_integration(
            logger=logger,
            bedrock_client=bedrock_client,
            db_client=db_client,
            config=config
        )
        
        if llm_integration:
            # Create LLMWebhookHandler
            webhook_handler = create_llm_webhook_handler(llm_integration)
            
            if webhook_handler:
                # Create LLM enhancer using factory function
                llm_enhancer = create_webhook_llm_enhancer(
                    logger=logger,
                    cacheService=db_client,
                    llm_integration=llm_integration,  # Required parameter
                    webhook_handler=webhook_handler,  # Required parameter
                    config=config
                )
            else:
                print("⚠️  LLMWebhookHandler creation failed - cannot create WebhookLLMEnhancer")
                return
            
            if llm_enhancer:
                print("✅ WebhookLLMEnhancer created successfully")
                print(f"   Type: {type(llm_enhancer)}")
                print(f"   Has enhance_incoming_webhook: {hasattr(llm_enhancer, 'enhance_incoming_webhook')}")
                print(f"   Has process_complex_query: {hasattr(llm_enhancer, 'process_complex_query')}")
            else:
                print("⚠️  WebhookLLMEnhancer creation failed")
        else:
            print("⚠️  LLMWebhookIntegration creation failed - cannot create WebhookLLMEnhancer")
            
    except Exception as e:
        print(f"❌ Error:", e)
    finally:
        container.shutdown_resources()

def example_container_injection():
    """Example of using WebhookLLMEnhancer from the container"""
    
    # Create container and get dependencies
    container = AppContainer()
    container.config.from_dict(configDI)
    container.init_resources()
    
    try:
        # Get LLM enhancer directly from container
        llm_enhancer = container.llm_enhancer()
        
        if llm_enhancer:
            print("✅ WebhookLLMEnhancer retrieved from container")
            print(f"   Type: {type(llm_enhancer)}")
            
            # Example usage
            if isinstance(llm_enhancer, WebhookLLMEnhancer):
                print("   ✅ Valid WebhookLLMEnhancer instance")
            else:
                print("   ⚠️  Unexpected type")
        else:
            print("⚠️  No LLM enhancer available from container")
            
    except Exception as e:
        print(f"❌ Error:", e)
    finally:
        container.shutdown_resources()

def example_manual_creation():
    """Example of manually creating WebhookLLMEnhancer without container"""
    
    try:
        from shared.logger import Logger
        from shared.db import DynamodbClient
        from shared.bedrockClient import BedrockClient
        
        # Create dependencies manually
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
        
        # Create LLMWebhookIntegration first
        llm_integration = create_llm_webhook_integration(
            logger=logger,
            bedrock_client=bedrock_client,
            db_client=db_client,
            config=config
        )
        
        if llm_integration:
            # Create LLMWebhookHandler
            webhook_handler = create_llm_webhook_handler(llm_integration)
            
            if webhook_handler:
                # Create LLM enhancer
                llm_enhancer = create_webhook_llm_enhancer(
                    logger=logger,
                    cacheService=db_client,
                    llm_integration=llm_integration,  # Required parameter
                    webhook_handler=webhook_handler,  # Required parameter
                    config=config
                )
            else:
                print("⚠️  LLMWebhookHandler creation failed - cannot create WebhookLLMEnhancer")
                return
            
            if llm_enhancer:
                print("✅ WebhookLLMEnhancer created manually")
                print(f"   Type: {type(llm_enhancer)}")
            else:
                print("⚠️  WebhookLLMEnhancer creation failed")
        else:
            print("⚠️  LLMWebhookIntegration creation failed - cannot create WebhookLLMEnhancer")
            
    except Exception as e:
        print(f"❌ Error:", e)

def example_llm_integration_injection():
    """Example of injecting LLMWebhookIntegration into WebhookLLMEnhancer"""
    
    # Create container and get dependencies
    container = AppContainer()
    container.config.from_dict(configDI)
    container.init_resources()
    
    try:
        # Get dependencies from container
        logger = container.logger()
        db_client = container.db_client()
        bedrock_client = container.bedrock_client()
        config = container.config()
        
        # Create LLMWebhookIntegration first
        llm_integration = create_llm_webhook_integration(
            logger=logger,
            bedrock_client=bedrock_client,
            db_client=db_client,
            config=config
        )
        
        if llm_integration:
            print("✅ LLMWebhookIntegration created successfully")
            print(f"   Type: {type(llm_integration)}")
            
            # Create LLMWebhookHandler
            webhook_handler = create_llm_webhook_handler(llm_integration)
            
            if webhook_handler:
                # Inject LLMWebhookIntegration and LLMWebhookHandler into WebhookLLMEnhancer
                llm_enhancer = create_webhook_llm_enhancer(
                    logger=logger,
                    cacheService=db_client,
                    llm_integration=llm_integration,  # Inject the created integration
                    webhook_handler=webhook_handler,  # Inject the created handler
                    config=config
                )
            else:
                print("⚠️  LLMWebhookHandler creation failed - cannot create WebhookLLMEnhancer")
                return
            
            if llm_enhancer:
                print("✅ WebhookLLMEnhancer created with injected LLMWebhookIntegration")
                print(f"   Type: {type(llm_enhancer)}")
                print(f"   Using injected integration: {llm_enhancer.llm_integration is llm_integration}")
            else:
                print("⚠️  WebhookLLMEnhancer creation failed")
        else:
            print("⚠️  LLMWebhookIntegration creation failed")
            
    except Exception as e:
        print(f"❌ Error:", e)
    finally:
        container.shutdown_resources()

def example_container_llm_integration_injection():
    """Example of using LLMWebhookIntegration from container and injecting it"""
    
    # Create container and get dependencies
    container = AppContainer()
    container.config.from_dict(configDI)
    container.init_resources()
    
    try:
        # Get LLMWebhookIntegration from container
        llm_integration = container.llm_webhook_integration()
        
        if llm_integration:
            print("✅ LLMWebhookIntegration retrieved from container")
            print(f"   Type: {type(llm_integration)}")
            
            # Get other dependencies
            logger = container.logger()
            db_client = container.db_client()
            config = container.config()
            
            # Get LLMWebhookHandler from container
            webhook_handler = container.llm_webhook_handler()
            
            if webhook_handler:
                # Inject the container's components into a new WebhookLLMEnhancer
                llm_enhancer = create_webhook_llm_enhancer(
                    logger=logger,
                    cacheService=db_client,
                    llm_integration=llm_integration,  # Inject from container
                    webhook_handler=webhook_handler,  # Inject from container
                    config=config
                )
            else:
                print("⚠️  No LLMWebhookHandler available from container")
                return
            
            if llm_enhancer:
                print("✅ WebhookLLMEnhancer created with container's LLMWebhookIntegration")
                print(f"   Type: {type(llm_enhancer)}")
                print(f"   Using container integration: {llm_enhancer.llm_integration is llm_integration}")
            else:
                print("⚠️  WebhookLLMEnhancer creation failed")
        else:
            print("⚠️  No LLMWebhookIntegration available from container")
            
    except Exception as e:
        print(f"❌ Error:", e)
    finally:
        container.shutdown_resources()

if __name__ == "__main__":
    print("=== WebhookLLMEnhancer Injection Examples ===\n")
    
    print("1. Direct Injection Example:")
    example_direct_injection()
    print()
    
    print("2. Container Injection Example:")
    example_container_injection()
    print()
    
    print("3. Manual Creation Example:")
    example_manual_creation()
    print()
    
    print("4. LLMWebhookIntegration Injection Example:")
    example_llm_integration_injection()
    print()
    
    print("5. Container LLMWebhookIntegration Injection Example:")
    example_container_llm_integration_injection()
    print()
    
    print("=== Examples Complete ===")
