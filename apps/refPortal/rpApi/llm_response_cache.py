#!/usr/bin/env python3.12
"""
LLM Response Caching Module
Provides robust caching for LLM responses using Redis with TTL and proper key management.
"""

import hashlib
import json
import time
from typing import Optional, Dict, Any
from shared.logger import Logger
from shared.db import RedisClient


class LLMResponseCache:
    """Caches LLM responses with TTL and proper key management"""
    
    def __init__(self, 
                 logger: Logger,
                 redis_client: RedisClient,
                 ttl_seconds: int = 3600,  # 1 hour default
                 max_cache_size: int = 10000):
        """
        Initialize LLM response cache
        
        Args:
            logger: Logger instance
            redis_client: Redis client instance
            ttl_seconds: Time to live for cached responses in seconds
            max_cache_size: Maximum number of cached responses
        """
        self.logger = logger
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds
        self.max_cache_size = max_cache_size
        self.cache_prefix = "llm_response:"
        
        self.logger.info(f"LLM Response Cache initialized with TTL: {ttl_seconds}s, Max size: {max_cache_size}")
    
    def _generate_cache_key(self, message: str, referee_detail: Optional[Dict] = None) -> str:
        """
        Generate a unique cache key for the message and referee context
        
        Args:
            message: The input message
            referee_detail: Optional referee details for context
            
        Returns:
            Unique cache key
        """
        # Create a hash of the message and referee context
        cache_data = {
            'message': message.strip().lower(),
            'referee_id': referee_detail.get('refId') if referee_detail else None,
            'referee_level': referee_detail.get('level') if referee_detail else None
        }
        
        cache_string = json.dumps(cache_data, sort_keys=True)
        message_hash = hashlib.sha256(cache_string.encode()).hexdigest()
        
        return f"{self.cache_prefix}{message_hash}"
    
    def get_cached_response(self, message: str, referee_detail: Optional[Dict] = None) -> Optional[str]:
        """
        Get cached response for a message
        
        Args:
            message: The input message
            referee_detail: Optional referee details for context
            
        Returns:
            Cached response or None if not found
        """
        try:
            cache_key = self._generate_cache_key(message, referee_detail)
            cached_data = self.redis_client.get(cache_key)
            
            if cached_data:
                # Parse the cached data
                response_data = json.loads(cached_data)
                self.logger.debug(f"Cache hit for message: {message[:50]}...")
                return response_data.get('response')
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error retrieving cached response:", e)
            return None
    
    def cache_response(self, 
                      message: str, 
                      response: str, 
                      confidence: float,
                      referee_detail: Optional[Dict] = None,
                      metadata: Optional[Dict] = None) -> bool:
        """
        Cache a response with metadata
        
        Args:
            message: The input message
            response: The LLM response
            confidence: Confidence score of the response
            referee_detail: Optional referee details for context
            metadata: Optional additional metadata
            
        Returns:
            True if successfully cached, False otherwise
        """
        try:
            cache_key = self._generate_cache_key(message, referee_detail)
            
            # Prepare cache data
            cache_data = {
                'response': response,
                'confidence': confidence,
                'timestamp': time.time(),
                'message_length': len(message),
                'response_length': len(response),
                'metadata': metadata or {}
            }
            
            # Cache the response with TTL
            success = self.redis_client.setex(
                cache_key, 
                self.ttl_seconds, 
                json.dumps(cache_data)
            )
            
            if success:
                self.logger.debug(f"Cached response for message: {message[:50]}... (confidence: {confidence})")
                
                # Check cache size and clean if needed
                self._cleanup_cache_if_needed()
                
                return True
            else:
                self.logger.warning(f"Failed to cache response for message: {message[:50]}...")
                return False
                
        except Exception as e:
            self.logger.error(f"Error caching response:", e)
            return False
    
    def _cleanup_cache_if_needed(self):
        """Clean up old cache entries if cache size exceeds limit"""
        try:
            # Get all cache keys
            pattern = f"{self.cache_prefix}*"
            cache_keys = self.redis_client.keys(pattern)
            
            if len(cache_keys) > self.max_cache_size:
                # Sort by creation time (oldest first) and remove excess
                keys_to_remove = cache_keys[:len(cache_keys) - self.max_cache_size]
                
                for key in keys_to_remove:
                    self.redis_client.delete(key)
                
                self.logger.info(f"Cleaned up {len(keys_to_remove)} old cache entries")
                
        except Exception as e:
            self.logger.error(f"Error during cache cleanup:", e)
    
    def invalidate_cache(self, message: str, referee_detail: Optional[Dict] = None) -> bool:
        """
        Invalidate a specific cached response
        
        Args:
            message: The message to invalidate
            referee_detail: Optional referee details for context
            
        Returns:
            True if successfully invalidated, False otherwise
        """
        try:
            cache_key = self._generate_cache_key(message, referee_detail)
            result = self.redis_client.delete(cache_key)
            
            if result:
                self.logger.debug(f"Invalidated cache for message: {message[:50]}...")
            
            return bool(result)
            
        except Exception as e:
            self.logger.error(f"Error invalidating cache:", e)
            return False
    
    def clear_all_cache(self) -> bool:
        """
        Clear all LLM response cache entries
        
        Returns:
            True if successfully cleared, False otherwise
        """
        try:
            pattern = f"{self.cache_prefix}*"
            cache_keys = self.redis_client.keys(pattern)
            
            if cache_keys:
                for key in cache_keys:
                    self.redis_client.delete(key)
                
                self.logger.info(f"Cleared {len(cache_keys)} cache entries")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error clearing cache:", e)
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dictionary with cache statistics
        """
        try:
            pattern = f"{self.cache_prefix}*"
            cache_keys = self.redis_client.keys(pattern)
            
            total_size = 0
            total_confidence = 0
            response_count = 0
            
            for key in cache_keys[:100]:  # Sample first 100 for stats
                cached_data = self.redis_client.get(key)
                if cached_data:
                    try:
                        data = json.loads(cached_data)
                        total_size += data.get('response_length', 0)
                        total_confidence += data.get('confidence', 0)
                        response_count += 1
                    except:
                        pass
            
            avg_confidence = total_confidence / response_count if response_count > 0 else 0
            
            return {
                'total_entries': len(cache_keys),
                'sampled_entries': response_count,
                'average_response_length': total_size / response_count if response_count > 0 else 0,
                'average_confidence': avg_confidence,
                'ttl_seconds': self.ttl_seconds,
                'max_cache_size': self.max_cache_size
            }
            
        except Exception as e:
            self.logger.error(f"Error getting cache stats:", e)
            return {}

class InMemoryLLMResponseCache:
    """Simple in-memory cache for development/testing"""
    
    def __init__(self, 
                 logger: Logger,
                 ttl_seconds: int = 3600,
                 max_cache_size: int = 1000):
        """
        Initialize in-memory cache
        
        Args:
            logger: Logger instance
            ttl_seconds: Time to live for cached responses in seconds
            max_cache_size: Maximum number of cached responses
        """
        self.logger = logger
        self.ttl_seconds = ttl_seconds
        self.max_cache_size = max_cache_size
        self.cache = {}
        
        self.logger.info(f"In-Memory LLM Response Cache initialized with TTL: {ttl_seconds}s, Max size: {max_cache_size}")
    
    def _generate_cache_key(self, message: str, referee_detail: Optional[Dict] = None) -> str:
        """Generate cache key for in-memory cache"""
        cache_data = {
            'message': message.strip().lower(),
            'referee_id': referee_detail.get('refIdNIU') if referee_detail else None,
            'referee_level': referee_detail.get('level') if referee_detail else None
        }
        
        cache_string = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(cache_string.encode()).hexdigest()
    
    def get_cached_response(self, message: str, referee_detail: Optional[Dict] = None) -> Optional[str]:
        """Get cached response"""
        try:
            cache_key = self._generate_cache_key(message, referee_detail)
            cached_data = self.cache.get(cache_key)
            
            if cached_data and time.time() - cached_data['timestamp'] < self.ttl_seconds:
                self.logger.debug(f"Cache hit for message: {message[:50]}...")
                return cached_data['response']
            
            # Remove expired entry
            if cached_data:
                del self.cache[cache_key]
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error retrieving cached response:", e)
            return None
    
    def cache_response(self, 
                      message: str, 
                      response: str, 
                      confidence: float,
                      referee_detail: Optional[Dict] = None,
                      metadata: Optional[Dict] = None) -> bool:
        """Cache a response"""
        try:
            cache_key = self._generate_cache_key(message, referee_detail)
            
            # Clean up if cache is full
            if len(self.cache) >= self.max_cache_size:
                # Remove oldest entries
                sorted_items = sorted(self.cache.items(), key=lambda x: x[1]['timestamp'])
                items_to_remove = len(sorted_items) - self.max_cache_size + 1
                
                for i in range(items_to_remove):
                    del self.cache[sorted_items[i][0]]
            
            # Cache the response
            self.cache[cache_key] = {
                'response': response,
                'confidence': confidence,
                'timestamp': time.time(),
                'metadata': metadata or {}
            }
            
            self.logger.debug(f"Cached response for message: {message[:50]}... (confidence: {confidence})")
            return True
            
        except Exception as e:
            self.logger.error(f"Error caching response:", e)
            return False
    
    def clear_all_cache(self) -> bool:
        """Clear all cache entries"""
        try:
            self.cache.clear()
            self.logger.info("Cleared in-memory cache")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing cache:", e)
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            total_confidence = sum(item['confidence'] for item in self.cache.values())
            avg_confidence = total_confidence / len(self.cache) if self.cache else 0
            
            return {
                'total_entries': len(self.cache),
                'average_confidence': avg_confidence,
                'ttl_seconds': self.ttl_seconds,
                'max_cache_size': self.max_cache_size
            }
        except Exception as e:
            self.logger.error(f"Error getting cache stats:", e)
            return {}


# Factory functions for direct injection
def create_redis_llm_response_cache(logger: Logger, 
                                  redis_client: RedisClient,
                                  ttl_seconds: int = 3600,
                                  max_cache_size: int = 10000) -> LLMResponseCache:
    """
    Factory function to create Redis-based LLM response cache instances.
    
    Args:
        logger: Logger instance
        redis_client: Redis client instance (required)
        ttl_seconds: Time to live for cached responses
        max_cache_size: Maximum cache size
        
    Returns:
        LLMResponseCache instance
        
    Raises:
        ValueError: If redis_client is None
    """
    if not redis_client:
        raise ValueError("Redis client is required for Redis-based cache")
        
    return LLMResponseCache(
        logger=logger,
        redis_client=redis_client,
        ttl_seconds=ttl_seconds,
        max_cache_size=max_cache_size
    )


def create_in_memory_llm_response_cache(logger: Logger,
                                       ttl_seconds: int = 3600,
                                       max_cache_size: int = 1000) -> InMemoryLLMResponseCache:
    """
    Factory function to create in-memory LLM response cache instances.
    
    Args:
        logger: Logger instance
        ttl_seconds: Time to live for cached responses
        max_cache_size: Maximum cache size
        
    Returns:
        InMemoryLLMResponseCache instance
    """
    return InMemoryLLMResponseCache(
        logger=logger,
        ttl_seconds=ttl_seconds,
        max_cache_size=max_cache_size
    )


def create_llm_response_cache_from_config(logger: Logger,
                                         redis_client: Optional[RedisClient] = None,
                                         config: Optional[Dict[str, Any]] = None) -> Optional[LLMResponseCache]:
    """
    Factory function to create LLM response cache based on configuration.
    
    Args:
        logger: Logger instance
        redis_client: Redis client instance (optional)
        config: Configuration dictionary with LLM cache settings
        
    Returns:
        LLMResponseCache or InMemoryLLMResponseCache instance, or None if caching is disabled
    """
    if not config:
        config = {}
        
    llm_config = config.get('LLM', {})
    
    # Check if caching is enabled
    if not llm_config.get('use_cache', True):
        logger.info("LLM response caching disabled via configuration")
        return None
        
    use_redis = llm_config.get('use_redis_cache', True)
    ttl_seconds = llm_config.get('cache_ttl_seconds', 3600)
    max_cache_size = llm_config.get('cache_max_size', 10000 if use_redis else 1000)
    
    try:
        if use_redis:
            if not redis_client:
                logger.warning("Redis cache requested but no Redis client provided, falling back to in-memory cache")
                return create_in_memory_llm_response_cache(logger, ttl_seconds, max_cache_size)
            else:
                return create_redis_llm_response_cache(logger, redis_client, ttl_seconds, max_cache_size)
        else:
            return create_in_memory_llm_response_cache(logger, ttl_seconds, max_cache_size)
            
    except Exception as e:
        logger.error(f"Failed to create LLM response cache:", e)
        return None


# Legacy factory function (maintains backward compatibility)
def create_llm_response_cache(logger: Logger, 
                            redis_client: Optional[RedisClient] = None,
                            use_redis: bool = True,
                            ttl_seconds: int = 3600,
                            max_cache_size: int = 10000) -> LLMResponseCache:
    """
    Factory function to create LLM response cache instances (legacy version).
    
    Args:
        logger: Logger instance
        redis_client: Redis client instance (required if use_redis=True)
        use_redis: Whether to use Redis cache (True) or in-memory cache (False)
        ttl_seconds: Time to live for cached responses
        max_cache_size: Maximum cache size
        
    Returns:
        LLMResponseCache or InMemoryLLMResponseCache instance
        
    Raises:
        ValueError: If use_redis=True but redis_client is None
    """
    if use_redis:
        if not redis_client:
            raise ValueError("Redis client is required when use_redis=True")
        return create_redis_llm_response_cache(logger, redis_client, ttl_seconds, max_cache_size)
    else:
        return create_in_memory_llm_response_cache(logger, ttl_seconds, max_cache_size)
