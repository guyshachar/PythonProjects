#!/usr/bin/env python3.12
"""
LLM Cache Configuration Example
Shows how to configure LLM response caching in your application.
"""

# Example configuration for LLM caching
LLM_CACHE_CONFIG = {
    'LLM': {
        'enabled': True,
        'use_cache': True,  # Enable/disable caching
        'use_redis_cache': True,  # Use Redis (True) or in-memory (False)
        'cache_ttl_seconds': 3600,  # 1 hour cache TTL
        'cache_max_size': 10000,  # Maximum cache entries
        'confidence_threshold': 0.7,  # Minimum confidence to cache
        'log_interactions': True,  # Log LLM interactions
        'cache_high_confidence_only': True,  # Only cache high confidence responses
    }
}

# Environment variables for configuration
ENV_VARS = {
    'LLM_ENABLED': 'True',
    'LLM_USE_CACHE': 'True',
    'LLM_USE_REDIS_CACHE': 'True',
    'LLM_CACHE_TTL_SECONDS': '3600',
    'LLM_CACHE_MAX_SIZE': '10000',
    'LLM_CONFIDENCE_THRESHOLD': '0.7',
    'LLM_LOG_INTERACTIONS': 'True',
    'LLM_CACHE_HIGH_CONFIDENCE_ONLY': 'True',
}

# Example usage in your application
def example_cache_configuration():
    """Example of how to configure LLM caching"""
    
    import os
    
    # Load configuration from environment variables
    config = {
        'LLM': {
            'enabled': os.getenv('LLM_ENABLED', 'False') == 'True',
            'use_cache': os.getenv('LLM_USE_CACHE', 'True') == 'True',
            'use_redis_cache': os.getenv('LLM_USE_REDIS_CACHE', 'True') == 'True',
            'cache_ttl_seconds': int(os.getenv('LLM_CACHE_TTL_SECONDS', '3600')),
            'cache_max_size': int(os.getenv('LLM_CACHE_MAX_SIZE', '10000')),
            'confidence_threshold': float(os.getenv('LLM_CONFIDENCE_THRESHOLD', '0.7')),
            'log_interactions': os.getenv('LLM_LOG_INTERACTIONS', 'True') == 'True',
            'cache_high_confidence_only': os.getenv('LLM_CACHE_HIGH_CONFIDENCE_ONLY', 'True') == 'True',
        }
    }
    
    return config

# Cache performance monitoring
def monitor_cache_performance(cache_instance):
    """Monitor cache performance and statistics"""
    
    stats = cache_instance.get_cache_stats()
    
    print("=== LLM Cache Performance Stats ===")
    print(f"Total cached entries: {stats.get('total_entries', 0)}")
    print(f"Average confidence: {stats.get('average_confidence', 0):.2f}")
    print(f"Cache TTL: {stats.get('ttl_seconds', 0)} seconds")
    print(f"Max cache size: {stats.get('max_cache_size', 0)}")
    
    if stats.get('sampled_entries', 0) > 0:
        print(f"Average response length: {stats.get('average_response_length', 0):.0f} characters")
    
    # Calculate cache hit rate (if you have access to hit/miss counters)
    # This would require additional implementation in the cache class
    
    return stats

# Cache management utilities
def manage_cache(cache_instance, action='stats'):
    """Manage cache operations"""
    
    if action == 'stats':
        return monitor_cache_performance(cache_instance)
    
    elif action == 'clear':
        success = cache_instance.clear_all_cache()
        if success:
            print("✅ Cache cleared successfully")
        else:
            print("❌ Failed to clear cache")
        return success
    
    elif action == 'invalidate':
        # Example: invalidate specific message
        message = "מה השעה?"
        success = cache_instance.invalidate_cache(message)
        if success:
            print(f"✅ Invalidated cache for: {message}")
        else:
            print(f"❌ Failed to invalidate cache for: {message}")
        return success
    
    else:
        print(f"Unknown action: {action}")
        return False

# Example cache key generation
def example_cache_keys():
    """Show examples of how cache keys are generated"""
    
    from rpApi.llm_response_cache import LLMResponseCache
    from shared.logger import Logger
    
    # Create a dummy cache instance for key generation
    logger = Logger()
    cache = LLMResponseCache(logger, None)  # No Redis client needed for key generation
    
    # Example messages and referee details
    examples = [
        {
            'message': 'מה השעה?',
            'referee_detail': {'refId': '12345', 'level': 'senior'}
        },
        {
            'message': 'מה השעה?',
            'referee_detail': {'refId': '67890', 'level': 'junior'}
        },
        {
            'message': 'איפה המגרש?',
            'referee_detail': None
        }
    ]
    
    print("=== Cache Key Examples ===")
    for example in examples:
        key = cache._generate_cache_key(
            example['message'], 
            example['referee_detail']
        )
        print(f"Message: {example['message']}")
        print(f"Referee: {example['referee_detail']}")
        print(f"Cache Key: {key}")
        print("-" * 50)

if __name__ == "__main__":
    # Run examples
    print("LLM Cache Configuration Examples")
    print("=" * 40)
    
    # Show configuration
    config = example_cache_configuration()
    print("Configuration:", config)
    print()
    
    # Show cache key examples
    example_cache_keys()
