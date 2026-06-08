#!/usr/bin/env python3.12
"""
Example: Direct Injection of LLMResponseCache and InMemoryLLMResponseCache
Shows how to inject cache instances directly into your components.
"""

import os
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.logger import Logger
from shared.db import DynamodbClient
from shared.bedrockClient import BedrockClient
from shared.db import RedisClient
from rpApi.webhook_llm_integration import create_llm_webhook_integration, create_webhook_llm_enhancer, create_llm_webhook_handler
from rpApi.llm_response_cache import (
    create_redis_llm_response_cache,
    create_in_memory_llm_response_cache,
    create_llm_response_cache_from_config,
    LLMResponseCache,
    InMemoryLLMResponseCache
)


def example_redis_cache_injection():
    """Example of injecting Redis-based cache"""
    print("=== Redis Cache Injection Example ===\n")
    
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
    
    # Create Redis client
    redis_client = RedisClient(
        logger=logger,
        redis_url=os.getenv('REDIS_URL', 'redis://localhost:6379')
    )
    
    config = {
        'LLM': {
            'enabled': True,
            'use_cache': True,
            'use_redis_cache': True,
            'cache_ttl_seconds': 3600,
            'cache_max_size': 10000
        }
    }
    
    # Step 1: Create Redis-based cache
    print("1. Creating Redis-based LLM response cache...")
    try:
        redis_cache = create_redis_llm_response_cache(
            logger=logger,
            redis_client=redis_client,
            ttl_seconds=3600,
            max_cache_size=10000
        )
        print("   ✅ Redis cache created successfully")
        print(f"   Type: {type(redis_cache)}")
    except Exception as e:
        print(f"   ❌ Redis cache creation failed:", e)
        return
    
    # Step 2: Create LLM components
    print("\n2. Creating LLM components...")
    llm_integration = create_llm_webhook_integration(
        logger=logger,
        bedrock_client=bedrock_client,
        db_client=db_client,
        config=config
    )
    
    if llm_integration:
        webhook_handler = create_llm_webhook_handler(llm_integration)
        
        if webhook_handler:
            # Step 3: Create WebhookLLMEnhancer with injected Redis cache
            print("\n3. Creating WebhookLLMEnhancer with injected Redis cache...")
            llm_enhancer = create_webhook_llm_enhancer(
                logger=logger,
                cacheService=db_client,
                llm_integration=llm_integration,
                webhook_handler=webhook_handler,
                config=config,
                response_cache=redis_cache  # Inject Redis cache
            )
            
            if llm_enhancer:
                print("   ✅ WebhookLLMEnhancer created with Redis cache")
                print(f"   Cache type: {type(llm_enhancer.response_cache)}")
                
                # Test cache functionality
                print("\n4. Testing cache functionality...")
                test_cache_functionality(redis_cache)
            else:
                print("   ❌ WebhookLLMEnhancer creation failed")
        else:
            print("   ❌ LLMWebhookHandler creation failed")
    else:
        print("   ❌ LLMWebhookIntegration creation failed")


def example_in_memory_cache_injection():
    """Example of injecting in-memory cache"""
    print("\n=== In-Memory Cache Injection Example ===\n")
    
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
            'enabled': True,
            'use_cache': True,
            'use_redis_cache': False,  # Use in-memory cache
            'cache_ttl_seconds': 1800,  # 30 minutes
            'cache_max_size': 1000
        }
    }
    
    # Step 1: Create in-memory cache
    print("1. Creating in-memory LLM response cache...")
    try:
        in_memory_cache = create_in_memory_llm_response_cache(
            logger=logger,
            ttl_seconds=1800,
            max_cache_size=1000
        )
        print("   ✅ In-memory cache created successfully")
        print(f"   Type: {type(in_memory_cache)}")
    except Exception as e:
        print(f"   ❌ In-memory cache creation failed:", e)
        return
    
    # Step 2: Create LLM components
    print("\n2. Creating LLM components...")
    llm_integration = create_llm_webhook_integration(
        logger=logger,
        bedrock_client=bedrock_client,
        db_client=db_client,
        config=config
    )
    
    if llm_integration:
        webhook_handler = create_llm_webhook_handler(llm_integration)
        
        if webhook_handler:
            # Step 3: Create WebhookLLMEnhancer with injected in-memory cache
            print("\n3. Creating WebhookLLMEnhancer with injected in-memory cache...")
            llm_enhancer = create_webhook_llm_enhancer(
                logger=logger,
                cacheService=db_client,
                llm_integration=llm_integration,
                webhook_handler=webhook_handler,
                config=config,
                response_cache=in_memory_cache  # Inject in-memory cache
            )
            
            if llm_enhancer:
                print("   ✅ WebhookLLMEnhancer created with in-memory cache")
                print(f"   Cache type: {type(llm_enhancer.response_cache)}")
                
                # Test cache functionality
                print("\n4. Testing cache functionality...")
                test_cache_functionality(in_memory_cache)
            else:
                print("   ❌ WebhookLLMEnhancer creation failed")
        else:
            print("   ❌ LLMWebhookHandler creation failed")
    else:
        print("   ❌ LLMWebhookIntegration creation failed")


