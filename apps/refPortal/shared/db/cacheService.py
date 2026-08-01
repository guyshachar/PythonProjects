from select import poll
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Callable, Tuple, TYPE_CHECKING
import logging
import asyncio
import sys
import json
import re
import redis
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from shared.logger import Logger
from shared.db.dbClientBase import DbClientBase
from shared.db.cacheDecorator import cacheDecorator, CacheDecorator
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db.enumTypes import EntityType, ActionType

if TYPE_CHECKING:
    # Only import for type hints, not at runtime to avoid circular import
    from shared.orgRelated import MultiTenantSupport

class CacheService:
    """
    A thread-safe singleton cache service that loads and manages static data from the database.
    Provides easy reload functionality and efficient data access.
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False
    
    def __new__(cls, logger: Logger, dbClient: DbClientBase, redisCacheClient:redis.Redis, multiTenantSupport:'MultiTenantSupport'):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CacheService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, logger: Logger, dbClient: DbClientBase, redisCacheClient:redis.Redis, multiTenantSupport:'MultiTenantSupport'):
        self.logger = Logger()
        self.dbClient = dbClient
        self.redisCacheClient = redisCacheClient
        self.multiTenantSupport = multiTenantSupport

        self._internal_lock = threading.RLock()

        # Redis cache keys
        self._cache_prefix = "cache:"
        self._cache_ttl_prefix = "cache_ttl:"

        # appName:env as the true leading segment of every Redis key this service touches -
        # appName namespaces this app's keys in case Redis is ever shared with another
        # service; env sits right after it, both ahead of tenantKey since _get_cache_key's output
        # is tenantKey:cache:entityType:... and env/appName need to come before tenantKey,
        # not before "cache:".
        appName = os.getenv('appName', 'refPortal')
        self._env = f"{appName}:{getattr(self.dbClient, 'env', None) or 'unknown'}"

        self.pk_separator = 'AAAA'

        self.cacheLogger = Logger(log2Console=False)
        cacheDecorator.initialize(logger=logger, cacheLogger=self.cacheLogger, cacheService=self)
        
        # Mark as initialized (data will be loaded lazily)
        CacheService._initialized = True
        self.logger.info(f"CacheService initialized...")

    def _tournament_games_partition_complete_identifier(self, tournament_name: str) -> str:
        """Identifier suffix for Redis sentinel: full tournament game list was loaded (path 3), not partial (path 1)."""
        return f'{tournament_name}:{self.pk_separator}:__partition_complete__'

    def tournament_games_partition_cache_is_complete(self, tenantKey: str, tournament_name: str) -> bool:
        if not tournament_name:
            return False
        rid = self._tournament_games_partition_complete_identifier(tournament_name)
        cache_key = self._get_cache_key(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=rid)
        return self._redis_exists(cache_key)

    def mark_tournament_games_partition_complete(self, tenantKey: str, tournament_name: str, ttl_seconds: Optional[int] = None) -> bool:
        if not tournament_name:
            return False
        ttl = ttl_seconds if ttl_seconds is not None else DbClientBase.CacheTypes.get(EntityType.TOURNAMENTSGAMES, {}).get('ttl', 3600)
        rid = self._tournament_games_partition_complete_identifier(tournament_name)
        cache_key = self._get_cache_key(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=rid)
        return self._redis_set(key=cache_key, data={'v': 1}, ttl_seconds=ttl)

    def clear_tournament_games_partition_complete(self, tenantKey: str, tournament_name: str) -> bool:
        if not tournament_name:
            return False
        rid = self._tournament_games_partition_complete_identifier(tournament_name)
        cache_key = self._get_cache_key(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=rid)
        return self._redis_delete(cache_key)
    
    @classmethod
    def get_instance(cls):
        """Get the singleton instance. Must be initialized first."""
        if cls._instance is None:
            raise RuntimeError("CacheService not initialized. Call CacheService(logger, dbClient) first.")
        return cls._instance
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the singleton is initialized."""
        return cls._initialized
    
    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None
            cls._initialized = False
    
    def _get_keyidentifiers(self, identifier: str = None, keys:list[str] = None) -> dict[str, str]:
        keyIdentifiers:list[str] = {}
        if keys == None:
            keyIdentifiers[identifier.split(':')[1] if ':' in identifier else None] = {'identifier': identifier, 'single': True}
        elif isinstance(keys, str):
            _identifier = f'{identifier}:{keys}'
            keyIdentifiers[_identifier] = {'identifier': _identifier, 'single': True}
        else:
            for key in keys:
                _identifier = f'{identifier}:{key}'
                keyIdentifiers[_identifier] = {'identifier': _identifier, 'single': False}
        return keyIdentifiers
        
    def _is_cache_valid(self, tenantKey: str, entityType: str, identifier: str = None, keys = None) -> bool:
        """Check if cache entry is still valid - Redis TTL handles expiration automatically"""
        # Simply check if the cache key exists - Redis TTL will have expired it if needed
        keyIdentifiers = self._get_keyidentifiers(identifier=identifier, keys=keys)
        for key, value in keyIdentifiers.items():
            cacheKey = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=value.get('identifier'))
            if cacheKey.endswith(f':{self.pk_separator}'):
                return self._redis_exists(key=cacheKey) or self._redis_exists(key=f'{cacheKey}:*')
            if not self._redis_exists(key=cacheKey):
                return False
        return True
        
    def _should_include_game(self, game: Dict[str, Any], includeArchived: bool, includeRemoved: bool, includeCanceled: bool, from_date: Optional[datetime], to_date: Optional[datetime]) -> bool:
        """Check if a game should be included based on filtering criteria"""
        if not game:
            return False
        
        state = game.get('state', 'active')
        # Check archived status
        if not includeArchived and state == 'archived':
            return False
        
        # Check removed status
        if not includeRemoved and state == 'removed':
            return False

        # Check canceled status
        if not includeCanceled and state == 'canceled':
            return False

        # Check date range
        game_date = game.get('date') or game.get('gameDate')
        if game_date:
            try:
                from datetime import datetime
                game_date_obj = datetime.strptime(str(game_date), '%Y-%m-%d') if isinstance(game_date, str) else game_date
                
                if from_date:
                    from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                    if game_date_obj < from_date_obj:
                        return False
                
                if to_date:
                    to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                    if game_date_obj > to_date_obj:
                        return False
            except (ValueError, TypeError):
                # If date parsing fails, include the game (let DB handle it)
                pass
        
        return True
    
    def _redis_get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis cache"""
        try:
            if key.endswith(f':{self.pk_separator}'):
                keys:list[str] = self.redis_get_keys(pattern=f'{key}:*')
                data = self._redis_get_batch(keys=keys)
                return data
            else:
                data = self.redisCacheClient.get(name=key)
                if data:
                    return jsonHelper.load_from_json(data=data)
                return None
        except Exception as ex:
            self.logger.error(f"❌ Error getting data from Redis for key {key}:", ex)
            return None
    
    def _redis_get_batch(self, keys: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get multiple keys from Redis cache in one operation using mget.
        
        Args:
            keys: List of Redis keys to retrieve
        
        Returns:
            Dict mapping each key to its parsed data (or None if key doesn't exist)
        
        Example:
            keys = ['cache:user:1', 'cache:user:2', 'cache:user:3']
            results = cache_service._redis_get_batch(keys)
            # Returns: {
            #     'cache:user:1': {'name': 'John'},
            #     'cache:user:2': {'name': 'Jane'},
            #     'cache:user:3': None  # if key doesn't exist
            # }
        """
        if not keys:
            return {}
        
        try:
            # Use mget to get all values in one round trip
            values = self.redisCacheClient.mget(keys)
            
            # Parse results and map to keys
            results = {}
            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        results[key] = jsonHelper.load_from_json(data=value)
                    except Exception as ex:
                        self.logger.warning(f"⚠️ Error parsing JSON for key {key}:", ex)
                        results[key] = None
                else:
                    results[key] = None
            
            return results
        except Exception as ex:
            self.logger.error(f"❌ Error getting batch data from Redis:", ex)
            # Return dict with None values for all keys on error
            return {key: None for key in keys}
    
    def _redis_set(self, key: str, data: Dict[str, Any], ttl_seconds: int = 3600) -> bool:
        """Set data in Redis cache with TTL"""
        try:
            if ttl_seconds < 0:
                self.redisCacheClient.delete(key)
                return True
            json_data = jsonHelper.save_to_json(data=data)
            self.redisCacheClient.setex(name=key, time=ttl_seconds, value=json_data)
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error setting data in Redis for key {key}:", ex)
            return False
    
    def _redis_set_batch(self, items: List[Dict[str, Any]], default_ttl_seconds: int = 3600) -> bool:
        """
        Set multiple keys in Redis cache with TTL in one operation using pipeline.
        
        Args:
            items: List of dicts with keys: 'key' (str), 'data' (Dict[str, Any]), 'ttl_seconds' (int, optional)
            default_ttl_seconds: Default TTL to use if not specified in item
        
        Returns:
            bool: True if all operations succeeded, False otherwise
        
        Example:
            items = [
                {'key': 'cache:user:1', 'data': {'name': 'John'}, 'ttl_seconds': 3600},
                {'key': 'cache:user:2', 'data': {'name': 'Jane'}, 'ttl_seconds': 7200},
                {'key': 'cache:user:3', 'data': {'name': 'Bob'}}  # Uses default_ttl_seconds
            ]
            cache_service._redis_set_batch(items, default_ttl_seconds=3600)
        """
        if not items:
            return True
        
        try:
            pipe = self.redisCacheClient.pipeline()
            for item in items:
                key = item.get('key')
                value = item.get('value')
                ttl_seconds = item.get('ttl_seconds', default_ttl_seconds)
                
                if not key or value is None:
                    self.logger.warning(f"⚠️ Skipping invalid item in batch set: missing key or data")
                    continue
                
                json_value = jsonHelper.save_to_json(data=value)
                pipe.setex(name=key, time=ttl_seconds, value=json_value)
            
            # Execute all commands in one round trip
            pipe.execute()
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error setting batch data in Redis:", ex)
            return False
    
    def _redis_delete(self, key: str) -> bool:
        """Delete data from Redis cache"""
        try:
            self.redisCacheClient.delete(key)
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error deleting data from Redis for key {key}:", ex)
            return False
    
    def _redis_exists(self, key: str) -> bool:
        """Check if key exists in Redis cache"""
        try:
            if key.endswith(':*'):
                return len(self.redis_get_keys(pattern=key)) > 0
            return bool(self.redisCacheClient.exists(key))
        except Exception as ex:
            self.logger.error(f"❌ Error checking existence in Redis for key {key}:", ex)
            return False
    
    def _get_cache_key(self, tenantKey: str, entityType: str, identifier: str = None) -> str:
        """Get Redis cache key for a specific cache type and identifier"""
        key = f"{self._env}:{tenantKey.replace('#',':')}:{self._cache_prefix}{entityType}"
        if identifier:
            identifier = identifier.replace('#',':')
            tokens = identifier.split(':')
            if len(tokens) > 1:
                if tokens[0] == tokens[1]:
                    identifier = ':'.join(tokens[1:])
            return f"{key}:{identifier}"
        return f"{key}"

    def _get_cache_ttl_key(self, tenantKey: str, entityType: str) -> str:
        """Get Redis cache TTL key for a specific cache type"""
        key = f"{self._env}:{tenantKey.replace('#',':')}:{self._cache_ttl_prefix}{entityType}"
        return f"{key}"
    
    def _redis_cache_get(self, tenantKey: str, entityType: str, identifier: str = None, keys: List[str] = None) -> Dict[str, Any]:
        """Get cache data from Redis"""
        data = {}
        keyIdentifiers = self._get_keyidentifiers(identifier=identifier, keys=keys)        
        for key, value in keyIdentifiers.items():
            cacheKey = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=value.get('identifier'))
            redisValue = self._redis_get(cacheKey) or {}
            if value.get('single'):
                for _key, _value in redisValue.items():
                    _key = _key.split(':AAAA:')[-1].replace(':', '#')
                    data = data | {_key: _value}
                break
            data = data | {key: redisValue}

        if entityType == EntityType.REFEREEGAMES or entityType == EntityType.TOURNAMENTSGAMES:
            if False and identifier:
                data = self.multiTenantSupport.mapItem(tenantKey=tenantKey, objType='games', obj=data)
            else:
                self.multiTenantSupport.mapList(tenantKey=tenantKey, objType='games', objs=data)
        elif entityType == EntityType.REFEREEREVIEWS:
            if identifier:
                data = self.multiTenantSupport.mapItem(tenantKey=tenantKey, objType='reviews', obj=data)
            else:
                self.multiTenantSupport.mapList(tenantKey=tenantKey, objType='reviews', objs=data)
        return data

    def _redis_cache_set(self, tenantKey: str, entityType: str, data: Dict[str, Any], identifier: str = None, ttl_seconds: int = None) -> bool:
        """Set cache data in Redis"""
        key = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=identifier)
        if ttl_seconds is None:
            ttl_seconds = DbClientBase.CacheTypes.get(entityType, {}).get('ttl', 3600)
        
        # Set the data
        result = self._redis_set(key=key, data=data, ttl_seconds=ttl_seconds)
        
        # Auto-expire related cache entries based on cache type
        if result:
            self._auto_expire_related_entries(tenantKey=tenantKey, entityType=entityType, identifier=identifier, data=data)
        
        return result
    
    def _redis_cache_delete(self, tenantKey: str, entityType: str, identifier: str = None, keys:list[str] = None) -> bool:
        """Delete cache data from Redis"""
        keyIdentifiers = self._get_keyidentifiers(identifier=identifier, keys=keys)
        result = False
        for key, value in keyIdentifiers.items():
            cacheKey = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=value.get('identifier'))
            result = result or self._redis_delete(key=cacheKey)
        return result
    
    def _redis_cache_get_keys(self, tenantKey: str, entityType: str, identifier: str = None) -> List[str]:
        """Get cache keys from Redis"""
        key = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=identifier)
        return self.redis_get_keys(key)

    def _auto_expire_related_entries(self, tenantKey: str, entityType: str, identifier: str, data: Dict[str, Any]) -> None:
        """Automatically expire related cache entries when data is updated"""
        return
        try:
            if entityType == 'refereeGames' and identifier:
                # When referee game is updated, expire related referee reviews
                ref_id, gamePk = identifier.split(':', 1) if ':' in identifier else (identifier, None)
                if gamePk:
                    self.expire_referee_review(refId=ref_id, gamePk=gamePk)
                    self.logger.debug(f"🔄 Auto-expired referee review for {ref_id}:{gamePk}")
            
            elif entityType == 'refereeReviews' and identifier:
                # When referee review is updated, expire related referee games
                ref_id, gamePk = identifier.split(':', 1) if ':' in identifier else (identifier, None)
                if gamePk:
                    self.expire_referee_game(refId=ref_id, gamePk=gamePk)
                    self.logger.debug(f"🔄 Auto-expired referee game for {ref_id}:{gamePk}")
            
            elif entityType == 'tournamentGames' and identifier:
                # When tournament game is updated, expire related game detail mappings
                tournament_name, gamePk = identifier.split(':', 1) if ':' in identifier else (identifier, None)
                if gamePk and data and data.get('id'):
                    # Expire game detail mapping by ID
                    self._redis_cache_delete(entityType='gameDetailId', identifier=str(data.get('id')))
                    self.logger.debug(f"🔄 Auto-expired game detail mapping for ID {data.get('id')}")
            
            elif entityType in ['fields', 'tournaments', 'seasons', 'rules', 'sections', 'documents', 'referees']:
                # For static data, expire all related dynamic data when static data changes
                self._expire_all_dynamic_data()
                self.logger.debug(f"🔄 Auto-expired all dynamic data due to {entityType} update")
                
        except Exception as ex:
            self.logger.error(f"❌ Error in auto-expire related entries for {entityType}:{identifier}:", ex)
    
    def _expire_all_dynamic_data(self) -> None:
        """Expire all dynamic data when static data changes"""
        try:
            # Get all referee games keys
            referee_games_keys = self.redis_get_keys(f"{self._env}:*:{self._cache_prefix}refereeGames:*")
            for key in referee_games_keys:
                self.redis_delete(key)

            # Get all referee reviews keys
            referee_reviews_keys = self.redis_get_keys(f"{self._env}:*:{self._cache_prefix}refereeReviews:*")
            for key in referee_reviews_keys:
                self.redis_delete(key)

            # Get all tournament games keys
            tournament_games_keys = self.redis_get_keys(f"{self._env}:*:{self._cache_prefix}tournamentGames:*")
            for key in tournament_games_keys:
                self.redis_delete(key)

            # Get all game detail mappings
            game_detail_keys = self.redis_get_keys(f"{self._env}:*:{self._cache_prefix}gameDetailId:*")
            for key in game_detail_keys:
                self.redis_delete(key)
                
            self.logger.debug("🗑️ Auto-expired all dynamic data due to static data update")
            
        except Exception as ex:
            self.logger.error(f"❌ Error expiring all dynamic data:", ex)
    
    def _invalidate_cache_for_filter(self, filter_dict: dict) -> None:
        """Invalidate cache entries based on a filter"""
        try:
            # For filter-based operations, we need to be more conservative
            # and invalidate all dynamic data since we can't easily determine
            # which specific entries were affected
            self._expire_all_dynamic_data()
            self.logger.debug(f"🔄 Invalidated all dynamic data due to filter operation")
        except Exception as ex:
            self.logger.error(f"❌ Error invalidating cache for filter:", ex)
    
    def _invalidate_cache_for_gamePk(self, gamePk: str, tournamentGameId: Optional[int] = None) -> None:
        """Invalidate cache entries for a specific game PK"""
        try:
            # Find and invalidate all cache entries related to this game PK
            # Note: these three patterns have no tenantKey segment/wildcard even after this env
            # fix (pre-existing, not introduced by the env-prefix change) - real keys are always
            # {env}:{tenantKey}:{cache_prefix}{entityType}:..., so as written this glob can only
            # ever match a key for the literal (nonexistent) "GLOBAL"-less tenant segment. Left
            # as-is beyond adding the env segment for consistency - fixing the missing tenant
            # wildcard is a separate, pre-existing issue outside this change's scope.
            patterns = [
                f"{self._env}:{self._cache_prefix}{EntityType.REFEREEGAMES}:*:{gamePk or tournamentGameId}",
                f"{self._env}:{self._cache_prefix}{EntityType.REFEREEREVIEWS}:*:{gamePk or tournamentGameId}",
                f"{self._env}:{self._cache_prefix}{EntityType.TOURNAMENTSGAMES}:*:{gamePk or tournamentGameId}"
            ]
            
            for pattern in patterns:
                keys = self.redis_get_keys(pattern)
                for key in keys:
                    self.redis_delete(key)
            
            self.logger.debug(f"🔄 Invalidated cache entries for game PK {gamePk or tournamentGameId}")
        except Exception as ex:
            self.logger.error(f"❌ Error invalidating cache for game PK {gamePk or tournamentGameId}:", ex)

    def _redis_get_cache_ttl(self, tenantKey: str, entityType: str) -> int:
        """Get cache TTL from Redis"""
        key = self._get_cache_ttl_key(tenantKey=tenantKey, entityType=entityType)
        data = self._redis_get(key)
        if data and 'ttl' in data:
            return data['ttl']
        return DbClientBase.CacheTypes.get(entityType, {}).get('ttl', 3600)
    
    def _load_fields(self):
        """Load fields data from database"""
        try:
            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                fields = self.dbClient.getFields(tenantKey=tenantKey)
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.FIELDS, data=fields or {}, identifier=None)
                self.logger.debug(f"📋 Loaded {len(fields or {})} fields for tenant {tenant}")
        except Exception as ex:
            self.logger.error(f"Error loading fields:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.FIELDS, data={})
    
    def _load_tournaments(self):
        """Load tournaments data from database"""
        try:
            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                tournaments = self.dbClient.getTournaments(tenantKey=tenantKey)
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTS, data=tournaments or {}, identifier=None)
                self.logger.debug(f"🏆 Loaded {len(tournaments or {})} tournaments for tenant {tenant}")
        except Exception as ex:
            self.logger.error(f"Error loading tournaments:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.TOURNAMENTS, data={})
    
    def _load_seasons(self):
        """Load seasons data from database"""
        try:
            seasons = self.dbClient.getSeasons()
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.SEASONS, data=seasons or {})
            self.logger.debug(f"📅 Loaded {len(seasons or {})} seasons")
        except Exception as ex:
            self.logger.error(f"Error loading seasons:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.SEASONS, data={})
    
    def _load_rules(self):
        """Load rules data from database"""
        try:
            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                rules = self.dbClient.getRules(tenantKey=tenantKey)
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.RULES, data=rules or {}, identifier=None)
                self.logger.debug(f"📜 Loaded {len(rules or {})} rules for tenant {tenant}")
        except Exception as ex:
            self.logger.error(f"Error loading rules:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.RULES, data={})
    
    def _load_sections(self):
        """Load sections data from database"""
        try:
            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                sections = self.dbClient.getSections(tenantKey=tenantKey)
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.SECTIONS, data=sections or {}, identifier=None)
                self.logger.debug(f"📂 Loaded {len(sections or {})} sections for tenant {tenant}")
        except Exception as ex:
            self.logger.error(f"Error loading sections:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.SECTIONS, data={})
    
    def _load_roles(self):
        """Load roles data from database"""
        try:
            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                roles = self.dbClient.getRoles(tenantKey=tenantKey)
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.ROLES, data=roles or {}, identifier=None)
                self.logger.debug(f"🎭 Loaded {len(roles or {})} roles for tenant {tenant}")
        except Exception as ex:
            self.logger.error(f"Error loading roles:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.ROLES, data={})
    
    def _load_documents(self):
        """Load documents data from database"""
        try:
            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                documents = self.dbClient.getDocuments(tenantKey=tenantKey)
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.DOCUMENTS, data=documents or {}, identifier=None)
                self.logger.debug(f"📄 Loaded {len(documents or {})} documents for tenant {tenant}")
        except Exception as ex:
            self.logger.error(f"Error loading documents:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.DOCUMENTS, data={})
    
    def _load_tenants(self):
        """Load organization services data from database"""
        try:
            tenants = self.dbClient.getTenants()
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.TENANTS, data=tenants or {})
            self.logger.debug(f"🏢 Loaded {len(tenants or {})} organization services")
        except Exception as ex:
            self.logger.error(f"Error loading organization services:", ex)
            self._redis_cache_set(tenantKey='GLOBAL', entityType=EntityType.TENANTS, data={})
    
    def _load_referees(self):
        """Load referees data from database (more dynamic, shorter TTL)"""
        try:
            ttl_seconds = DbClientBase.CacheTypes.get(EntityType.REFEREES, {}).get('ttl', 3600)
            referees = {}
            refereesGlobal = self.dbClient.getRefereeProperties()  # keyed by refereeId
            referees['GLOBAL'] = refereesGlobal
            i = 0
            cacheItems = []
            for referee in refereesGlobal.values():
                refereeId = referee.get('refereeId')
                i += 1
                value = {
                    'value': referee,
                    'filters': {}
                }

                # Keyed by refereeId, not mobileNo - mobile_no is nullable and multiple
                # mobile-less referees would otherwise overwrite each other's cache entry.
                cacheKey = self._get_cache_key(tenantKey='GLOBAL', entityType=EntityType.REFEREES, identifier=f'{refereeId}:AAA')
                ttl_seconds = DbClientBase.CacheTypes.get(EntityType.REFEREES, {}).get('ttl', 3600)

                cacheItems.append({'key': cacheKey, 'value': value, 'ttl_seconds': ttl_seconds})

            self._redis_set_batch(items=cacheItems)

            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                cacheItems = []
                tenantReferees = self.dbClient.getTenantRefereeProperties(tenantKey=tenantKey)  # keyed by refereeId
                referees[tenantKey] = tenantReferees

                i = 0
                for refereeId, tenantReferee in tenantReferees.items():
                    i += 1
                    refereeDetail = helpers.merge_nested_dicts(refereesGlobal.get(refereeId, {}), tenantReferee)
                    value = {
                        'value': refereeDetail,
                        'filters': {}
                    }

                    cacheKey = self._get_cache_key(tenantKey=tenantKey, entityType=EntityType.REFEREES, identifier=f'{refereeId}:AAAA')
                    cacheItems.append({'key': cacheKey, 'value': value, 'ttl_seconds': ttl_seconds})

                self._redis_set_batch(items=cacheItems)

            self.logger.debug(f"👥 Loaded {len(refereesGlobal)} referees")

            return referees
        except Exception as ex:
            self.logger.error(f"Error loading referees:", ex)
    
    def _load_referee_games(self, tenantKey: str, refId: str, gamePk: Optional[str] = None, tournamentGameId: Optional[int] = None, include_archived: bool = False, include_removed: bool = False, include_canceled: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None):
        """Load referee games data from database by referee ID and optional game PK"""
        try:
            referee_games = self.dbClient.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=gamePk, tournamentGameId=tournamentGameId, includeArchived=include_archived, includeRemoved=include_removed, includeCanceled=include_canceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
            for gamePk, referee_game in referee_games.items():
                # Store each game individually in Redis
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, data=referee_game or {}, identifier=f"{refId}:{gamePk or tournamentGameId}")
            self.logger.info(f"✅ Loaded {len(referee_games)} referee games for referee {refId}" + (f" and game {gamePk or tournamentGameId}" if gamePk or tournamentGameId else ""))
            return referee_games.keys()
        except Exception as ex:
            self.logger.error(f"Error loading referee games for {refId}" + (f" and game {gamePk or tournamentGameId}" if gamePk or tournamentGameId else "") + f":", ex)
            if gamePk or tournamentGameId:
                self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=refId, keys=gamePk or tournamentGameId)

    def _load_referee_reviews(self, tenantKey: str, refId: str, gamePk: Optional[str] = None, tournamentGameId: Optional[int] = None, from_date: Optional[str] = None, to_date: Optional[str] = None):
        """Load referee reviews data from database by referee ID and optional game PK"""
        try:
            referee_reviews = self.dbClient.getRefereeReviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk, tournamentGameId=tournamentGameId, from_date=from_date, to_date=to_date)
            for gamePk, referee_review in referee_reviews.items():
                # Store each review individually in Redis
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, data=referee_review or {}, identifier=f"{refId}:{gamePk or tournamentGameId}")
            self.logger.info(f"✅ Loaded {len(referee_reviews)} referee reviews for referee {refId}" + (f" and game {gamePk or tournamentGameId}" if gamePk or tournamentGameId else ""))
            return referee_reviews.keys()
        except Exception as ex:
            self.logger.error(f"Error loading referee reviews for {refId}" + (f" and game {gamePk or tournamentGameId}" if gamePk or tournamentGameId else "") + f":", ex)
            if gamePk or tournamentGameId:
                self._redis_cache_delete(entityType=EntityType.REFEREEREVIEWS, identifier=refId, keys=gamePk or tournamentGameId)


    def _load_tournamentGames(self, tenantKey: str, tournamentName: str, gamePk: Optional[str] = None, tournamentGameId: Optional[int] = None, nonArchivedOnly: bool = False, filters: list = []):
        """Load tournament games data from database by tournament name and optional game PK"""
        try:
            result = self.dbClient.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, tournamentGameId=tournamentGameId, nonArchivedOnly=nonArchivedOnly, filters=filters)
            if not result:
                return {}
            #self.multiTenantSupport.mapList(objType='games', refereeItems=result)
            tournamentGames = result
            for _gamePk, _tournamentGame in tournamentGames.items():
                # Store each game individually in Redis
                _tournamentName = _tournamentGame.get('tournamentName')
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, data=_tournamentGame or {}, identifier=f"{_tournamentName}:{_gamePk or tournamentGameId}")
                
                # Store game detail mapping
                if False and _tournamentGame and _tournamentGame.get("id"):
                    self._redis_cache_set(tenantKey='GLOBAL', entityType='gameDetailId', data=_tournamentGame, identifier=str(_tournamentGame.get("id")))
                    #self._redis_cache_set(tenantKey='GLOBAL', entityType='gameDetailId', data={"tenantKey": tenantKey, "tournamentName": tournamentName, "gamePk": gamePk}, identifier=str(tournamentGame.get("id")))
            self.logger.info(f"✅ Loaded {len(tournamentGames)} tournament games for tournament {tournamentName}" + (f" and game PK {gamePk or tournamentGameId}" if gamePk or tournamentGameId else ""))
            return tournamentGames
        except Exception as ex:
            self.logger.error(f"Error loading tournament games for {tournamentName}" + (f" and game PK {gamePk or tournamentGameId}" if gamePk or tournamentGameId else "") + f":", ex)
            if gamePk or tournamentGameId:
                self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=tournamentName, keys=gamePk or tournamentGameId)

    # Public access methods
    @cacheDecorator.cache(entityType=EntityType.FIELDS, actionType=ActionType.GET)
    def getFields(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get fields data from cache"""
        with self._internal_lock:
            return self.dbClient.getFields(tenantKey=tenantKey)

    @cacheDecorator.cache(entityType=EntityType.AREAS, actionType=ActionType.GET)
    def getAreas(self, forceReload: bool = False) -> Dict[str, Any]:
        """Get areas data from cache (global, not tenant-scoped)"""
        with self._internal_lock:
            return self.dbClient.getAreas()

    @cacheDecorator.cache(entityType=EntityType.NOTIFICATIONTYPES, actionType=ActionType.GET)
    def getNotificationTypes(self, forceReload: bool = False) -> Dict[str, Any]:
        """Get notification-type catalog data from cache (global, not tenant-scoped)"""
        with self._internal_lock:
            return self.dbClient.getNotificationTypes()

    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTS, actionType=ActionType.GET)
    def getTournaments(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get tournaments data from cache"""
        with self._internal_lock:
            return self.dbClient.getTournaments(tenantKey=tenantKey)
    
    @cacheDecorator.cache(entityType=EntityType.SEASONS, actionType=ActionType.GET)
    def getSeasons(self, forceReload: bool = False) -> Dict[str, Any]:
        """Get seasons data from cache"""
        with self._internal_lock:
            return self.dbClient.getSeasons()
    
    @cacheDecorator.cache(entityType=EntityType.RULES, actionType=ActionType.GET)
    def getRules(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get rules data from cache"""
        with self._internal_lock:
            return self.dbClient.getRules(tenantKey=tenantKey)
    
    @cacheDecorator.cache(entityType=EntityType.SECTIONS, actionType=ActionType.GET)
    def getSections(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get sections data from cache"""
        with self._internal_lock:
            return self.dbClient.getSections(tenantKey=tenantKey)
    
    @cacheDecorator.cache(entityType=EntityType.ROLES, actionType=ActionType.GET)
    def getRoles(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get roles data from cache"""
        with self._internal_lock:
            return self.dbClient.getRoles(tenantKey=tenantKey)
    
    def getDocuments(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get documents data from cache"""
        with self._internal_lock:
            return self.dbClient.getDocuments(tenantKey=tenantKey)
    
    @cacheDecorator.cache(entityType=EntityType.TENANTS, actionType=ActionType.GET)
    def getTenants(self, forceReload: bool = False) -> Dict[str, Any]:
        """Get organization services data from cache"""
        with self._internal_lock:
            return self.dbClient.getTenants()
    
    #@cacheDecorator.cache(entityType=EntityType.REFEREES, actionType=ActionType.GET)
    def getRefereesNoCache(self) -> Dict[str, Any]:
        """Get referees data from cache"""
        with self._internal_lock:
            tenants = self.getTenants()
            referees = {}
            referees['GLOBAL'] = self.getReferees(tenantKey='GLOBAL', forceReload=True)
            for tenantKey, tenant in tenants.items():
                referees[tenantKey] = self.getReferees(tenantKey=tenantKey, forceReload=True)
            return referees
    
    @cacheDecorator.cache(entityType=EntityType.CLIENTIDENTIFIERS, actionType=ActionType.GET)
    def getClientIdentifier(self, clientIdentifier, from_created: datetime = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get client identifier data from database (not cached as it's user-specific)"""
        try:
            with self._internal_lock:
                result = self.dbClient.getClientIdentifier(clientIdentifier=clientIdentifier, from_created=from_created)
                return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting client identifier {clientIdentifier}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.MEDIAFILEMETADATA, actionType=ActionType.GET)
    def getMediaFileMetadata(self, tenantKey: str, file_id, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get media file metadata from database (not cached as it's file-specific)"""
        try:
            return self.dbClient.getMediaFileMetadata(tenantKey=tenantKey, file_id=file_id)
        except Exception as ex:
            self.logger.error(f"❌ Error getting media file metadata {file_id}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.MEDIAFILEMETADATA, actionType=ActionType.GET)
    def getMediaFilesByMobile(self, tenantKey: str, mobile_no, forceReload: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Get media files by mobile number from database (not cached as it's user-specific)"""
        try:
            return self.dbClient.getMediaFilesByMobile(tenantKey=tenantKey, mobile_no=mobile_no)
        except Exception as ex:
            self.logger.error(f"❌ Error getting media files for mobile {mobile_no}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.MEDIAFILEMETADATA, actionType=ActionType.GET)
    def getMediaFilesByMessageSid(self, tenantKey: str, message_sid, forceReload: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Get media files by message SID from database (not cached as it's message-specific)"""
        try:
            return self.dbClient.getMediaFilesByMessageSid(tenantKey=tenantKey, message_sid=message_sid)
        except Exception as ex:
            self.logger.error(f"❌ Error getting media files for message {message_sid}:", ex)
            return None
    
    def getDict(self, tenantKey: str, keyPrefix, entityKey=None, jsonDumps=True, asIsEntityKey=False, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get dictionary data from database (not cached as it's key-specific)"""
        try:
            return self.dbClient.getDict(tenantKey=tenantKey, keyPrefix=keyPrefix, entityKey=entityKey, jsonDumps=jsonDumps, asIsEntityKey=asIsEntityKey)
        except Exception as ex:
            self.logger.error(f"❌ Error getting dict for prefix {keyPrefix}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.LEAGUETABLES, actionType=ActionType.GET)
    def getLeagueTables(self, tenantKey: str, tournamentName, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get league table data from database (not cached as it's tournament-specific)"""
        try:
            result = self.dbClient.getLeagueTables(tenantKey=tenantKey, tournamentName=tournamentName)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting league table for {tournamentName}:", ex)
            return None
    
    def getTournamentGamesArchived(self, tenantKey: str, tournamentName, gamePk=None, tournamentGameId=None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get archived tournament games from database (not cached as it's tournament-specific)"""
        try:
            return self.dbClient.getTournamentGamesArchived(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, tournamentGameId=tournamentGameId)
        except Exception as ex:
            self.logger.error(f"❌ Error getting archived tournament games for {tournamentName}:", ex)
            return None

    def getPublicGames(
        self,
        tenant_keys: list,
        tournament_name: str = None,
        section_filter: str = None,
        from_date=None,
        to_date=None,
        field_filter: str = None,
        referee_id: int = None,
        referee_name: str = None,
    ):
        """Delegate to dbClient.getPublicGames when available (PostgreSQL optimized path)."""
        if not hasattr(self.dbClient, 'getPublicGames'):
            return None
        try:
            return self.dbClient.getPublicGames(
                tenant_keys=tenant_keys,
                tournament_name=tournament_name,
                section_filter=section_filter,
                from_date=from_date,
                to_date=to_date,
                field_filter=field_filter,
                referee_id=referee_id,
                referee_name=referee_name,
            )
        except Exception as ex:
            self.logger.error('❌ Error in getPublicGames:', ex)
            return None

    def patchCarpoolForGame(self, tenantKey: str, tournamentName: str, gamePk: str = None, tournamentGameId: Optional[int] = None, carpoolData: Optional[Dict[str, Any]] = None):
        try:
            games = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, tournamentGameId=tournamentGameId)
            game = (games or {}).get(gamePk)
            if not game:
                self.logger.warning(f"patchCarpoolForGame: game not found tenantKey={tenantKey} gamePk={gamePk} tournamentGameId={tournamentGameId}")
                return
            if carpoolData is None:
                game.pop('carpool', None)
            else:
                game['carpool'] = carpoolData
            self.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, tournamentGameId=tournamentGameId, value=game)
        except Exception as ex:
            self.logger.error(f"patchCarpoolForGame error tenantKey={tenantKey} gamePk={gamePk} tournamentGameId={tournamentGameId}:", ex)

    @cacheDecorator.cache(entityType=EntityType.REFEREES, actionType=ActionType.GET)
    def getReferees(self, tenantKey: str, mobileNo: str=None, refereeId: Optional[int]=None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get referee properties from database (not cached as it's referee-specific).
        mobileNo is kept only for referees not yet known/created (no refereeId exists yet);
        prefer refereeId wherever the caller can resolve it."""
        try:
            if tenantKey == 'GLOBAL':
                result = self.dbClient.getRefereeProperties(mobileNo=mobileNo, refereeId=refereeId)
            else:
                result = self.dbClient.getTenantRefereeProperties(tenantKey=tenantKey, mobileNo=mobileNo, refereeId=refereeId)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee properties for {mobileNo or refereeId}:", ex)
            return None

    def resolveRefereeIdByMobile(self, mobileNo: str) -> Optional[int]:
        """Resolve a mobileNo to its Postgres referees.id, for callers that only have a mobileNo
        (e.g. legacy tokens, webhook-origin data) and no access to an in-memory referee index."""
        if not mobileNo:
            return None
        try:
            result = self.dbClient.getRefereeProperties(mobileNo=mobileNo)
            referee = next(iter((result or {}).values()), None)
            return referee.get('refereeId') if referee else None
        except Exception as ex:
            self.logger.error(f"❌ Error resolving refereeId for {mobileNo}:", ex)
            return None

    def resolveRefereeIdByInternalId(self, tenantKey: str, internalRefereeId) -> Optional[int]:
        """Resolve a tenant-scoped internalRefereeId to its Postgres referees.id, for referees
        that don't have a mobile number yet (mirrors resolveRefereeIdByMobile)."""
        if not tenantKey or internalRefereeId is None:
            return None
        try:
            return self.dbClient.resolveRefereeIdByInternalId(tenantKey=tenantKey, internalRefereeId=internalRefereeId)
        except Exception as ex:
            self.logger.error(f"❌ Error resolving refereeId for internalRefereeId={internalRefereeId} tenantKey={tenantKey}:", ex)
            return None

    def getRefereeProperty(self, tenantKey: str, mobileNo: str = None, refereeId: Optional[int] = None, propertyName: str = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        referee = self.getReferees(tenantKey=tenantKey, mobileNo=mobileNo, refereeId=refereeId, forceReload=forceReload)
        if referee:
            if propertyName and referee.get(propertyName):
                return referee.get(propertyName.replace(' ', ''))
            else:
                return referee
        return None

    def getCacheOnlyKey(self, **kwargs):
        tenantKey = kwargs.pop('tenantKey', 'GLOBAL')
        entityType = kwargs.pop('entityType', None)
        segments = []
        segments.append(self._env)
        segments.append(tenantKey)
        segments.append('cacheOnly')
        if entityType:
            segments.append(str(entityType))
        segments.extend([str(v) for k, v in kwargs.items()])
        key = ':'.join(segments)
        key = key.replace('#', ':')
        return key

    def getCacheOnlyKeyVal(self, **kwargs):
        key = self.getCacheOnlyKey(**kwargs)
        data = self.redis_get(key=key)
        if data is None:
            return None
        #use regex to remove " from start and end from data, i.e. "abc" return abc
        try:
            data = re.sub(r'^["\'](.*)["\']$', r'\1', data)
        except Exception as ex:
            pass
        try:
            data = jsonHelper.load_from_json(data)
        except Exception as ex:
            jsonStr = jsonHelper.save_to_json({'value': data})
            data = jsonHelper.load_from_json(jsonStr)
        if isinstance(data, dict) and 'value' in data:
            data = data['value']
        return data

    def getRefereeAvailaiblity(self, refereeId: Optional[int] = None, from_date: datetime = None, to_date: datetime = None) -> Optional[Dict[str, Any]]:
        """Get referee availability from database - deliberately NOT decorated with @cacheDecorator.cache:
        that decorator's cache key is scoped only by refereeId (see EntityType.REFEREEAVAILABILITY's
        partitionKeys in dbClientBase.py), with no entityKeys for from_date/to_date - so any two calls
        for the same referee with different date ranges within the 60-minute TTL would silently return
        whichever range was cached first, regardless of what was actually requested (this bit hard once
        week-to-week navigation started making back-to-back calls with different ranges)."""
        try:
            result = self.dbClient.getRefereeAvailaiblity(refereeId=refereeId, from_date=from_date, to_date=to_date)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee availability for {refereeId}:", ex)
            return None

    @cacheDecorator.cache(entityType=EntityType.REFEREETEMPLATES, actionType=ActionType.GET)
    def getRefereeTemplates(self, tenantKey: str, refereeId: Optional[int] = None, action:str = None, msgSid:Optional[str] = None, status:Optional[str] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, from_updated: Optional[datetime] = None, to_updated: Optional[datetime] = None, forceReload: bool = False, **kwargs) -> Optional[List[Dict[str, Any]]]:
        """Get referee templates from database (not cached as it's mobile-specific)"""
        try:
            result = self.dbClient.getRefereeTemplates(tenantKey=tenantKey, refereeId=refereeId, action=action, msgSid=msgSid, status=status, from_created=from_created, to_created=to_created, from_updated=from_updated, to_updated=to_updated)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee templates for {refereeId}:", ex)
            return None

    @cacheDecorator.cache(entityType=EntityType.REFEREEMESSAGES, actionType=ActionType.GET)
    def getRefereeMessages(self, mobileNo:Optional[str] = None, refereeId: Optional[int] = None, direction:str = None, msgSid:Optional[str] = None, recentDays:Optional[int] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, forceReload: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Get referee messages from database (not cached as it's mobile-specific)"""
        try:
            result = self.dbClient.getRefereeMessages(mobileNo=mobileNo, refereeId=refereeId, direction=direction, msgSid=msgSid, recentDays=recentDays, from_created=from_created, to_created=to_created)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee messages for {mobileNo or refereeId}:{direction} {ex}")
            return None
        
    @cacheDecorator.cache(entityType=EntityType.MESSAGES, actionType=ActionType.GET)
    def getMessage(self, msgSid, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get message from database (not cached as it's message-specific)"""
        try:
            result = self.dbClient.getMessage(msgSid=msgSid)
            return list(result.values())[0]
        except Exception as ex:
            self.logger.error(f"❌ Error getting message {msgSid}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.KEYVAL, actionType=ActionType.GET)
    def getKeyVal(self, key, forceReload: bool = False) -> Optional[Any]:
        """Get key-value from database (not cached as it's key-specific)"""
        try:
            result = self.dbClient.getKeyVal(key=key)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting key-value for {key}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.POSITIONUPDATES, actionType=ActionType.GET)
    def getPositionUpdates(self, mobileNo):
        with self._internal_lock:
            result = self.dbClient.getPositionUpdates(mobileNo=mobileNo)
            return result

    @cacheDecorator.cache(entityType=EntityType.REFEREELOCATIONS, actionType=ActionType.GET)
    def getRefereeLocations(self, mobileNo, timestamp:int=None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        with self._internal_lock:
            result = self.dbClient.getRefereeLocations(mobileNo=mobileNo, timestamp=timestamp)
            return result

    @cacheDecorator.cache(entityType=EntityType.REFERENCEIDS, actionType=ActionType.GET)
    def getReferenceId(self, target: str, target_id: str = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get reference ID from database (not cached as it's reference-specific)"""
        try:
            result = self.dbClient.getReferenceId(target=target, target_id=target_id)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting reference ID for {target}:{target_id}:", ex)
            return None

    @cacheDecorator.cache(entityType=EntityType.NOTIFICATIONS, actionType=ActionType.GET)
    def getNotifications(self, tenantKey: str, target: str, target_id: int = ..., notificationType: str = None, target_to=None, status: str = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, from_updated: Optional[datetime] = None, to_updated: Optional[datetime] = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get notifications from database (not cached as it's notification-specific)"""
        try:
            result = self.dbClient.getNotifications(tenantKey=tenantKey, target=target, target_id=target_id, notificationType=notificationType, target_to=target_to, status=status, from_created=from_created, to_created=to_created, from_updated=from_updated, to_updated=to_updated)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting notifications for {target}:{target_id}:{notificationType}:", ex)
            return None

    #@cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.COUNT)
    def countRefereeGames(self, tenantKey: str, refId: str = None, refereeId: Optional[int] = None, includeArchived: bool = False, includeRemoved: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, expr: Callable = None) -> int:
        games = self.getRefereeGames(tenantKey=tenantKey, refId=refId, refereeId=refereeId, includeArchived=includeArchived, includeRemoved=includeRemoved, from_date=from_date, to_date=to_date)
        filteredGames = [game for game in games.values() if expr(game)] if expr else list(games.values())
        return len(filteredGames)

    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.GET)
    def getRefereeGames(self, tenantKey: str, refId: Optional[str] = None, mobileNo: Optional[str] = None, refereeId: Optional[int] = None, gamePk: Optional[str] = None, tournamentGameId: Optional[int] = None, includeArchived: bool = False, includeRemoved: bool = False, includeCanceled: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, forceReload: bool = False, **kwargs) -> Dict[str, Any]:
        """Get referee games data from cache by referee ID (legacy, DynamoDB-only), mobileNo (referee
        identity in transition, e.g. tmpRefId merges), or global referees.id, and optional game PK"""
        with self._internal_lock:
            result = self.dbClient.getRefereeGames(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, tournamentGameId=tournamentGameId, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
            return result
            
    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.SET)
    def setRefereeGame(self, tenantKey, value, refId=None, mobileNo=None, refereeId=None, gamePk=None, tournamentGameId=None):
        """Proxy for dbClient.setRefereeGame with cache invalidation"""
        result = self.dbClient.setRefereeGame(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, tournamentGameId=tournamentGameId, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.GET)
    def getRefereeReviews(self, tenantKey: str, refId: Optional[str] = None, mobileNo: Optional[str] = None, refereeId: Optional[int] = None, gamePk: Optional[str] = None, tournamentGameId: Optional[int] = None, season: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None, forceReload: bool = False) -> Dict[str, Any]:
        """Get referee reviews data from cache by referee ID (legacy, DynamoDB-only), mobileNo (referee
        identity in transition, e.g. tmpRefId merges), or global referees.id, and optional game PK"""
        with self._internal_lock:
            return self.dbClient.getRefereeReviews(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, tournamentGameId=tournamentGameId, from_date=from_date, to_date=to_date)

    #@cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.COUNT)
    def countTournamentGames(self, tenantKey: str, tournamentName: str = None, nonArchivedOnly: bool = False, expr: Callable = None) -> int:
        games = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, nonArchivedOnly=nonArchivedOnly)
        filteredGames = [game for game in games.values() if expr(game)] if expr else list(games.values())
        return len(filteredGames)

    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.GET)
    def getTournamentGames(self, tenantKey: Optional[str] = None, tournamentGameId: Optional[int] = None, tournamentName: str = None, gamePk: Optional = None, gameId: Optional[str] = None, nonArchivedOnly: bool = False, forceReload: bool = False, filters: list = []) -> Dict[str, Any]:
        """Get tournament games data from cache by tournament name and optional game PK"""
        with self._internal_lock:
            result = self.dbClient.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, tournamentGameId=tournamentGameId, gamePk=gamePk, gameId=gameId, nonArchivedOnly=nonArchivedOnly, filters=filters)
            return result
            if gamePk:
                if forceReload or not self._is_cache_valid(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=tournamentName, keys=gamePk):
                    self._load_tournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
                return self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=tournamentName, keys=gamePk)
            else:
                # Load all games with filters
                tournamentGames = self._load_tournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, nonArchivedOnly=nonArchivedOnly, filters=filters)
                
                # Get all games from Redis
                games = {}
                for _gamePk, _tournamentGame in tournamentGames.items():
                    _tournamentName = _tournamentGame.get('tournamentName')
                    game_data = self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=f"{_tournamentName}:{_gamePk}")
                    if game_data:
                        games = games | {_gamePk: game_data}
                
                return games
    
    #@cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.GET)
    def getGameDetail(self, game: dict, forceReload: bool = False) -> Dict[str, Any]:
        """Get tournament games data from cache by tournament name and optional game PK.
        If game already carries an embedded 'gameDetail' (e.g. postgresClient's referee_games_v /
        referee_reviews_v-backed getRefereeGames/getRefereeReviews already joined it in), return
        that directly and skip the extra query. tenantKey is read from game itself rather than
        taken as a separate parameter - every caller already has it there, and a mismatched
        explicit tenantKey would silently look up the wrong tenant's data."""
        if not forceReload and isinstance(game, dict) and game.get('gameDetail'):
            return game['gameDetail']
        with self._internal_lock:
            tenantKey = game.get('tenantKey')
            tournament_name = game.get('tournamentName')
            gamePk = game.get('gamePk')
            tournamentGameId = game.get('tournamentGameId')
            if tournament_name and (gamePk or tournamentGameId):
                gameDetail = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournament_name, gamePk=gamePk, tournamentGameId=tournamentGameId, forceReload=forceReload)
                if gameDetail:
                    # getTournamentGames (via @cacheDecorator.cache) already returns a single
                    # unwrapped game dict when both tournamentName+gamePk fully match an entity
                    # key (the common case here) - only unwrap again if it's still a {key: dict}
                    # collection (e.g. a partition-only match with multiple/no gamePk filter).
                    if isinstance(gameDetail, dict) and ('gamePk' in gameDetail or 'tournamentGameId' in gameDetail):
                        return gameDetail
                    return helpers.singleDictValue(gameDetail)
            return None
    
    def getGameDetailById(self, gameId: str, forceReload: bool = False) -> Dict[str, Any]:
        """Resolve a game by its short string identifier or by a real tournamentGameId - both are
        matched directly against tournament_games (tries tournament_game_id and the game_id
        column - see postgresClient.getTournamentGames/setTournamentGame). No longer goes through
        the reference_ids indirection."""
        result = self.getTournamentGames(gameId=gameId, forceReload=forceReload)
        return helpers.singleDictValue(result) if result else None

    # Cache management methods
    def reload_all(self) -> bool:
        """Reload all cached data from database"""
        try:
            self.logger.info("🔄 Reloading all cache data...")
            with self._internal_lock:
                self._load_fields()
                self._load_tournaments()
                self._load_seasons()
                self._load_rules()
                self._load_sections()
                self._load_roles()
                self._load_documents()
                self._load_referees()
                self._load_tenants()
            self.logger.info("✅ All cache data reloaded successfully")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error reloading cache:", ex)
            return False
    
    def reload_specific(self, entityType: str) -> bool:
        """Reload specific cache type"""
        try:
            self.logger.info(f"🔄 Reloading {entityType} cache...")
            with self._internal_lock:
                if entityType == EntityType.FIELDS:
                    self._load_fields()
                elif entityType == EntityType.TOURNAMENTS:
                    self._load_tournaments()
                elif entityType == EntityType.SEASONS:
                    self._load_seasons()
                elif entityType == EntityType.RULES:
                    self._load_rules()
                elif entityType == EntityType.SECTIONS:
                    self._load_sections()
                elif entityType == EntityType.ROLES:
                    self._load_roles()
                elif entityType == EntityType.DOCUMENTS:
                    self._load_documents()
                elif entityType == EntityType.REFEREES:
                    self._load_referees()
                elif entityType == EntityType.TENANTS:
                    self._load_tenants()
                else:
                    self.logger.warning(f"Unknown cache type: {entityType}")
                    return False
            
            self.logger.info(f"✅ {entityType} cache reloaded successfully")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error reloading {entityType} cache:", ex)
            return False
    
    def expire_cache(self, tenantKey: str = None, entityType: Optional[str] = None, identifier: str = None) -> bool:
        """Clear cache data"""
        try:
            with self._internal_lock:
                if entityType:
                    key = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=identifier)

                    # Always use wildcard to clear all keys under the entity/partition tree
                    pattern = f"{key}:*"
                    keys = self.redis_get_keys(pattern=pattern)
                    for key in keys:
                        self.redis_delete(key)
                    
                    self.logger.debug(f"🗑️ Cleared {entityType} cache")
                else:
                    # Clear all cache
                    self.redis_clear_all()
                    self.logger.debug("🗑️ Cleared all cache")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error clearing cache:", ex)
            return False
    
    def get_cache_status(self, tenantKey: str) -> Dict[str, Any]:
        """Get current cache status and statistics"""
        with self._internal_lock:
            # Get all cache keys from Redis
            cache_keys = self.redis_get_keys(f"{self._env}:{tenantKey.replace('#',':')}:{self._cache_prefix}:*")
            cache_types = set()
            
            for key in cache_keys:
                # Extract cache type from key (e.g., "cache:fields" -> "fields")
                cache_type = key.replace(f"{self._cache_prefix}", "").split(":")[0]
                cache_types.add(cache_type)
            
            status = {
                'cacheTypes': list(cache_types),
                'cache_sizes': {},
                'ttl_settings': {}
            }
            
            for entityType in cache_types:
                # Get cache size (count of keys for this type)
                type_keys = self.redis_get_keys(pattern=f"{self._env}:{tenantKey.replace('#',':')}:{self._cache_prefix}{entityType}:*")
                status['cache_sizes'][entityType] = len(type_keys)
                
                # Get TTL setting
                status['ttl_settings'][entityType] = self._redis_get_cache_ttl(tenantKey=tenantKey, entityType=entityType)
            
            return status
    
    def is_cache_valid(self, entityType: str, tenantKey: str = 'GLOBAL') -> bool:
        """Check if specific cache type is valid"""
        with self._internal_lock:
            return self._is_cache_valid(tenantKey=tenantKey, entityType=entityType)
    
    def get_cache_age(self, entityType: str, tenantKey: str = 'GLOBAL') -> Optional[float]:
        """Get age of cache entry in seconds using Redis TTL"""
        with self._internal_lock:
            key = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=None)
            if not self._redis_exists(key=key):
                return None
            ttl = self.redis_get_ttl(key=key)
            if ttl < 0:
                return None
            # Calculate age: TTL remaining - original TTL = age
            original_ttl = self._redis_get_cache_ttl(tenantKey=tenantKey, entityType=entityType)
            age = original_ttl - ttl
            return age if age >= 0 else None
    
    # Utility methods for common operations
    def get_field_by_name(self, tenantKey: str, fieldName: str, forceReload: bool = False, game: dict = None) -> Optional[Dict[str, Any]]:
        """Get specific field by name. If game already carries an embedded 'field' (e.g.
        postgresClient's referee_games_v/referee_reviews_v-backed getRefereeGames/getRefereeReviews
        already joined it in), return that directly and skip the extra query."""
        if not forceReload and isinstance(game, dict) and game.get('field'):
            return game['field']
        fields = self.getFields(tenantKey=tenantKey, forceReload=forceReload)
        return fields.get(fieldName, {})

    def get_area_by_name(self, areaName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get a specific area (global, not tenant-scoped) by name."""
        areas = self.getAreas(forceReload=forceReload)
        return areas.get(areaName, {})

    def get_area_by_id(self, areaId, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get a specific area (global, not tenant-scoped) by id - areas are keyed by name
        in the cache (like fields/documents/rules), so this scans the small areas dict."""
        if areaId is None:
            return {}
        areaId = int(areaId)
        areas = self.getAreas(forceReload=forceReload)
        return next((a for a in areas.values() if a.get('id') == areaId), {})

    def get_notification_type_by_key(self, typeKey: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get a specific notification type (global, not tenant-scoped) by its type_key."""
        types = self.getNotificationTypes(forceReload=forceReload)
        return types.get(typeKey, {})

    def get_tournament_by_name(self, tenantKey: str, tournamentName: str, forceReload: bool = False, game: dict = None) -> Optional[Dict[str, Any]]:
        """Get specific tournament by name. If game already carries an embedded 'tournament'
        (e.g. postgresClient's referee_games_v/referee_reviews_v-backed getRefereeGames/
        getRefereeReviews already joined it in), return that directly and skip the extra query."""
        if not forceReload and isinstance(game, dict) and game.get('tournament'):
            return game['tournament']
        tournaments = self.getTournaments(tenantKey=tenantKey, forceReload=forceReload)
        return tournaments.get(tournamentName, {})
    
    def get_rule_by_name(self, tenantKey: str, ruleName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific rule by name"""
        rules = self.getRules(tenantKey=tenantKey, forceReload=forceReload)
        return rules.get(ruleName, {})
    
    def get_section_by_name(self, tenantKey: str, sectionName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific section by name"""
        if not sectionName:
            return {}
        sections = self.getSections(tenantKey=tenantKey, forceReload=forceReload)
        return sections.get(sectionName, {})
    
    def get_role_by_name(self, tenantKey: str, roleName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific role by name"""
        roles = self.getRoles(tenantKey=tenantKey, forceReload=forceReload)
        return roles.get(roleName, {})
    
    def get_tenant_by_key(self, tenantKey: str, forceReload: bool = False, game: dict = None) -> Optional[Dict[str, Any]]:
        """Get specific tenant by key. If game already carries an embedded 'tenant' (e.g.
        postgresClient's referee_games_v/referee_reviews_v-backed getRefereeGames/getRefereeReviews
        already joined it in), return that directly and skip the extra query."""
        if not forceReload and isinstance(game, dict) and game.get('tenant'):
            return game['tenant']
        tenants = self.getTenants(forceReload=forceReload)
        return tenants.get(tenantKey, {})
    
    def search_fields(self, tenantKey: str, searchTerm: str, forceReload: bool = False) -> List[Dict[str, Any]]:
        """Search fields by name or description"""
        fields = self.getFields(tenantKey=tenantKey, forceReload=forceReload)
        if not searchTerm:
            return list(fields.values())

        results = []
        search_lower = searchTerm.lower()
        
        for fieldName, field in fields.items():
            if (search_lower in fieldName.lower() or 
                (isinstance(field, dict) and 
                 any(search_lower in str(value).lower() for value in field.values() if isinstance(value, str)))):
                results.append(field)
        
        return results
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get detailed cache statistics"""
        with self._internal_lock:
            # Get all cache types from Redis
            all_keys = self.redis_get_keys(pattern=f"{self._env}:*:{self._cache_prefix}*")
            cache_types = set()
            for key in all_keys:
                # Extract cache type from key
                parts = key.split(f"{self._cache_prefix}")
                if len(parts) > 1:
                    cache_type = parts[1].split(":")[0]
                    cache_types.add(cache_type)
            
            stats = {
                'total_cacheTypes': len(cache_types),
                'cache_details': {}
            }
            
            for entityType in cache_types:
                type_keys = self.redis_get_keys(pattern=f"{self._env}:*:{self._cache_prefix}{entityType}:*")
                stats['cache_details'][entityType] = {
                    'entry_count': len(type_keys),
                    'age_seconds': self.get_cache_age(entityType),
                    'is_valid': self.is_cache_valid(entityType),
                    'ttl_seconds': DbClientBase.CacheTypes.get(entityType, {}).get('ttl', 3600)
                }
            
            return stats
    
    # Record expiration methods for dynamic entities
    def expire_referee_game(self, tenantKey: str, refId: str, gamePk: str) -> bool:
        """Mark a specific referee game as expired and remove from cache"""
        try:
            with self._internal_lock:
                if self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{refId}:{gamePk}"):
                    self.logger.debug(f"⏰ Expired referee game {gamePk} for referee {refId}")
                    return True
                else:
                    self.logger.warning(f"Referee game {gamePk} not found in cache for referee {refId}")
                    return False
        except Exception as ex:
            self.logger.error(f"❌ Error expiring referee game {gamePk} for referee {refId}:", ex)
            return False
    
    def expire_referee_review(self, tenantKey: str, refId: str, gamePk: str) -> bool:
        """Mark a specific referee review as expired and remove from cache"""
        try:
            with self._internal_lock:
                if self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{refId}:{gamePk}"):
                    self.logger.debug(f"⏰ Expired referee review {gamePk} for referee {refId}")
                    return True
                else:
                    self.logger.warning(f"Referee review {gamePk} not found in cache for referee {refId}")
                    return False
        except Exception as ex:
            self.logger.error(f"❌ Error expiring referee review {gamePk} for referee {refId}:", ex)
            return False
    
    def expire_tournament_game(self, tenantKey: str, tournamentName: str, gamePk: str) -> bool:
        """Mark a specific tournament game as expired and remove from cache"""
        try:
            with self._internal_lock:
                if self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=f"{tournamentName}:{gamePk}"):
                    self.logger.debug(f"⏰ Expired tournament game {gamePk} for tournament {tournamentName}")
                    return True
                else:
                    self.logger.warning(f"Tournament game {gamePk} not found in cache for tournament {tournamentName}")
                    return False
        except Exception as ex:
            self.logger.error(f"❌ Error expiring tournament game {gamePk} for tournament {tournamentName}:", ex)
            return False
    
    def expire_multiple_referee_games(self, tenantKey: str, refId: str, gamePks: Optional[List[str]] = None) -> Dict[str, bool]:
        """Mark multiple referee games as expired and remove from cache"""
        results = {}
        if gamePks is None:
            # Delete all referee games for this referee
            pattern = f"{self._env}:{tenantKey.replace('#',':')}:{self._cache_prefix}{EntityType.REFEREEGAMES}:{refId}:*"
            keys = self.redis_get_keys(pattern)
            for key in keys:
                self.redis_delete(key)
            self.logger.debug(f"🗑️ Expired all referee games for referee {refId}")
        else:
            for gamePk_item in gamePks:
                results[gamePk_item] = self.expire_referee_game(tenantKey=tenantKey, refId=refId, gamePk=gamePk_item)
        return results
    
    def expire_multiple_referee_reviews(self, tenantKey: str, refId: str, gamePks: Optional[List[str]] = None) -> Dict[str, bool]:
        """Mark multiple referee reviews as expired and remove from cache"""
        results = {}
        if gamePks is None:
            # Delete all referee reviews for this referee
            pattern = f"{self._env}:{tenantKey.replace('#',':')}:{self._cache_prefix}{EntityType.REFEREEREVIEWS}:{refId}:*"
            keys = self.redis_get_keys(pattern)
            for key in keys:
                self.redis_delete(key)
            self.logger.debug(f"🗑️ Expired all referee reviews for referee {refId}")
        else:
            for gamePk in gamePks:
                results[gamePk] = self.expire_referee_review(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
        return results
    
    def get_referee_game_by_pk(self, tenantKey: str, refId: Optional[str] = None, mobileNo: Optional[str] = None, refereeId: Optional[int] = None, gamePk: str = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific referee game by PK"""
        return self.getRefereeGames(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, forceReload=forceReload)

    def get_referee_review_by_pk(self, tenantKey: str, refId: Optional[str] = None, mobileNo: Optional[str] = None, refereeId: Optional[int] = None, gamePk: str = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific referee review by PK"""
        referee_review = self.getRefereeReviews(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, forceReload=forceReload)
        return referee_review
    
    def get_tournament_game_by_pk(self, tenantKey: str, tournamentName: str, gamePk: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific tournament game by PK"""
        tournament_game = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, forceReload=forceReload)
        return tournament_game
    
    def reload_referee_data(self, tenantKey: str, refId: str, gamePk: Optional[str] = None) -> bool:
        """Reload all data for a specific referee and optional game PK"""
        try:
            self.logger.info(f"🔄 Reloading data for referee {refId}" + (f" and game PK {gamePk}" if gamePk else "") + "...")
            with self._internal_lock:
                self._load_referee_games(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
                self._load_referee_reviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
            self.logger.info(f"✅ Referee {refId}" + (f" and game PK {gamePk}" if gamePk else "") + " data reloaded successfully")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error reloading data for referee {refId}" + (f" and game PK {gamePk}" if gamePk else "") + f":", ex)
            return False
    

    def reload_tournament_data(self, tenantKey: str, tournamentName: str, gamePk: Optional[str] = None) -> bool:
        """Reload all data for a specific tournament and optional game PK"""
        try:
            self.logger.info(f"🔄 Reloading data for tournament {tournamentName}" + (f" and game PK {gamePk}" if gamePk else "") + "...")
            with self._internal_lock:
                self._load_tournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
            self.logger.info(f"✅ Tournament {tournamentName}" + (f" and game PK {gamePk}" if gamePk else "") + " data reloaded successfully")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error reloading data for tournament {tournamentName}" + (f" and game PK {gamePk}" if gamePk else "") + f":", ex)
            return False
    
    # Redis cache methods
    def redis_get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis cache (public method)"""
        return self._redis_get(key=key)
    
    def redis_set(self, key: str, data: Dict[str, Any], ttl_seconds: int = 3600) -> bool:
        """Set data in Redis cache with TTL (public method)"""
        return self._redis_set(key=key, data=data, ttl_seconds=ttl_seconds)
    
    def redis_delete(self, key: str) -> bool:
        """Delete data from Redis cache (public method)"""
        return self._redis_delete(key=key)
    
    def redis_exists(self, key: str) -> bool:
        """Check if key exists in Redis cache (public method)"""
        return self._redis_exists(key=key)
    
    def redis_clear_all(self) -> bool:
        """Clear all data from Redis cache"""
        try:
            self.redisCacheClient.flushdb()
            self.logger.debug("🗑️ Cleared all Redis cache data")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error clearing Redis cache:", ex)
            return False
    
    def redis_get_keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching pattern from Redis cache"""
        try:
            keys = self.redisCacheClient.keys(pattern=pattern)
            return keys
        except Exception as ex:#GLOBAL:cache:tenants:AAAA:IL:handball:2024-25
            self.logger.error(f"❌ Error getting keys from Redis with pattern {pattern}:", ex)
            return []
    
    def redis_get_ttl(self, key: str) -> int:
        """Get TTL for a key in Redis cache"""
        try:
            ttl = self.redisCacheClient.ttl(name=key)
            return ttl if ttl is not None else -1   
        except Exception as ex:
            self.logger.error(f"❌ Error getting TTL from Redis for key {key}:", ex)
            return -1
    
    def redis_set_ttl(self, key: str, ttl_seconds: int) -> bool:
        """Set TTL for a key in Redis cache"""
        try:
            return bool(self.redisCacheClient.expire(name=key, time=ttl_seconds))
        except Exception as ex:
            self.logger.error(f"❌ Error setting TTL in Redis for key {key}:", ex)
            return False
    
    # ===== DATABASE CLIENT PROXY METHODS =====
    # These methods proxy all database set/update/delete operations and handle cache invalidation
    
    @cacheDecorator.cache(entityType=EntityType.MEDIAFILEMETADATA, actionType=ActionType.SET)
    def setMediaFileMetadata(self, file_id, metadata):
        """Proxy for dbClient.setMediaFileMetadata with cache invalidation"""
        result = self.dbClient.setMediaFileMetadata(file_id=file_id, metadata=metadata)
        return result
        
    def delete(self, key):
        """Proxy for dbClient.delete with cache invalidation"""
        result = self.dbClient.delete(key)
        return result
    
    def deleteByFilter(self, filter):
        """Proxy for dbClient.deleteByFilter with cache invalidation"""
        result = self.dbClient.deleteByFilter(filters=filter)
        if result:
            # For filter-based deletes, we need to invalidate related cache entries
            self._invalidate_cache_for_filter(filter=filter)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.FIELDS, actionType=ActionType.SET)
    def setField(self, tenantKey, fieldName, value):
        """Proxy for dbClient.setField with cache invalidation"""
        result = self.dbClient.setField(tenantKey=tenantKey, fieldName=fieldName, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.AREAS, actionType=ActionType.SET)
    def setArea(self, areaName, value):
        """Proxy for dbClient.setArea with cache invalidation (global, not tenant-scoped).
        Upserts by area_name (its unique key), matching setField/setDocument/setRule."""
        result = self.dbClient.setArea(areaName=areaName, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.NOTIFICATIONTYPES, actionType=ActionType.SET)
    def setNotificationType(self, typeKey, value):
        """Proxy for dbClient.setNotificationType with cache invalidation (global, not tenant-scoped).
        Upserts by type_key (its unique key), matching setArea."""
        result = self.dbClient.setNotificationType(typeKey=typeKey, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.RULES, actionType=ActionType.SET)
    def setRule(self, tenantKey, ruleName, value):
        """Proxy for dbClient.setRule with cache invalidation"""
        result = self.dbClient.setRule(tenantKey=tenantKey, ruleName=ruleName, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.SEASONS, actionType=ActionType.SET)
    def setSeason(self, season=None):
        """Proxy for dbClient.setSeason with cache invalidation"""
        result = self.dbClient.setSeason(season=season)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.SECTIONS, actionType=ActionType.SET)
    def setSection(self, tenantKey, sectionName, value):
        """Proxy for dbClient.setSection with cache invalidation"""
        result = self.dbClient.setSection(tenantKey=tenantKey, sectionName=sectionName, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTS, actionType=ActionType.SET)
    def setTournament(self, tenantKey, tournamentName, value):
        """Proxy for dbClient.setTournament with cache invalidation"""
        result = self.dbClient.setTournament(tenantKey=tenantKey, tournamentName=tournamentName, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.LEAGUETABLES, actionType=ActionType.SET)
    def setLeagueTable(self, tenantKey, tournamentName, value):
        """Proxy for dbClient.setLeagueTable with cache invalidation"""
        result = self.dbClient.setLeagueTable(tenantKey=tenantKey, tournamentName=tournamentName, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.SET)
    def setTournamentGame(self, tenantKey, tournamentName, gamePk, value, tournamentGameId: Optional[int] = None):
        """Proxy for dbClient.setTournamentGame with cache invalidation"""
        return self.dbClient.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, tournamentGameId=tournamentGameId, value=value)

    @cacheDecorator.cache(entityType=EntityType.REFEREES, actionType=ActionType.SET)
    def setReferee(self, tenantKey, value, mobileNo=None, refereeId=None, **kwargs):
        """Proxy for dbClient.setRefereeProperties with cache invalidation.
        mobileNo is kept only for referees not yet known/created (no refereeId exists yet)."""
        if tenantKey == 'GLOBAL':
            result = self.dbClient.setRefereeProperties(mobileNo=mobileNo, refereeId=refereeId, value=value)
        else:
            result = self.dbClient.setTenantRefereeProperties(tenantKey=tenantKey, mobileNo=mobileNo, refereeId=refereeId, value=value)
        return result

    def setRefereeProperty(self, tenantKey, value, mobileNo=None, refereeId=None, propertyName=None, **kwargs):
        referee = self.getReferees(tenantKey=tenantKey, mobileNo=mobileNo, refereeId=refereeId)
        if not referee:
            return
        if propertyName:
            referee[propertyName.replace(' ', '')] = value
        elif isinstance(value, dict):
            for _propertyName, _value in value.items():
                if _propertyName:
                    referee[_propertyName.replace(' ', '')] = _value
        result = self.setReferee(tenantKey=tenantKey, mobileNo=mobileNo, refereeId=refereeId, value=referee)

    def setCacheOnlyKeyVal(self, **kwargs):
        value = kwargs.pop('value', None)
        ttlSeconds = kwargs.pop('ttlSeconds', 60 * 60 * 24)
        key = self.getCacheOnlyKey(**kwargs)
        if value:
            if not isinstance(value, dict):
                value = {'value': value}
            value = jsonHelper.save_to_json(value)
        result = self.redis_set(key=key, data=value, ttl_seconds=ttlSeconds)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEAVAILABILITY, actionType=ActionType.SET)
    def setRefereeAvailaiblity(self, refereeId: Optional[int] = None, value=None):
        """Proxy for dbClient.setRefereeAvailaiblity with cache invalidation"""
        result = self.dbClient.setRefereeAvailaiblity(refereeId=refereeId, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.CLIENTIDENTIFIERS, actionType=ActionType.SET)
    def setClientIdentifier(self, clientIdentifier, sessionIdentifier, pushSubscription=None, mobileNo=None, refereeId=None, userAgent=None, platform=None, status=None):
        """Proxy for dbClient.setClientIdentifier with cache invalidation"""
        result = self.dbClient.setClientIdentifier(clientIdentifier=clientIdentifier, sessionIdentifier=sessionIdentifier, pushSubscription=pushSubscription, mobileNo=mobileNo, refereeId=refereeId, userAgent=userAgent, platform=platform, status=status)
        return result

    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.SET)
    def deleteTournamentGame(self, tenantKey, tournamentName, gamePk=None, tournamentGameId=None):
        """Proxy for dbClient.deleteTournamentGame with cache invalidation"""
        self.dbClient.deleteTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, tournamentGameId=tournamentGameId)

    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.SET)
    def deleteRefereeGame(self, tenantKey, refId=None, mobileNo=None, refereeId=None, gamePk=None, tournamentGameId=None):
        """Proxy for dbClient.removeRefereeGame with cache invalidation"""
        result = self.dbClient.removeRefereeGame(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, tournamentGameId=tournamentGameId)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.SET)
    def setRefereeReview(self, tenantKey, value, refId=None, mobileNo=None, refereeId=None, gamePk=None, tournamentGameId=None):
        """Proxy for dbClient.setRefereeReview with cache invalidation"""
        result = self.dbClient.setRefereeReview(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, tournamentGameId=tournamentGameId, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.SET)
    def removeRefereeReview(self, tenantKey, refId=None, mobileNo=None, refereeId=None, gamePk=None, tournamentGameId=None):
        """Proxy for dbClient.removeRefereeReview with cache invalidation"""
        result = self.dbClient.removeRefereeReview(tenantKey=tenantKey, refId=refId, mobileNo=mobileNo, refereeId=refereeId, gamePk=gamePk, tournamentGameId=tournamentGameId)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREETEMPLATES, actionType=ActionType.SET)
    def setRefereeTemplate(self, tenantKey, msgSid=None, value=None, refereeId: Optional[int] = None):
        """Proxy for dbClient.setRefereeTemplate with cache invalidation"""
        result = self.dbClient.setRefereeTemplate(tenantKey=tenantKey, msgSid=msgSid, value=value, refereeId=refereeId)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEMESSAGES, actionType=ActionType.SET)
    def setRefereeMessage(self, mobileNo:Optional[str] = None, direction:str = None, msgSid:str = None, value:dict = None, refereeId: Optional[int] = None):
        """Proxy for dbClient.setRefereeMessage with cache invalidation"""
        result = self.dbClient.setRefereeMessage(mobileNo=mobileNo, direction=direction, msgSid=msgSid, value=value, refereeId=refereeId)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.MESSAGES, actionType=ActionType.SET)
    def setMessage(self, msgSid, value):
        """Proxy for dbClient.setMessage with cache invalidation"""
        result = self.dbClient.setMessage(msgSid=msgSid, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.KEYVAL, actionType=ActionType.SET)
    def setKeyVal(self, key, value):
        """Proxy for dbClient.setKeyVal with cache invalidation"""
        result = self.dbClient.setKeyVal(key=key, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.POSITIONUPDATES, actionType=ActionType.SET)
    def setPositionUpdate(self, mobileNo:str, timestamp:str, value:dict):
        result = self.dbClient.setPositionUpdate(mobileNo=mobileNo, timestamp=timestamp, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREELOCATIONS, actionType=ActionType.SET)
    def setRefereeLocation(self, mobileNo:str, timestamp:int, value:dict):
        result = self.dbClient.setRefereeLocation(mobileNo=mobileNo, timestamp=timestamp, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.INVOCATIONS, actionType=ActionType.SET)
    def setInvocation(self, tenantKey, invocationId, value):
        """Proxy for dbClient.setInvocation with cache invalidation"""
        result = self.dbClient.setInvocation(tenantKey=tenantKey, invocationId=invocationId, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.REFERENCEIDS, actionType=ActionType.SET)
    def setReferenceId(self, target: str, target_id: str, value):
        """Proxy for dbClient.setReferenceId with cache invalidation"""
        result = self.dbClient.setReferenceId(target=target, target_id=target_id, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.NOTIFICATIONS, actionType=ActionType.SET)
    def setNotification(self, tenantKey: str, target: str, target_id: int, notificationType:str, target_to, value, **kwargs):
        """Proxy for dbClient.setNotifications with cache invalidation.
        The @cacheDecorator.cache(..., ActionType.SET) wrapper expects (value, invalidated) back
        and, since NOTIFICATIONS has partitionKeys=['target','target_id'], expires the whole
        target:target_id partition on a successful write - so getNotifications() reads no longer
        need forceReload=True to see this write."""
        if isinstance(value, dict):
            value['target_id'] = target_id
            value['target'] = target
            value['notificationType'] = notificationType
            value['tenantKey'] = tenantKey
        result = self.dbClient.setNotifications(tenantKey=tenantKey, target=target, target_id=target_id, notificationType=notificationType, target_to=target_to, value=value)
        return result

    def setCollectedItems(self, tenantKey, objType, mobileNo, value):
        entityType = EntityType.COLLECTEDITEMS
        with self._internal_lock:
            self._redis_cache_set(tenantKey=tenantKey, entityType=entityType, data=value or {}, identifier=f'{objType}:{mobileNo}')

    #@cacheDecorator.cache(entityType=EntityType.COLLECTEDITEMS, actionType=ActionType.COUNT)
    def countCollectedItems(self, tenantKey: str, objType: str) -> int:
        keys = self._redis_cache_get_keys(tenantKey=tenantKey, entityType=EntityType.COLLECTEDITEMS, identifier=f'{objType}:*')
        return len(keys)
    
    def getCollectedItems(self, tenantKey, objType, mobileNo=None) -> dict:
        entityType = EntityType.COLLECTEDITEMS
        with self._internal_lock:
            return self._redis_cache_get(tenantKey=tenantKey, entityType=entityType, identifier=f'{objType}:{mobileNo or "*"}')

    @cacheDecorator.cache(entityType=EntityType.POLLS, actionType=ActionType.GET)
    def getPolls(self, pollId=None) -> dict:
        with self._internal_lock:
            return self.dbClient.getPolls(pollId=pollId)
    
    @cacheDecorator.cache(entityType=EntityType.POLLVOTES, actionType=ActionType.GET)
    def getPollVotes(self, pollId, mobileNo=None, questionId=None) -> dict:
        with self._internal_lock:
            return self.dbClient.getPollVotes(pollId=pollId, mobileNo=mobileNo, questionId=questionId)
    
    @cacheDecorator.cache(entityType=EntityType.POLLS, actionType=ActionType.SET)
    def setPoll(self, pollId, value) -> bool:
        result = self.dbClient.setPoll(pollId=pollId, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.POLLVOTES, actionType=ActionType.SET)
    def setPollVote(self, pollId, mobileNo, questionId, value) -> bool:
        result = self.dbClient.setPollVote(pollId=pollId, mobileNo=mobileNo, questionId=questionId, value=value)
        return result

if __name__ == '__main__':
    from shared.appContainer import AppContainer
    import shared.configurationDI as configDI
    container = AppContainer()
    container.config.from_dict(configDI.configDI)
    container.init_resources()    

    #service = MessagingService(logger=logging.getLogger(), cacheService=cacheService, refereesByMobile={'+972547799979': {'name': 'Guy', 'mobileNo': '+972547799979'}}, activeClient='meta', metaClient=MetaClient(logger=logging.getLogger(), cacheService=cacheService, fromMobile='+972547799979', useClient=True, apiVersion='v24.0', fromPhoneNumberId='120702945000013', whatsappBusinessAccountId='120702945000013'))
    cacheService = container.cache_service()
    multiTenantSupport = container.multi_tenant_support()

    exit(0)