def example_config_based_cache_injection():
    """Example of injecting cache based on configuration"""
    print("\n=== Config-Based Cache Injection Example ===\n")
    
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
    
    # Try to create Redis client (may fail in development)
    redis_client = None
    try:
        redis_client = RedisClient(
            logger=logger,
            redis_url=os.getenv('REDIS_URL', 'redis://localhost:6379')
        )
        print("   ✅ Redis client created")
    except Exception as e:
        print(f"   ⚠️  Redis client creation failed:", e)
        print("   Will fall back to in-memory cache")
    
    config = {
        'LLM': {
            'enabled': True,
            'use_cache': True,
            'use_redis_cache': True,  # Will fall back to in-memory if Redis unavailable
            'cache_ttl_seconds': 3600,
            'cache_max_size': 10000
        }
    }
    
    # Step 1: Create cache based on configuration
    print("1. Creating cache based on configuration...")
    cache = create_llm_response_cache_from_config(
        logger=logger,
        redis_client=redis_client,
        config=config
    )
    
    if cache:
        print("   ✅ Cache created successfully")
        print(f"   Type: {type(cache)}")
        
        # Step 2: Create LLM components
        print("\n2. Creating LLM components...")
        llm_integration = create_llm_webhook_integration(
            logger=logger,
            bedrock_client=bedrock_client,
            db_client=db_client,
            config=config
        )
        
        if llm_integration:
            webhook_handler = create_llm_webhook_handler(llm_integration)
            
            if webhook_handler:
                # Step 3: Create WebhookLLMEnhancer with injected cache
                print("\n3. Creating WebhookLLMEnhancer with injected cache...")
                llm_enhancer = create_webhook_llm_enhancer(
                    logger=logger,
                    cacheService=db_client,
                    llm_integration=llm_integration,
                    webhook_handler=webhook_handler,
                    config=config,
                    response_cache=cache  # Inject config-based cache
                )
                
                if llm_enhancer:
                    print("   ✅ WebhookLLMEnhancer created with config-based cache")
                    print(f"   Cache type: {type(llm_enhancer.response_cache)}")
                    
                    # Test cache functionality
                    print("\n4. Testing cache functionality...")
                    test_cache_functionality(cache)
                else:
                    print("   ❌ WebhookLLMEnhancer creation failed")
            else:
                print("   ❌ LLMWebhookHandler creation failed")
        else:
            print("   ❌ LLMWebhookIntegration creation failed")
    else:
        print("   ❌ Cache creation failed")


def test_cache_functionality(cache):
    """Test basic cache functionality"""
    print("   Testing cache operations...")
    
    # Test data
    test_message = "מה השעה?"
    test_response = "השעה היא 14:30"
    test_referee = {'refId': '12345', 'level': 'senior'}
    
    # Test caching
    success = cache.cache_response(
        message=test_message,
        response=test_response,
        confidence=0.9,
        referee_detail=test_referee
    )
    
    if success:
        print("   ✅ Response cached successfully")
        
        # Test retrieval
        cached_response = cache.get_cached_response(test_message, test_referee)
        if cached_response:
            print("   ✅ Cached response retrieved successfully")
            print(f"   Retrieved: {cached_response}")
        else:
            print("   ❌ Failed to retrieve cached response")
        
        # Test stats
        stats = cache.get_cache_stats()
        print(f"   Cache stats: {stats.get('total_entries', 0)} entries")
        
        # Test invalidation
        invalidated = cache.invalidate_cache(test_message, test_referee)
        if invalidated:
            print("   ✅ Cache invalidation successful")
        else:
            print("   ❌ Cache invalidation failed")
    else:
        print("   ❌ Failed to cache response")


def example_container_injection():
    """Example of using container-based injection"""
    print("\n=== Container-Based Cache Injection Example ===\n")
    
    try:
        from shared.appContainer import AppContainer
        
        # Create container
        container = AppContainer()
        
        # Get cache from container
        print("1. Getting cache from container...")
        cache = container.active_llm_response_cache()
        
        if cache:
            print("   ✅ Cache retrieved from container")
            print(f"   Type: {type(cache)}")
            
            # Get LLM enhancer from container (includes cache)
            print("\n2. Getting LLM enhancer from container...")
            llm_enhancer = container.llm_enhancer()
            
            if llm_enhancer:
                print("   ✅ LLM enhancer retrieved from container")
                print(f"   Cache type: {type(llm_enhancer.response_cache)}")
                
                # Test cache functionality
                print("\n3. Testing cache functionality...")
                test_cache_functionality(cache)
            else:
                print("   ❌ LLM enhancer retrieval failed")
        else:
            print("   ❌ Cache retrieval failed")
            
    except Exception as e:
        print(f"   ❌ Container-based injection failed:", e)


def main():
    """Run all cache injection examples"""
    print("LLM Cache Injection Examples")
    print("=" * 50)
    
    # Example 1: Redis cache injection
    example_redis_cache_injection()
    
    # Example 2: In-memory cache injection
    example_in_memory_cache_injection()
    
    # Example 3: Config-based cache injection
    example_config_based_cache_injection()
    
    # Example 4: Container-based injection
    example_container_injection()
    
    print("\n" + "=" * 50)
    print("Cache injection examples completed!")


if __name__ == "__main__":
    main()
