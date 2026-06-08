from select import poll
import threading
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Callable, Tuple, TYPE_CHECKING
from urllib.parse import quote, unquote
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
from shared.enumTypes import EntityType, ActionType

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
        key = f"{tenantKey.replace('#',':')}:{self._cache_prefix}{entityType}"
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
        key = f"{tenantKey.replace('#',':')}:{self._cache_ttl_prefix}{entityType}"
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
            referee_games_keys = self.redis_get_keys(f"*:{self._cache_prefix}refereeGames:*")
            for key in referee_games_keys:
                self.redis_delete(key)
            
            # Get all referee reviews keys
            referee_reviews_keys = self.redis_get_keys(f"*:{self._cache_prefix}refereeReviews:*")
            for key in referee_reviews_keys:
                self.redis_delete(key)
            
            # Get all tournament games keys
            tournament_games_keys = self.redis_get_keys(f"*:{self._cache_prefix}tournamentGames:*")
            for key in tournament_games_keys:
                self.redis_delete(key)
            
            # Get all game detail mappings
            game_detail_keys = self.redis_get_keys(f"*:{self._cache_prefix}gameDetailId:*")
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
    
    def _invalidate_cache_for_gamePk(self, gamePk: str) -> None:
        """Invalidate cache entries for a specific game PK"""
        try:
            # Find and invalidate all cache entries related to this game PK
            patterns = [
                f"{self._cache_prefix}{EntityType.REFEREEGAMES}:*:{gamePk}",
                f"{self._cache_prefix}{EntityType.REFEREEREVIEWS}:*:{gamePk}",
                f"{self._cache_prefix}{EntityType.TOURNAMENTSGAMES}:*:{gamePk}"
            ]
            
            for pattern in patterns:
                keys = self.redis_get_keys(pattern)
                for key in keys:
                    self.redis_delete(key)
            
            self.logger.debug(f"🔄 Invalidated cache entries for game PK {gamePk}")
        except Exception as ex:
            self.logger.error(f"❌ Error invalidating cache for game PK {gamePk}:", ex)

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
            refereesGlobal = self.dbClient.getRefereeProperties(tenantKey='GLOBAL')
            referees['GLOBAL'] = refereesGlobal
            i = 0
            cacheItems = []
            for mobileNo, referee in refereesGlobal.items():
                i += 1
                value = {
                    'value': referee,
                    'filters': {}
                }
                
                cacheKey = self._get_cache_key(tenantKey='GLOBAL', entityType=EntityType.REFEREES, identifier=f'{mobileNo}:AAA')
                ttl_seconds = DbClientBase.CacheTypes.get(EntityType.REFEREES, {}).get('ttl', 3600)
                
                cacheItems.append({'key': cacheKey, 'value': value, 'ttl_seconds': ttl_seconds})
            
            self._redis_set_batch(items=cacheItems)

            tenants = self.getTenants()
            for tenantKey, tenant in tenants.items():
                cacheItems = []
                tenantReferees = self.dbClient.getRefereeProperties(tenantKey=tenantKey)
                referees[tenantKey] = tenantReferees

                i = 0
                for mobileNo, tenantReferee in tenantReferees.items():
                    i += 1
                    refereeDetail = helpers.merge_nested_dicts(refereesGlobal.get(mobileNo, {}), tenantReferee)
                    value = {
                        'value': refereeDetail,
                        'filters': {}
                    }

                    cacheKey = self._get_cache_key(tenantKey=tenantKey, entityType=EntityType.REFEREES, identifier=f'{mobileNo}:AAAA')      
                    cacheItems.append({'key': cacheKey, 'value': value, 'ttl_seconds': ttl_seconds})
            
                self._redis_set_batch(items=cacheItems)

            self.logger.debug(f"👥 Loaded {len(refereesGlobal)} referees")

            return referees
        except Exception as ex:
            self.logger.error(f"Error loading referees:", ex)
    
    def _load_referee_games(self, tenantKey: str, refId: str, gamePk: Optional[str] = None, include_archived: bool = False, include_removed: bool = False, include_canceled: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None):
        """Load referee games data from database by referee ID and optional game PK"""
        try:
            referee_games = self.dbClient.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=gamePk, includeArchived=include_archived, includeRemoved=include_removed, includeCanceled=include_canceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
            for gamePk, referee_game in referee_games.items():
                # Store each game individually in Redis
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, data=referee_game or {}, identifier=f"{refId}:{gamePk}")
            self.logger.info(f"✅ Loaded {len(referee_games)} referee games for referee {refId}" + (f" and game {gamePk}" if gamePk else ""))
            return referee_games.keys()
        except Exception as ex:
            self.logger.error(f"Error loading referee games for {refId}" + (f" and game {gamePk}" if gamePk else "") + f":", ex)
            if gamePk:
                self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=refId, keys=gamePk)

    def _load_referee_games_new(self, tenantKey: str, mobileNo: str, gamePk: Optional[str] = None, include_archived: bool = False, include_removed: bool = False, include_canceled: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None):
        """Load referee games data from database by referee ID and optional game PK"""
        try:
            referee_games = self.dbClient.getRefereeGamesNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, includeArchived=include_archived, includeRemoved=include_removed, includeCanceled=include_canceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
            for gamePk, referee_game in referee_games.items():
                # Store each game individually in Redis
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, data=referee_game or {}, identifier=f"{mobileNo}:{gamePk}")
            self.logger.info(f"✅ Loaded {len(referee_games)} referee games for referee {mobileNo}" + (f" and game {gamePk}" if gamePk else ""))
            return referee_games.keys()
        except Exception as ex:
            self.logger.error(f"Error loading referee games for {mobileNo}" + (f" and game {gamePk}" if gamePk else "") + f":", ex)
            if gamePk:
                self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=mobileNo, keys=gamePk)
        
    def _load_referee_reviews(self, tenantKey: str, refId: str, gamePk: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None):
        """Load referee reviews data from database by referee ID and optional game PK"""
        try:
            referee_reviews = self.dbClient.getRefereeReviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk, from_date=from_date, to_date=to_date)
            for gamePk, referee_review in referee_reviews.items():
                # Store each review individually in Redis
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, data=referee_review or {}, identifier=f"{refId}:{gamePk}")
            self.logger.info(f"✅ Loaded {len(referee_reviews)} referee reviews for referee {refId}" + (f" and game {gamePk}" if gamePk else ""))
            return referee_reviews.keys()
        except Exception as ex:
            self.logger.error(f"Error loading referee reviews for {refId}" + (f" and game {gamePk}" if gamePk else "") + f":", ex)
            if gamePk:
                self._redis_cache_delete(entityType=EntityType.REFEREEREVIEWS, identifier=refId, keys=gamePk)

    def _load_referee_reviews_new(self, tenantKey: str, mobileNo: str, gamePk: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None):
        """Load referee reviews data from database by referee ID and optional game PK"""
        try:
            referee_reviews = self.dbClient.getRefereeReviewsNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, from_date=from_date, to_date=to_date)
            for gamePk, referee_review in referee_reviews.items():
                # Store each review individually in Redis
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, data=referee_review or {}, identifier=f"{mobileNo}:{gamePk}")
            self.logger.info(f"✅ Loaded {len(referee_reviews)} referee reviews for referee {mobileNo}" + (f" and game {gamePk}" if gamePk else ""))
            return referee_reviews.keys()
        except Exception as ex:
            self.logger.error(f"Error loading referee reviews for {mobileNo}" + (f" and game {gamePk}" if gamePk else "") + f":", ex)
            if gamePk:
                self._redis_cache_delete(entityType=EntityType.REFEREEREVIEWS, identifier=mobileNo, keys=gamePk)

    def _load_tournamentGames(self, tenantKey: str, tournamentName: str, gamePk: Optional[str] = None, nonArchivedOnly: bool = False, filters: list = []):
        """Load tournament games data from database by tournament name and optional game PK"""
        try:
            result = self.dbClient.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, nonArchivedOnly=nonArchivedOnly, filters=filters)
            if not result:
                return {}
            #self.multiTenantSupport.mapList(objType='games', refereeItems=result)
            tournamentGames = result
            for _gamePk, _tournamentGame in tournamentGames.items():
                # Store each game individually in Redis
                _tournamentName = _tournamentGame.get('tournamentName')
                self._redis_cache_set(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, data=_tournamentGame or {}, identifier=f"{_tournamentName}:{_gamePk}")
                
                # Store game detail mapping
                if False and _tournamentGame and _tournamentGame.get("id"):
                    self._redis_cache_set(tenantKey='GLOBAL', entityType='gameDetailId', data=_tournamentGame, identifier=str(_tournamentGame.get("id")))
                    #self._redis_cache_set(tenantKey='GLOBAL', entityType='gameDetailId', data={"tenantKey": tenantKey, "tournamentName": tournamentName, "gamePk": gamePk}, identifier=str(tournamentGame.get("id")))
            self.logger.info(f"✅ Loaded {len(tournamentGames)} tournament games for tournament {tournamentName}" + (f" and game PK {gamePk}" if gamePk else ""))
            if not gamePk:
                try:
                    tournament = self.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
                    section = (tournament or {}).get('section', '')
                    self._store_tournament_games_index(
                        tenantKey=tenantKey,
                        tournamentName=tournamentName,
                        games=tournamentGames,
                        section=section,
                    )
                except Exception as ex:
                    self.logger.error(f"Error building tournament games index for {tournamentName}:", ex)
            return tournamentGames
        except Exception as ex:
            self.logger.error(f"Error loading tournament games for {tournamentName}" + (f" and game PK {gamePk}" if gamePk else "") + f":", ex)
            if gamePk:
                self._redis_cache_delete(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=tournamentName, keys=gamePk)

    def _norm_phone_index(self, phone) -> str:
        return ''.join(c for c in str(phone or '') if c.isdigit())

    def _raw_referees_for_index(self, gameDetail: dict) -> list:
        arr = gameDetail.get('referees')
        if isinstance(arr, list) and arr:
            return arr
        nested = gameDetail.get('nested') or {}
        if isinstance(nested, dict) and nested:
            return list(nested.values())
        return []

    def _ref_phone_index(self, ref) -> str:
        if not isinstance(ref, dict):
            return ''
        return str(ref.get('* phone') or ref.get('phone') or ref.get('mobileNo') or '').strip()

    def _ref_name_index(self, ref) -> str:
        if not isinstance(ref, dict):
            return ''
        return str(ref.get('* name') or ref.get('name') or '').strip()

    def _build_tournament_game_index_entry(self, gameDetail: dict, section: str = '') -> Optional[dict]:
        if not isinstance(gameDetail, dict):
            return None
        state = str(gameDetail.get('state') or '').lower()
        if state in ('removed', 'canceled'):
            return None
        gamePk = str(gameDetail.get('gamePk') or '').strip()
        if not gamePk:
            return None
        game_date = gameDetail.get('date') or gameDetail.get('gameDate') or gameDetail.get('scheduledDate')
        scheduled = gameDetail.get('scheduledDate') or gameDetail.get('dateTime') or gameDetail.get('date')
        fd = gameDetail.get('fieldData')
        fd = fd if isinstance(fd, dict) else {}
        addr_raw = fd.get('addressDetails')
        addr = addr_raw if isinstance(addr_raw, dict) else {}
        field_blob = ' '.join(
            str(x)
            for x in (
                gameDetail.get('field'),
                gameDetail.get('fieldName'),
                fd.get('name'),
                addr.get('address'),
            )
            if x
        )
        field_label = str(gameDetail.get('field') or gameDetail.get('fieldName') or fd.get('name') or '').strip().lower()
        date_day = str(game_date)[:10] if game_date else ''
        referee_phones = []
        referee_names = []
        for ref in self._raw_referees_for_index(gameDetail):
            phone = self._norm_phone_index(self._ref_phone_index(ref))
            if phone:
                referee_phones.append(phone)
            name = self._ref_name_index(ref).lower()
            if name:
                referee_names.append(name)
        return {
            'gamePk': gamePk,
            'tournamentName': gameDetail.get('tournamentName') or '',
            'section': section or '',
            'date': str(game_date) if game_date else '',
            'scheduledDate': str(scheduled) if scheduled else '',
            'fieldBlob': field_blob.lower(),
            'fieldLabel': field_label,
            'dateDay': date_day,
            'refereePhones': referee_phones,
            'refereeNames': referee_names,
        }

    _TOURNAMENT_GAMES_INDEX_TTL_SECONDS = 60 * 60

    def _tournament_games_index_cache_kwargs(self, tenantKey: str, tournamentName: str) -> dict:
        return {
            'tenantKey': tenantKey,
            'entityType': EntityType.TOURNAMENTSGAMESINDEX,
            'tournamentName': tournamentName,
        }

    def _tournament_games_index_redis_key(self, tenantKey: str, tournamentName: str) -> str:
        return self.getCachedKey(**self._tournament_games_index_cache_kwargs(tenantKey, tournamentName))

    def _tournament_games_index_cache_exists(self, tenantKey: str, tournamentName: str) -> bool:
        return self._redis_exists(self._tournament_games_index_redis_key(tenantKey=tenantKey, tournamentName=tournamentName))

    def _get_tournament_games_index_cache(self, tenantKey: str, tournamentName: str) -> Optional[dict]:
        if not self._tournament_games_index_cache_exists(tenantKey=tenantKey, tournamentName=tournamentName):
            return None
        data = self._redis_get(self._tournament_games_index_redis_key(tenantKey=tenantKey, tournamentName=tournamentName))
        return data if isinstance(data, dict) else {}

    def _set_tournament_games_index_cache(self, tenantKey: str, tournamentName: str, index: dict) -> bool:
        stored = self._redis_set(
            key=self._tournament_games_index_redis_key(tenantKey=tenantKey, tournamentName=tournamentName),
            data=index or {},
            ttl_seconds=self._TOURNAMENT_GAMES_INDEX_TTL_SECONDS,
        )
        if stored:
            self._sync_tournament_field_date_lookup_indexes(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
                index=index or {},
            )
        return stored

    def _lookup_index_segment(self, value: str) -> str:
        return quote(str(value or '').strip().lower(), safe='')

    def _field_lookup_index_redis_key(self, tenantKey: str, tournamentName: str, fieldKey: str) -> str:
        return self.getCachedKey(
            tenantKey=tenantKey,
            entityType=EntityType.TOURNAMENTSGAMESINDEXBYFIELD,
            tournamentName=tournamentName,
            fieldKey=self._lookup_index_segment(fieldKey),
        )

    def _date_lookup_index_redis_key(self, tenantKey: str, tournamentName: str, dateDay: str) -> str:
        return self.getCachedKey(
            tenantKey=tenantKey,
            entityType=EntityType.TOURNAMENTSGAMESINDEXBYDATE,
            tournamentName=tournamentName,
            dateDay=str(dateDay or '')[:10],
        )

    def _tournament_field_date_lookup_pattern(self, tenantKey: str, entityType: EntityType, tournamentName: str) -> str:
        tenant_prefix = tenantKey.replace('#', ':')
        return f"{tenant_prefix}:cacheOnly:{entityType}:{tournamentName}:*"

    def _expire_tournament_field_date_lookup_keys(self, tenantKey: str, tournamentName: str) -> None:
        for entityType in (
            EntityType.TOURNAMENTSGAMESINDEXBYFIELD,
            EntityType.TOURNAMENTSGAMESINDEXBYDATE,
        ):
            pattern = self._tournament_field_date_lookup_pattern(
                tenantKey=tenantKey,
                entityType=entityType,
                tournamentName=tournamentName,
            )
            for key in self.redis_get_keys(pattern=pattern):
                self.redis_delete(key)

    def _set_field_date_lookup_pks(self, redis_key: str, pks: list) -> bool:
        return self._redis_set(
            key=redis_key,
            data=sorted(set(str(pk) for pk in (pks or []))),
            ttl_seconds=self._TOURNAMENT_GAMES_INDEX_TTL_SECONDS,
        )

    def _collect_field_date_lookup_entries(self, index: dict) -> tuple:
        field_pks = {}
        date_pks = {}
        for gamePk, entry in (index or {}).items():
            game_pk = str(gamePk)
            field_label = (entry.get('fieldLabel') or '').strip().lower()
            if field_label:
                field_pks.setdefault(field_label, []).append(game_pk)
            field_blob = (entry.get('fieldBlob') or '').strip().lower()
            if field_blob and field_blob != field_label:
                field_pks.setdefault(field_blob, []).append(game_pk)
            date_day = (entry.get('dateDay') or '')[:10]
            if date_day:
                date_pks.setdefault(date_day, []).append(game_pk)
        return field_pks, date_pks

    def _sync_tournament_field_date_lookup_indexes(
        self,
        tenantKey: str,
        tournamentName: str,
        index: dict,
        expire_query_cache: bool = True,
    ) -> None:
        self._expire_tournament_field_date_lookup_keys(tenantKey=tenantKey, tournamentName=tournamentName)
        field_pks, date_pks = self._collect_field_date_lookup_entries(index=index)
        for field_key, pks in field_pks.items():
            self._set_field_date_lookup_pks(
                redis_key=self._field_lookup_index_redis_key(
                    tenantKey=tenantKey,
                    tournamentName=tournamentName,
                    fieldKey=field_key,
                ),
                pks=pks,
            )
        for date_day, pks in date_pks.items():
            self._set_field_date_lookup_pks(
                redis_key=self._date_lookup_index_redis_key(
                    tenantKey=tenantKey,
                    tournamentName=tournamentName,
                    dateDay=date_day,
                ),
                pks=pks,
            )
        if expire_query_cache:
            self.expire_tournament_games_query_cache(tenantKey=tenantKey)

    def _rebuild_tournament_field_date_lookup_indexes(self, tenantKey: str, tournamentName: str) -> None:
        index = self.getTournamentGamesIndex(
            tenantKey=tenantKey,
            tournamentName=tournamentName,
            forceReload=False,
        )
        self._sync_tournament_field_date_lookup_indexes(
            tenantKey=tenantKey,
            tournamentName=tournamentName,
            index=index,
            expire_query_cache=False,
        )

    def _rebuild_tenant_field_date_lookup_indexes(self, tenantKey: str, tournamentNames: list) -> None:
        for tournamentName in tournamentNames or []:
            self._rebuild_tournament_field_date_lookup_indexes(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
            )

    def _field_key_from_lookup_redis_key(self, redis_key: str) -> str:
        field_segment = redis_key.rsplit(':', 1)[-1]
        return unquote(field_segment).lower()

    def _ensure_tournament_field_lookup_indexes(self, tenantKey: str, tournamentName: str) -> None:
        pattern = self._tournament_field_date_lookup_pattern(
            tenantKey=tenantKey,
            entityType=EntityType.TOURNAMENTSGAMESINDEXBYFIELD,
            tournamentName=tournamentName,
        )
        if not self.redis_get_keys(pattern=pattern):
            self._rebuild_tournament_field_date_lookup_indexes(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
            )

    def _ensure_tournament_date_lookup_indexes(self, tenantKey: str, tournamentName: str, days: list) -> None:
        if not days:
            return
        missing = any(
            not self._redis_exists(
                self._date_lookup_index_redis_key(
                    tenantKey=tenantKey,
                    tournamentName=tournamentName,
                    dateDay=day,
                )
            )
            for day in days
        )
        if missing and self._get_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName) is not None:
            self._rebuild_tournament_field_date_lookup_indexes(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
            )

    def _normalize_query_cache_date(self, dt: datetime = None) -> str:
        if not dt:
            return ''
        try:
            return dt.date().isoformat()
        except Exception:
            return str(dt)[:10]

    def _normalize_game_pk_list(self, gamePk) -> list:
        if gamePk is None:
            return []
        if isinstance(gamePk, (set, list, tuple)):
            items = gamePk
        else:
            items = [gamePk]
        return sorted({str(pk).strip() for pk in items if pk is not None and str(pk).strip()})

    def _get_cached_tournament_games_by_pk(self, tenantKey: str, tournamentName: str, pk_list: list) -> tuple:
        games = {}
        missing = []
        if not pk_list:
            return games, missing
        redis_keys = []
        pk_by_redis_key = {}
        for pk in pk_list:
            cache_key = self._get_cache_key(
                tenantKey=tenantKey,
                entityType=EntityType.TOURNAMENTSGAMES,
                identifier=f"{tournamentName}:{pk}",
            )
            redis_keys.append(cache_key)
            pk_by_redis_key[cache_key] = pk
        batch = self._redis_get_batch(redis_keys)
        for cache_key, pk in pk_by_redis_key.items():
            data = batch.get(cache_key)
            if isinstance(data, dict) and data:
                games[str(pk)] = data
            else:
                missing.append(str(pk))
        return games, missing

    def _tournament_games_query_cache_hash(
        self,
        tournamentNames: list,
        leagueName: str = None,
        sectionFilter: str = None,
        fromDate: datetime = None,
        toDate: datetime = None,
        fieldFilter: str = None,
        refereeFilter: str = None,
    ) -> str:
        payload = {
            'leagueName': leagueName or '',
            'sectionFilter': sectionFilter or '',
            'fromDate': self._normalize_query_cache_date(fromDate),
            'toDate': self._normalize_query_cache_date(toDate),
            'fieldFilter': (fieldFilter or '').strip().lower(),
            'refereeFilter': (refereeFilter or '').strip().lower(),
            'tournamentNames': sorted(tournamentNames or []),
        }
        return hashlib.md5(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()

    def _tournament_games_query_cache_redis_key(self, tenantKey: str, query_hash: str) -> str:
        return self.getCachedKey(
            tenantKey=tenantKey,
            entityType=EntityType.TOURNAMENTSGAMESINDEXQUERY,
            queryHash=query_hash,
        )

    def _get_tournament_games_query_cache(self, tenantKey: str, query_hash: str) -> Optional[dict]:
        key = self._tournament_games_query_cache_redis_key(tenantKey=tenantKey, query_hash=query_hash)
        if not self._redis_exists(key):
            return None
        data = self._redis_get(key)
        if not isinstance(data, dict):
            return None
        return {
            tournamentName: set(str(pk) for pk in (pks or []))
            for tournamentName, pks in data.items()
        }

    def _set_tournament_games_query_cache(self, tenantKey: str, query_hash: str, matches: dict) -> bool:
        payload = {
            tournamentName: sorted(set(str(pk) for pk in pks))
            for tournamentName, pks in (matches or {}).items()
        }
        return self._redis_set(
            key=self._tournament_games_query_cache_redis_key(tenantKey=tenantKey, query_hash=query_hash),
            data=payload,
            ttl_seconds=self._TOURNAMENT_GAMES_INDEX_TTL_SECONDS,
        )

    def expire_tournament_games_query_cache(self, tenantKey: str) -> bool:
        try:
            pattern = f"{tenantKey.replace('#', ':')}:cacheOnly:{EntityType.TOURNAMENTSGAMESINDEXQUERY}:*"
            keys = self.redis_get_keys(pattern=pattern)
            for key in keys:
                self.redis_delete(key)
            return True
        except Exception as ex:
            self.logger.error(f"Error expiring tournament games query cache tenantKey={tenantKey}:", ex)
            return False

    def _days_in_date_range(self, fromDate: datetime = None, toDate: datetime = None) -> list:
        if not fromDate and not toDate:
            return []
        start = (fromDate or toDate).date()
        end = (toDate or fromDate).date()
        if end < start:
            start, end = end, start
        days = []
        current = start
        while current <= end:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _are_tournament_games_indexes_cached(self, tenantKey: str, tournamentNames: list) -> bool:
        return all(
            self._tournament_games_index_cache_exists(tenantKey=tenantKey, tournamentName=tournamentName)
            for tournamentName in (tournamentNames or [])
        )

    def _query_tournament_games_from_field_date_indexes(
        self,
        tenantKey: str,
        tournamentNames: list,
        fromDate: datetime = None,
        toDate: datetime = None,
        fieldFilter: str = None,
    ) -> Optional[dict]:
        if not fieldFilter and not fromDate and not toDate:
            return None
        if not tournamentNames:
            return {}
        if not self._are_tournament_games_indexes_cached(tenantKey=tenantKey, tournamentNames=tournamentNames):
            return None

        indexes = self.getTournamentGamesIndexes(
            tenantKey=tenantKey,
            tournamentNames=tournamentNames,
            forceReload=False,
        )
        return {
            tournamentName: self._filter_tournament_games_index(
                index=indexes.get(tournamentName) or {},
                fromDate=fromDate,
                toDate=toDate,
                fieldFilter=fieldFilter,
            )
            for tournamentName in tournamentNames
        }

    def _delete_tournament_games_index_cache(self, tenantKey: str, tournamentName: str) -> bool:
        key = self.getCachedKey(**self._tournament_games_index_cache_kwargs(tenantKey, tournamentName))
        return self._redis_delete(key)

    def _store_tournament_games_index(self, tenantKey: str, tournamentName: str, games: dict, section: str = '') -> dict:
        index = {}
        for _gamePk, gameDetail in (games or {}).items():
            entry = self._build_tournament_game_index_entry(gameDetail=gameDetail, section=section)
            if entry:
                index[str(_gamePk)] = entry
        self._set_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName, index=index)
        return index

    def _upsert_tournament_games_index_entry(self, tenantKey: str, tournamentName: str, gameDetail: dict, section: str = '') -> None:
        index = self._get_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName)
        if index is None:
            index = {}
        gamePk = str((gameDetail or {}).get('gamePk') or '').strip()
        if not gamePk:
            return
        entry = self._build_tournament_game_index_entry(gameDetail=gameDetail, section=section)
        if entry:
            index[gamePk] = entry
        elif gamePk in index:
            del index[gamePk]
        self._set_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName, index=index)

    def _remove_tournament_games_index_entry(self, tenantKey: str, tournamentName: str, gamePk: str) -> None:
        index = self._get_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName)
        if index is None:
            return
        gamePk = str(gamePk or '').strip()
        if gamePk and gamePk in index:
            del index[gamePk]
            self._set_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName, index=index)

    def expire_tournament_games_index(self, tenantKey: str, tournamentName: str = None) -> bool:
        try:
            if tournamentName:
                deleted = self._delete_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName)
                self._sync_tournament_field_date_lookup_indexes(tenantKey=tenantKey, tournamentName=tournamentName, index={})
                return deleted
            pattern = f"{tenantKey.replace('#', ':')}:cacheOnly:{EntityType.TOURNAMENTSGAMESINDEX}:*"
            keys = self.redis_get_keys(pattern=pattern)
            for key in keys:
                self.redis_delete(key)
            for entityType in (
                EntityType.TOURNAMENTSGAMESINDEXBYFIELD,
                EntityType.TOURNAMENTSGAMESINDEXBYDATE,
            ):
                lookup_pattern = f"{tenantKey.replace('#', ':')}:cacheOnly:{entityType}:*"
                for key in self.redis_get_keys(pattern=lookup_pattern):
                    self.redis_delete(key)
            self.expire_tournament_games_query_cache(tenantKey=tenantKey)
            return True
        except Exception as ex:
            self.logger.error(f"Error expiring tournament games index tenantKey={tenantKey} tournamentName={tournamentName}:", ex)
            return False

    def getTournamentGamesIndex(self, tenantKey: str, tournamentName: str, forceReload: bool = False) -> dict:
        if not forceReload:
            cached = self._get_tournament_games_index_cache(tenantKey=tenantKey, tournamentName=tournamentName)
            if cached is not None:
                return cached
        games = self.dbClient.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName) or {}
        tournament = self.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
        section = (tournament or {}).get('section', '')
        return self._store_tournament_games_index(
            tenantKey=tenantKey,
            tournamentName=tournamentName,
            games=games,
            section=section,
        )

    def getTournamentGamesIndexes(self, tenantKey: str, tournamentNames: list, forceReload: bool = False) -> dict:
        """Load tournament game indexes for many tournaments (one Redis MGET when cached)."""
        indexes = {}
        if not tournamentNames:
            return indexes
        if not forceReload:
            redis_keys = []
            key_to_name = {}
            for tournamentName in tournamentNames:
                cache_key = self._tournament_games_index_redis_key(tenantKey=tenantKey, tournamentName=tournamentName)
                redis_keys.append(cache_key)
                key_to_name[cache_key] = tournamentName
            batch = self._redis_get_batch(redis_keys)
            missing_names = []
            for cache_key, tournamentName in key_to_name.items():
                cached = batch.get(cache_key)
                if cached is None:
                    missing_names.append(tournamentName)
                else:
                    indexes[tournamentName] = cached if isinstance(cached, dict) else {}
            for tournamentName in missing_names:
                indexes[tournamentName] = self.getTournamentGamesIndex(
                    tenantKey=tenantKey,
                    tournamentName=tournamentName,
                    forceReload=False,
                )
            return indexes
        for tournamentName in tournamentNames:
            indexes[tournamentName] = self.getTournamentGamesIndex(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
                forceReload=True,
            )
        return indexes

    def _parse_index_datetime(self, value) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _filter_tournament_games_index(
        self,
        index: dict,
        sectionFilter: str = None,
        fromDate: datetime = None,
        toDate: datetime = None,
        fieldFilter: str = None,
        refereeMobileFilter: str = None,
        refereeFilter: str = None,
        now: datetime = None,
    ) -> set:
        if sectionFilter:
            index = {
                gamePk: entry
                for gamePk, entry in (index or {}).items()
                if (entry.get('section') or '') == sectionFilter
            }
        else:
            index = index or {}
        from_dt = fromDate.replace(tzinfo=timezone.utc) if fromDate else None
        to_dt = toDate.replace(tzinfo=timezone.utc) if toDate else None
        field_q = (fieldFilter or '').strip().lower()
        referee_mobile_digits = self._norm_phone_index(refereeMobileFilter) if refereeMobileFilter else ''
        referee_q = (refereeFilter or '').strip().lower()
        now_dt = now or datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        matched = set()
        for gamePk, entry in index.items():
            if from_dt or to_dt:
                gdt = self._parse_index_datetime(entry.get('date'))
                if not gdt:
                    continue
                if from_dt and gdt < from_dt:
                    continue
                if to_dt and gdt > to_dt:
                    continue
            if field_q and field_q not in (entry.get('fieldBlob') or ''):
                continue
            if referee_mobile_digits or referee_q:
                started_dt = self._parse_index_datetime(entry.get('scheduledDate') or entry.get('date'))
                game_started = bool(started_dt and started_dt <= now_dt)
                if not game_started:
                    continue
                if referee_mobile_digits:
                    phones = entry.get('refereePhones') or []
                    if not any(
                        phone == referee_mobile_digits or phone.endswith(referee_mobile_digits)
                        for phone in phones
                    ):
                        continue
                elif referee_q:
                    names = entry.get('refereeNames') or []
                    if not any(referee_q in name for name in names):
                        continue
            matched.add(str(gamePk))
        return matched

    def queryTenantTournamentGamesIndex(
        self,
        tenantKey: str,
        tournamentNames: list,
        leagueName: str = None,
        sectionFilter: str = None,
        fromDate: datetime = None,
        toDate: datetime = None,
        fieldFilter: str = None,
        refereeMobileFilter: str = None,
        refereeFilter: str = None,
        now: datetime = None,
        forceReload: bool = False,
    ) -> Optional[dict]:
        """Return {tournamentName: {gamePk, ...}} using cacheOnly field/date indexes and query cache."""
        try:
            query_hash = None
            if not forceReload and not refereeMobileFilter:
                query_hash = self._tournament_games_query_cache_hash(
                    tournamentNames=tournamentNames,
                    leagueName=leagueName,
                    sectionFilter=sectionFilter,
                    fromDate=fromDate,
                    toDate=toDate,
                    fieldFilter=fieldFilter,
                    refereeFilter=refereeFilter,
                )
                cached_query = self._get_tournament_games_query_cache(tenantKey=tenantKey, query_hash=query_hash)
                if cached_query is not None:
                    return cached_query

            lookup_matches = None
            if not forceReload and (fieldFilter or fromDate or toDate):
                lookup_matches = self._query_tournament_games_from_field_date_indexes(
                    tenantKey=tenantKey,
                    tournamentNames=tournamentNames,
                    fromDate=fromDate,
                    toDate=toDate,
                    fieldFilter=fieldFilter,
                )

            needs_index_entries = bool(sectionFilter or refereeFilter or refereeMobileFilter)
            indexes = None
            if lookup_matches is None or needs_index_entries:
                indexes = self.getTournamentGamesIndexes(
                    tenantKey=tenantKey,
                    tournamentNames=tournamentNames,
                    forceReload=forceReload,
                )

            if lookup_matches is not None:
                result = {}
                for tournamentName in tournamentNames:
                    candidate_pks = lookup_matches.get(tournamentName, set())
                    if needs_index_entries:
                        index_slice = {
                            gamePk: entry
                            for gamePk, entry in (indexes.get(tournamentName) or {}).items()
                            if str(gamePk) in candidate_pks
                        }
                        result[tournamentName] = self._filter_tournament_games_index(
                            index=index_slice,
                            sectionFilter=sectionFilter,
                            fromDate=None,
                            toDate=None,
                            fieldFilter=None,
                            refereeMobileFilter=refereeMobileFilter,
                            refereeFilter=refereeFilter,
                            now=now,
                        )
                    else:
                        result[tournamentName] = set(str(pk) for pk in candidate_pks)
            else:
                result = {
                    tournamentName: self._filter_tournament_games_index(
                        index=indexes.get(tournamentName) or {},
                        sectionFilter=sectionFilter,
                        fromDate=fromDate,
                        toDate=toDate,
                        fieldFilter=fieldFilter,
                        refereeMobileFilter=refereeMobileFilter,
                        refereeFilter=refereeFilter,
                        now=now,
                    )
                    for tournamentName in tournamentNames
                }

            if query_hash is not None:
                self._set_tournament_games_query_cache(
                    tenantKey=tenantKey,
                    query_hash=query_hash,
                    matches=result,
                )
            return result
        except Exception as ex:
            self.logger.error(f"queryTenantTournamentGamesIndex failed tenantKey={tenantKey}:", ex)
            return None

    def queryTournamentGamesIndex(
        self,
        tenantKey: str,
        tournamentName: str,
        sectionFilter: str = None,
        fromDate: datetime = None,
        toDate: datetime = None,
        fieldFilter: str = None,
        refereeMobileFilter: str = None,
        refereeFilter: str = None,
        now: datetime = None,
        forceReload: bool = False,
    ) -> Optional[set]:
        """Return matching gamePk values for a tournament using the lightweight index cache."""
        try:
            batch = self.queryTenantTournamentGamesIndex(
                tenantKey=tenantKey,
                tournamentNames=[tournamentName],
                sectionFilter=sectionFilter,
                fromDate=fromDate,
                toDate=toDate,
                fieldFilter=fieldFilter,
                refereeMobileFilter=refereeMobileFilter,
                refereeFilter=refereeFilter,
                now=now,
                forceReload=forceReload,
            )
            if batch is None:
                return None
            return batch.get(tournamentName, set())
        except Exception as ex:
            self.logger.error(
                f"queryTournamentGamesIndex failed tenantKey={tenantKey} tournamentName={tournamentName}:",
                ex,
            )
            return None
    
    # Public access methods
    @cacheDecorator.cache(entityType=EntityType.FIELDS, actionType=ActionType.GET)
    def getFields(self, tenantKey: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get fields data from cache"""
        with self._internal_lock:
            return self.dbClient.getFields(tenantKey=tenantKey)
    
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
    
    #@cacheDecorator.cache(entityType=EntityType.REFEREES, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getRefereesNoCache(self) -> Dict[str, Any]:
        """Get referees data from cache"""
        with self._internal_lock:
            tenants = self.getTenants()
            referees = {}
            referees['GLOBAL'] = self.getReferees(tenantKey='GLOBAL', forceReload=True)
            for tenantKey, tenant in tenants.items():
                referees[tenantKey] = self.getReferees(tenantKey=tenantKey, forceReload=True)
            return referees
    
    @cacheDecorator.cache(entityType=EntityType.CLIENTIDENTIFIERS, actionType=ActionType.GET, identifierArgs=['clientIdentifier'])
    def getClientIdentifier(self, clientIdentifier, from_created: datetime = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get client identifier data from database (not cached as it's user-specific)"""
        try:
            with self._internal_lock:
                result = self.dbClient.getClientIdentifier(clientIdentifier=clientIdentifier, frmo_created=from_created)
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
    
    def getTournamentGamesArchived(self, tenantKey: str, tournamentName, gamePk=None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get archived tournament games from database (not cached as it's tournament-specific)"""
        try:
            return self.dbClient.getTournamentGamesArchived(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
        except Exception as ex:
            self.logger.error(f"❌ Error getting archived tournament games for {tournamentName}:", ex)
            return None

    @cacheDecorator.cache(entityType=EntityType.REFEREES, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getReferees(self, tenantKey: str, mobileNo: str=None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get referee properties from database (not cached as it's referee-specific)"""
        try:
            result = self.dbClient.getRefereeProperties(tenantKey=tenantKey, mobileNo=mobileNo)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee properties for {mobileNo}:", ex)
            return None
    
    def getRefereeProperty(self, tenantKey: str, mobileNo: str, propertyName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        referee = self.getReferees(tenantKey=tenantKey, mobileNo=mobileNo, forceReload=forceReload)
        if referee:
            return referee.get(propertyName.replace(' ', ''))
        return None

    def getCachedKey(self, **kwargs):
        tenantKey = kwargs.pop('tenantKey', 'GLOBAL')
        entityType = kwargs.pop('entityType', None)
        segments = []
        segments.append(tenantKey)
        segments.append('cacheOnly')
        if entityType:
            segments.append(str(entityType))
        segments.extend([str(v) for k, v in kwargs.items()])
        key = ':'.join(segments)
        key = key.replace('#', ':')
        return key

    def getCachedKeyVal(self, **kwargs):
        key = self.getCachedKey(**kwargs)
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

    @cacheDecorator.cache(entityType=EntityType.REFEREEAVAILABILITY, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getRefereeAvailaiblity(self, mobileNo: str, from_date: datetime = None, to_date: datetime = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get referee availability from database (not cached as it's referee and date-specific)"""
        try:
            return self.dbClient.getRefereeAvailaiblity(mobileNo=mobileNo, from_date=from_date, to_date=to_date)
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee availability for {mobileNo}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.REFEREETEMPLATES, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getRefereeTemplates(self, tenantKey: str, mobileNo, action:str = None, msgSid:Optional[str] = None, status:Optional[str] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, from_updated: Optional[datetime] = None, to_updated: Optional[datetime] = None, forceReload: bool = False, **kwargs) -> Optional[List[Dict[str, Any]]]:
        """Get referee templates from database (not cached as it's mobile-specific)"""
        try:
            result = self.dbClient.getRefereeTemplates(tenantKey=tenantKey, mobileNo=mobileNo, action=action, msgSid=msgSid, status=status, from_created=from_created, to_created=to_created, from_updated=from_updated, to_updated=to_updated)
            return result   
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee templates for {mobileNo}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.REFEREEMESSAGES, actionType=ActionType.GET, identifierArgs=['mobileNo', 'direction'])
    def getRefereeMessages(self, mobileNo:str, direction:str, msgSid:Optional[str] = None, recentDays:Optional[int] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, forceReload: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Get referee messages from database (not cached as it's mobile-specific)"""
        try:
            return self.dbClient.getRefereeMessages(mobileNo=mobileNo, direction=direction, msgSid=msgSid, recentDays=recentDays, from_created=from_created, to_created=to_created)
        except Exception as ex:
            self.logger.error(f"❌ Error getting referee messages for {mobileNo}:{direction} {ex}")
            return None
        
    @cacheDecorator.cache(entityType=EntityType.MESSAGES, actionType=ActionType.GET, identifierArgs=['msgSid'])
    def getMessage(self, msgSid, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get message from database (not cached as it's message-specific)"""
        try:
            result = self.dbClient.getMessage(msgSid=msgSid)
            return list(result.values())[0]
        except Exception as ex:
            self.logger.error(f"❌ Error getting message {msgSid}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.KEYVAL, actionType=ActionType.GET, identifierArgs=['key'])
    def getKeyVal(self, key, forceReload: bool = False) -> Optional[Any]:
        """Get key-value from database (not cached as it's key-specific)"""
        try:
            result = self.dbClient.getKeyVal(key=key)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting key-value for {key}:", ex)
            return None
    
    @cacheDecorator.cache(entityType=EntityType.POSITIONUPDATES, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getPositionUpdates(self, mobileNo):
        with self._internal_lock:
            return self.dbClient.getPositionUpdates(mobileNo=mobileNo)

    @cacheDecorator.cache(entityType=EntityType.REFEREELOCATIONS, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getRefereeLocations(self, mobileNo, timestamp:int=None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        with self._internal_lock:
            return self.dbClient.getRefereeLocations(mobileNo=mobileNo, timestamp=timestamp)

    @cacheDecorator.cache(entityType=EntityType.REFERENCEIDS, actionType=ActionType.GET, identifierArgs=['target'])
    def getReferenceId(self, target: str, id: str = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get reference ID from database (not cached as it's reference-specific)"""
        try:
            result = self.dbClient.getReferenceId(target=target, id=id)
            return result
        except Exception as ex:
            self.logger.error(f"❌ Error getting reference ID for {target}:{id}:", ex)
            return None

    @cacheDecorator.cache(entityType=EntityType.NOTIFICATIONS, actionType=ActionType.GET, identifierArgs=['target', 'id'])
    def getNotifications(self, tenantKey: str, target: str, id: str = None, notificationType: str = None, to:str = None, timestamp: int = None, status: str = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, from_updated: Optional[datetime] = None, to_updated: Optional[datetime] = None, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get notifications from database (not cached as it's notification-specific)"""
        try:
            return self.dbClient.getNotifications(tenantKey=tenantKey, target=target, id=id, notificationType=notificationType, to=to, timestamp=timestamp, status=status, from_created=from_created, to_created=to_created, from_updated=from_updated, to_updated=to_updated)
        except Exception as ex:
            self.logger.error(f"❌ Error getting notifications for {target}:{id}:{notificationType}:{timestamp}:", ex)
            return None

    #@cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.COUNT, identifierArgs=['refId'])
    def countRefereeGames(self, tenantKey: str, refId: str = None, includeArchived: bool = False, includeRemoved: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, expr: Callable = None) -> int:
        games = self.getRefereeGames(tenantKey=tenantKey, refId=refId, includeArchived=includeArchived, includeRemoved=includeRemoved, from_date=from_date, to_date=to_date)
        filteredGames = [game for game in games.values() if expr(game)] if expr else list(games.values())
        return len(filteredGames)

    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.GET, identifierArgs=['refId'])
    def getRefereeGames(self, tenantKey: str, refId: str, gamePk: Optional[str] = None, includeArchived: bool = False, includeRemoved: bool = False, includeCanceled: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, forceReload: bool = False, **kwargs) -> Dict[str, Any]:
        """Get referee games data from cache by referee ID and optional game PK"""
        with self._internal_lock:
            referee_games = self.dbClient.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=gamePk, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
            return referee_games
            if gamePk:
                if forceReload or not self._is_cache_valid(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{refId}:{gamePk}"):
                    self._load_referee_games(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
                return self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{refId}:{gamePk}")
            else:
                # Load all games with filters
                gamePks = self._load_referee_games(tenantKey=tenantKey, refId=refId, include_archived=includeArchived, include_removed=includeRemoved, include_canceled=includeCanceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
                
                # Get all games from Redis
                games = {}
                for gamePk in gamePks:
                    game_data = self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{refId}:{gamePk}")
                    if game_data and self._should_include_game(game=game_data, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, from_date=from_date, to_date=to_date):
                        games = games | {gamePk: game_data}
                
                return games

    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getRefereeGamesNew(self, tenantKey: str, mobileNo: str, gamePk: Optional[str] = None, includeArchived: bool = False, includeRemoved: bool = False, includeCanceled: bool = False, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, from_created: Optional[datetime] = None, to_created: Optional[datetime] = None, forceReload: bool = False, **kwargs) -> Dict[str, Any]:
        """Get referee games data from cache by referee ID and optional game PK"""
        with self._internal_lock:
            referee_games = self.dbClient.getRefereeGamesNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
            return referee_games
            if gamePk:
                if forceReload or not self._is_cache_valid(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{mobileNo}:{gamePk}"):
                    self._load_referee_games_new(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
                return self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{mobileNo}:{gamePk}")
            else:
                # Load all games with filters
                gamePks = self._load_referee_games_new(tenantKey=tenantKey, mobileNo=mobileNo, include_archived=includeArchived, include_removed=includeRemoved, include_canceled=includeCanceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
                
                # Get all games from Redis
                games = {}
                for gamePk in gamePks:
                    game_data = self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEGAMES, identifier=f"{mobileNo}:{gamePk}")
                    if game_data and self._should_include_game(game=game_data, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, from_date=from_date, to_date=to_date):
                        games = games | {gamePk: game_data}
                
                return games

    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.SET, identifierArgs=['refId'])
    def setRefereeGame(self, tenantKey, refId, gamePk, value):
        """Proxy for dbClient.setRefereeGame with cache invalidation"""
        result = self.dbClient.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=gamePk, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def setRefereeGameNew(self, tenantKey, mobileNo, gamePk, value):
        """Proxy for dbClient.setRefereeGame with cache invalidation"""
        result = self.dbClient.setRefereeGameNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.GET, identifierArgs=['refId'])
    def getRefereeReviews(self, tenantKey: str, refId: str, gamePk: Optional[str] = None, season: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None, forceReload: bool = False) -> Dict[str, Any]:
        """Get referee reviews data from cache by referee ID and optional game PK"""
        with self._internal_lock:
            referee_reviews = self.dbClient.getRefereeReviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk, from_date=from_date, to_date=to_date)
            return referee_reviews
            if gamePk:
                if forceReload or not self._is_cache_valid(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{refId}:{gamePk}"):
                    self._load_referee_reviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
                return self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{refId}:{gamePk}")
            else:
                # Load all reviews with filters
                gamePks = self._load_referee_reviews(tenantKey=tenantKey, refId=refId, from_date=from_date, to_date=to_date)
                
                # Get all reviews from Redis
                reviews = {}
                for gamePk in gamePks:
                    review_data = self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{refId}:{gamePk}")
                    if review_data:
                        reviews = reviews | {gamePk: review_data}

                return reviews

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.GET, identifierArgs=['mobileNo'])
    def getRefereeReviewsNew(self, tenantKey: str, mobileNo: str, gamePk: Optional[str] = None, season: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None, forceReload: bool = False) -> Dict[str, Any]:
        """Get referee reviews data from cache by referee ID and optional game PK"""
        with self._internal_lock:
            referee_reviews = self.dbClient.getRefereeReviewsNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, from_date=from_date, to_date=to_date)
            return referee_reviews
            if gamePk:
                if forceReload or not self._is_cache_valid(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{mobileNo}:{gamePk}"):
                    self._load_referee_reviews_new(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
                return self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{mobileNo}:{gamePk}")
            else:
                # Load all reviews with filters
                gamePks = self._load_referee_reviews_new(tenantKey=tenantKey, mobileNo=mobileNo, from_date=from_date, to_date=to_date)
                
                # Get all reviews from Redis
                reviews = {}
                for gamePk in gamePks:
                    review_data = self._redis_cache_get(tenantKey=tenantKey, entityType=EntityType.REFEREEREVIEWS, identifier=f"{mobileNo}:{gamePk}")
                    if review_data:
                        reviews = reviews | {gamePk: review_data}

                return reviews

    #@cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.COUNT, identifierArgs=['tournamentName'])
    def countTournamentGames(self, tenantKey: str, tournamentName: str = None, nonArchivedOnly: bool = False, expr: Callable = None) -> int:
        games = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, nonArchivedOnly=nonArchivedOnly)
        filteredGames = [game for game in games.values() if expr(game)] if expr else list(games.values())
        return len(filteredGames)

    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.GET, identifierArgs=['tournamentName'])
    def getTournamentGames(self, tenantKey: str, tournamentName: str = None, gamePk: Optional = None, nonArchivedOnly: bool = False, forceReload: bool = False, filters: list = []) -> Dict[str, Any]:
        """Get tournament games data from cache by tournament name and optional game PK"""
        with self._internal_lock:
            pk_list = self._normalize_game_pk_list(gamePk)
            if pk_list:
                if not forceReload:
                    games, missing = self._get_cached_tournament_games_by_pk(
                        tenantKey=tenantKey,
                        tournamentName=tournamentName,
                        pk_list=pk_list,
                    )
                    if not missing:
                        return games
                    db_pk = missing[0] if len(missing) == 1 else missing
                    loaded = self._load_tournamentGames(
                        tenantKey=tenantKey,
                        tournamentName=tournamentName,
                        gamePk=db_pk,
                        nonArchivedOnly=nonArchivedOnly,
                        filters=filters,
                    ) or {}
                    games.update({str(k): v for k, v in loaded.items()})
                    return games
                loaded = self._load_tournamentGames(
                    tenantKey=tenantKey,
                    tournamentName=tournamentName,
                    gamePk=pk_list[0] if len(pk_list) == 1 else pk_list,
                    nonArchivedOnly=nonArchivedOnly,
                    filters=filters,
                )
                return loaded or {}

            if not forceReload and self._is_cache_valid(
                tenantKey=tenantKey,
                entityType=EntityType.TOURNAMENTSGAMES,
                identifier=tournamentName,
            ):
                pattern = f"{self._get_cache_key(tenantKey=tenantKey, entityType=EntityType.TOURNAMENTSGAMES, identifier=tournamentName)}:*"
                redis_keys = self.redis_get_keys(pattern=pattern)
                if redis_keys:
                    batch = self._redis_get_batch(redis_keys)
                    games = {}
                    for cache_key, data in batch.items():
                        if not isinstance(data, dict) or not data:
                            continue
                        ident = cache_key.rsplit(':', 1)[-1]
                        if ':' in ident:
                            pk = ident.rsplit(':', 1)[-1]
                        else:
                            pk = str(data.get('gamePk') or ident)
                        games[str(pk)] = data
                    if games:
                        return games

            return self.dbClient.getTournamentGames(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
                gamePk=gamePk,
                nonArchivedOnly=nonArchivedOnly,
                filters=filters,
            )
    
    #@cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.GET, identifierArgs=['tournament_name'])
    def getGameDetail(self, tenantKey: str, game: dict, forceReload: bool = False) -> Dict[str, Any]:
        """Get tournament games data from cache by tournament name and optional game PK"""
        with self._internal_lock:
            tournament_name = game.get('tournamentName')
            gamePk = game.get('gamePk')
            if tournament_name and gamePk:
                gameDetail = self.getTournamentGames(tenantKey=tenantKey, tournamentName=game.get('tournamentName'), gamePk=game.get('gamePk'), forceReload=forceReload)
                if gameDetail:
                    return gameDetail
            return None
    
    #@cacheDecorator.cache(entityType=EntityType.REFERENCEIDS, actionType=ActionType.GET, identifierArgs=['gameId'])
    def getGameDetailById(self, gameId: str, forceReload: bool = False) -> Dict[str, Any]:
        """Get tournament games data from cache by tournament name and optional game PK"""
        with self._internal_lock:
            #game_detail = self._redis_cache_get(tenantKey='GLOBAL', entityType='gameDetailId', identifier=gameId)
            #if not game_detail:
            referenceValue = self.getReferenceId(target=str(EntityType.TOURNAMENTSGAMES), id=gameId)
            if not referenceValue:
                return None
            return self.getGameDetail(tenantKey=referenceValue.get('tenantKey'), game=referenceValue, forceReload=forceReload)
            #return game_detail
    
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
            cache_keys = self.redis_get_keys(f"{tenantKey.replace('#',':')}:{self._cache_prefix}:*")
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
                type_keys = self.redis_get_keys(pattern=f"{tenantKey.replace('#',':')}:{self._cache_prefix}{entityType}:*")
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
    def get_field_by_name(self, tenantKey: str, fieldName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific field by name"""
        fields = self.getFields(tenantKey=tenantKey, forceReload=forceReload)
        return fields.get(fieldName, {})
    
    def get_tournament_by_name(self, tenantKey: str, tournamentName: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific tournament by name"""
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
    
    def get_tenant_by_key(self, tenantKey: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific tenant by key"""
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
            all_keys = self.redis_get_keys(pattern=f"*:{self._cache_prefix}*")
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
                type_keys = self.redis_get_keys(pattern=f"*:{self._cache_prefix}{entityType}:*")
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
            pattern = f"{tenantKey.replace('#',':')}:{self._cache_prefix}{EntityType.REFEREEGAMES}:{refId}:*"
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
            pattern = f"{tenantKey.replace('#',':')}:{self._cache_prefix}{EntityType.REFEREEREVIEWS}:{refId}:*"
            keys = self.redis_get_keys(pattern)
            for key in keys:
                self.redis_delete(key)
            self.logger.debug(f"🗑️ Expired all referee reviews for referee {refId}")
        else:
            for gamePk in gamePks:
                results[gamePk] = self.expire_referee_review(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
        return results
    
    def expire_multiple_tournamentGames(self, tenantKey: str, tournamentName: str, gamePks: Optional[List[str]] = None) -> Dict[str, bool]:
        """Mark multiple tournament games as expired and remove from cache"""
        results = {}
        if gamePks is None:
            # Delete all tournament games for this tournament
            pattern = f"{tenantKey.replace('#',':')}:{self._cache_prefix}tournamentGames:{tournamentName}:*"
            keys = self.redis_get_keys(pattern=pattern)
            for key in keys:
                self.redis_delete(key)
            self.expire_tournament_games_index(tenantKey=tenantKey, tournamentName=tournamentName)
            self.logger.debug(f"🗑️ Expired all tournament games for tournament {tournamentName}")
        else:
            for gamePk in gamePks:
                results[gamePk] = self.expire_tournament_game(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
        return results
    
    def get_referee_game_by_pk(self, tenantKey: str, refId: str, gamePk: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific referee game by PK"""
        referee_game = self.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=gamePk, forceReload=forceReload)
        return referee_game

    def get_referee_game_by_pk_new(self, tenantKey: str, mobileNo: str, gamePk: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific referee game by PK"""
        referee_game = self.getRefereeGamesNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, forceReload=forceReload)
        return referee_game

    def get_referee_review_by_pk(self, tenantKey: str, refId: str, gamePk: str, forceReload: bool = False) -> Optional[Dict[str, Any]]:
        """Get specific referee review by PK"""
        referee_review = self.getRefereeReviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk, forceReload=forceReload)
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
    
    def reload_referee_data_new(self, tenantKey: str, mobileNo: str, gamePk: Optional[str] = None) -> bool:
        """Reload all data for a specific referee and optional game PK"""
        try:
            self.logger.info(f"🔄 Reloading data for referee {mobileNo}" + (f" and game PK {gamePk}" if gamePk else "") + "...")
            with self._internal_lock:
                self._load_referee_games_new(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
                #self._load_referee_reviews(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
            self.logger.info(f"✅ Referee {mobileNo}" + (f" and game PK {gamePk}" if gamePk else "") + " data reloaded successfully")
            return True
        except Exception as ex:
            self.logger.error(f"❌ Error reloading data for referee {mobileNo}" + (f" and game PK {gamePk}" if gamePk else "") + f":", ex)
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
    
    @cacheDecorator.cache(entityType=EntityType.LEAGUETABLES, actionType=ActionType.SET, identifierArgs=['tournamentName'])
    def setLeagueTable(self, tenantKey, tournamentName, value):
        """Proxy for dbClient.setLeagueTable with cache invalidation"""
        result = self.dbClient.setLeagueTable(tenantKey=tenantKey, tournamentName=tournamentName, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.SET, identifierArgs=['tournamentName'])
    def setTournamentGame(self, tenantKey, tournamentName, gamePk, value):
        """Proxy for dbClient.setTournamentGame with cache invalidation"""
        result = self.dbClient.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=value)
        try:
            tournament = self.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
            section = (tournament or {}).get('section', '')
            self._upsert_tournament_games_index_entry(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
                gameDetail=value,
                section=section,
            )
        except Exception as ex:
            self.logger.error(f"setTournamentGame index update failed tournamentName={tournamentName} gamePk={gamePk}:", ex)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREES, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def setReferee(self, tenantKey, mobileNo, value, **kwargs):
        """Proxy for dbClient.setRefereeProperties with cache invalidation"""
        result = self.dbClient.setRefereeProperties(tenantKey=tenantKey, mobileNo=mobileNo, value=value)
        return result

    def setRefereeProperty(self, tenantKey, mobileNo, value, propertyName=None, **kwargs):
        referee = self.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        if not referee:
            return
        if propertyName:
            referee[propertyName.replace(' ', '')] = value
        elif isinstance(value, dict):
            for _propertyName, _value in value.items():
                if _propertyName:
                    referee[_propertyName.replace(' ', '')] = _value
        result = self.setReferee(tenantKey=tenantKey, mobileNo=mobileNo, value=referee)

    def setCachedKeyVal(self, **kwargs):
        value = kwargs.pop('value', None)
        ttlSeconds = kwargs.pop('ttlSeconds', 60 * 60 * 24)
        key = self.getCachedKey(**kwargs)
        if value:
            if not isinstance(value, dict):
                value = {'value': value}
            value = jsonHelper.save_to_json(value)
        result = self.redis_set(key=key, data=value, ttl_seconds=ttlSeconds)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEAVAILABILITY, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def setRefereeAvailaiblity(self, mobileNo: str, value):
        """Proxy for dbClient.setRefereeAvailaiblity with cache invalidation"""
        result = self.dbClient.setRefereeAvailaiblity(mobileNo=mobileNo, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.CLIENTIDENTIFIERS, actionType=ActionType.SET, identifierArgs=['clientIdentifier'])
    def setClientIdentifier(self, clientIdentifier, sessionIdentifier, pushSubscription=None, mobileNo=None, userAgent=None, platform=None, status=None):
        """Proxy for dbClient.setClientIdentifier with cache invalidation"""
        result = self.dbClient.setClientIdentifier(clientIdentifier=clientIdentifier, sessionIdentifier=sessionIdentifier, pushSubscription=pushSubscription, mobileNo=mobileNo, userAgent=userAgent, platform=platform, status=status)
        return result

    @cacheDecorator.cache(entityType=EntityType.TOURNAMENTSGAMES, actionType=ActionType.SET, identifierArgs=['tournamentName', 'gamePk'])
    def deleteTournamentGame(self, tenantKey, tournamentName, gamePk):
        """Proxy for dbClient.deleteTournamentGame with cache invalidation"""
        self.dbClient.deleteTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
        try:
            self._remove_tournament_games_index_entry(
                tenantKey=tenantKey,
                tournamentName=tournamentName,
                gamePk=gamePk,
            )
        except Exception as ex:
            self.logger.error(f"deleteTournamentGame index update failed tournamentName={tournamentName} gamePk={gamePk}:", ex)
    
    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.SET, identifierArgs=['refId'])
    def deleteRefereeGame(self, tenantKey, refId, gamePk):
        """Proxy for dbClient.removeRefereeGame with cache invalidation"""
        result = self.dbClient.removeRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.REFEREEGAMES, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def deleteRefereeGameNew(self, tenantKey, mobileNo, gamePk):
        """Proxy for dbClient.removeRefereeGame with cache invalidation"""
        result = self.dbClient.removeRefereeGameNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.SET, identifierArgs=['refId'])
    def setRefereeReview(self, tenantKey, refId, gamePk, value):
        """Proxy for dbClient.setRefereeReview with cache invalidation"""
        result = self.dbClient.setRefereeReview(tenantKey=tenantKey, refId=refId, gamePk=gamePk, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def setRefereeReviewNew(self, tenantKey, mobileNo, gamePk, value):
        """Proxy for dbClient.setRefereeReview with cache invalidation"""
        result = self.dbClient.setRefereeReviewNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.SET, identifierArgs=['refId'])
    def removeRefereeReview(self, tenantKey, refId, gamePk):
        """Proxy for dbClient.removeRefereeReview with cache invalidation"""
        result = self.dbClient.removeRefereeReview(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREEREVIEWS, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def removeRefereeReviewNew(self, tenantKey, mobileNo, gamePk):
        """Proxy for dbClient.removeRefereeReview with cache invalidation"""
        result = self.dbClient.removeRefereeReviewNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREETEMPLATES, actionType=ActionType.SET, identifierArgs=['mobileNo'])
    def setRefereeTemplate(self, tenantKey, mobileNo, msgSid, value):
        """Proxy for dbClient.setRefereeTemplate with cache invalidation"""
        result = self.dbClient.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.REFEREEMESSAGES, actionType=ActionType.SET, identifierArgs=['mobileNo', 'direction'])
    def setRefereeMessage(self, mobileNo:str, direction:str, msgSid:str, value:dict):
        """Proxy for dbClient.setRefereeMessage with cache invalidation"""
        result = self.dbClient.setRefereeMessage(mobileNo=mobileNo, direction=direction, msgSid=msgSid, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.MESSAGES, actionType=ActionType.SET, identifierArgs=['msgSid'])
    def setMessage(self, msgSid, value):
        """Proxy for dbClient.setMessage with cache invalidation"""
        result = self.dbClient.setMessage(msgSid=msgSid, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.KEYVAL, actionType=ActionType.SET, identifierArgs=['key'])
    def setKeyVal(self, key, value):
        """Proxy for dbClient.setKeyVal with cache invalidation"""
        result = self.dbClient.setKeyVal(key=key, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.POSITIONUPDATES, actionType=ActionType.SET, identifierArgs=['mobileNo', 'timestamp'])
    def setPositionUpdate(self, mobileNo:str, timestamp:str, value:dict):
        result = self.dbClient.setPositionUpdate(mobileNo=mobileNo, timestamp=timestamp, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.REFEREELOCATIONS, actionType=ActionType.SET, identifierArgs=['mobileNo', 'timestamp'])
    def setRefereeLocation(self, mobileNo:str, timestamp:int, value:dict):
        result = self.dbClient.setRefereeLocation(mobileNo=mobileNo, timestamp=timestamp, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.INVOCATIONS, actionType=ActionType.SET)
    def setInvocation(self, tenantKey, invocationId, value):
        """Proxy for dbClient.setInvocation with cache invalidation"""
        result = self.dbClient.setInvocation(tenantKey=tenantKey, invocationId=invocationId, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.REFERENCEIDS, actionType=ActionType.SET, identifierArgs=['target'])
    def setReferenceId(self, target: str, id: str, value):
        """Proxy for dbClient.setReferenceId with cache invalidation"""
        result = self.dbClient.setReferenceId(target=target, id=id, value=value)
        return result

    @cacheDecorator.cache(entityType=EntityType.NOTIFICATIONS, actionType=ActionType.SET, identifierArgs=['target', 'id'])
    def setNotification(self, tenantKey: str, target: str, id: str, notificationType:str, to:str, timestamp: int, value, **kwargs):
        """Proxy for dbClient.setNotifications with cache invalidation"""
        id = helpers.resolve_notification_item_id(id, target)
        if isinstance(value, dict):
            value['id'] = id
            value['target'] = target
            value['notificationType'] = notificationType
            value['tenantKey'] = tenantKey
        result = self.dbClient.setNotifications(tenantKey=tenantKey, target=target, id=id, notificationType=notificationType, to=to, timestamp=timestamp, value=value)
        return result

    def setCollectedItems(self, tenantKey, objType, mobileNo, value):
        entityType = EntityType.COLLECTEDITEMS
        with self._internal_lock:
            self._redis_cache_set(tenantKey=tenantKey, entityType=entityType, data=value or {}, identifier=f'{objType}:{mobileNo}')

    #@cacheDecorator.cache(entityType=EntityType.COLLECTEDITEMS, actionType=ActionType.COUNT, identifierArgs=['objType'])
    def countCollectedItems(self, tenantKey: str, objType: str) -> int:
        keys = self._redis_cache_get_keys(tenantKey=tenantKey, entityType=EntityType.COLLECTEDITEMS, identifier=f'{objType}:*')
        return len(keys)
    
    def getCollectedItems(self, tenantKey, objType, mobileNo=None) -> dict:
        entityType = EntityType.COLLECTEDITEMS
        with self._internal_lock:
            return self._redis_cache_get(tenantKey=tenantKey, entityType=entityType, identifier=f'{objType}:{mobileNo or "*"}')

    @cacheDecorator.cache(entityType=EntityType.POLLS, actionType=ActionType.GET, identifierArgs=['pollId'])
    def getPolls(self, pollId=None) -> dict:
        with self._internal_lock:
            return self.dbClient.getPolls(pollId=pollId)
    
    @cacheDecorator.cache(entityType=EntityType.POLLVOTES, actionType=ActionType.GET, identifierArgs=['pollId', 'mobileNo'])
    def getPollVotes(self, pollId, mobileNo=None, questionId=None) -> dict:
        with self._internal_lock:
            return self.dbClient.getPollVotes(pollId=pollId, mobileNo=mobileNo, questionId=questionId)
    
    @cacheDecorator.cache(entityType=EntityType.POLLS, actionType=ActionType.SET, identifierArgs=['pollId'])
    def setPoll(self, pollId, value) -> bool:
        result = self.dbClient.setPoll(pollId=pollId, value=value)
        return result
    
    @cacheDecorator.cache(entityType=EntityType.POLLVOTES, actionType=ActionType.SET, identifierArgs=['pollId', 'mobileNo', 'questionId'])
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

    tenantKey = 'IL#football#2024-25'
    referees = cacheService.getReferees(tenantKey=tenantKey, mobileNo=None)
    #referees = {referees['mobileNo']: referees}
    for mobileNo, referee in referees.items():
        if not referee.get('refId'):
            continue
        items = cacheService.getRefereeGames(tenantKey=tenantKey, refId=referee['refId'])
        if not items:
            continue
        for item in items.values():
            mappedItem = multiTenantSupport.mapItem(tenantKey=tenantKey, objType='games', obj=item)
            cacheService.setRefereeGame(tenantKey=tenantKey, refId=item['refId'], gamePk=item['gamePk'], value=mappedItem)
            cacheService.setRefereeGameNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=item['gamePk'], value=mappedItem)

        items = cacheService.getRefereeReviews(tenantKey=tenantKey, refId=referee['refId'])
        if not items:
            continue
        for item in items.values():
            mappedItem = multiTenantSupport.mapItem(tenantKey=tenantKey, objType='reviews', obj=item)
            cacheService.setRefereeReview(tenantKey=tenantKey, refId=item['refId'], gamePk=item['gamePk'], value=mappedItem)
            cacheService.setRefereeReviewNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=item['gamePk'], value=mappedItem)

    exit(0)
    tour = cacheService.get_tournament_by_name(tenantKey='IL#handball#2025-26', tournamentName='ליגה נערות')
    cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo='+972547799979', value=False, propertyName='forceUseGreenApi')
    result = cacheService.getRefereeGames(tenantKey='IL#football#2025-26', refId=None, gamePk=['aaa', 'bbb'], from_date=datetime.now() - timedelta(days=7), forceReload=True)
    print(result)
    exit(0)
    handleUsers = container.handle_users()
    messagingService = container.messaging_service()

    tenantKey = 'IL#handball#2025-26'
    templates = cacheService.getRefereeTemplates(tenantKey=tenantKey, mobileNo=None, status='deferred', from_created=helpers.localNow() - timedelta(days=7))
    templatesMobileNos = list(set([template['mobileNo'] for template in templates.values()]))
    templatesMobileNos = ['+972524721664', '+972537211970']
    templatesMobileNos.sort()
    for mobileNo in templatesMobileNos:
        globalReferee = cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
        tenantReferee = cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        decryptedPassword = handleUsers.decryptPassword(tenantReferee.get('password', ''))
        if decryptedPassword:
            continue
        msg = f'אהלן {globalReferee.get('name', '')}, המערכת זיהתת שניסית להשתמש בשירותיה לביצוע פעולות אוטומטיות אבל לא הצליחה לבצע אותם מכיוון שלא עידכנת סיסמא דרך האפליקציה, לאחר עדכון הסיסמא תוכל להמשיך ולהשתמש בשירותים האוטומטיים של המערכת ובהצלחה.'
        send = False
        if send:
            msgSid = asyncio.run(messagingService.sendMessage(to=mobileNo, message=msg))
        pass
    exit(0)
    
    pendingGames = cacheService.getRefereeGames(tenantKey='IL#handball#2025-26', refId=None, includeArchived=False, includeRemoved=False, includeCanceled=False, from_date=helpers.localNow().date().isoformat())
    gamePks = list(set(game['gamePk'] for game in pendingGames.values()))
    gamePks.sort()
    i = 0
    total = 0
    for gamePk in gamePks:
        notifications = cacheService.getNotifications(tenantKey='IL#handball#2025-26', target='refereeGames', id=gamePk, notificationType='removedItem', to=None, status='sent')
        sentNotificationsToday = [notification for notification in notifications.values() if notification.get('sentDate').date() == helpers.localNow().date()]
        for notification in sentNotificationsToday:
            timeToSent = notification.get('sentDate') - notification.get('created')
            if timeToSent.total_seconds() > 12 * 60 * 60:
                i += 1
            pass
    
    exit(0)

    '''
        if False and gamePk != 'לאומית גבריםהפועל "קולסקי" פתח תקוה  הפועל "יוסי אברהמי" ערד1036839':
            continue
        for target in ['refereeGames', 'tournamentGames']:
            notifications = cacheService.getNotifications(tenantKey='IL#handball#2025-26', target=target, id=gamePk, notificationType=None, to=None, status='created')
            total += len(notifications)
            notificationGroups = set([(notification.get('notificationType'), notification.get('to')) for notification in notifications.values()])
            for notificationGroup in notificationGroups:
                notificationType, to = notificationGroup
                notificationsPerGroup = [notification for notification in notifications.values() if notification.get('notificationType') == notificationType and notification.get('to') == to]
                sentNotifications = cacheService.getNotifications(tenantKey='IL#handball#2025-26', target=target, id=gamePk, notificationType=notificationType, to=to, status='sent')
                if False and len(notificationsPerGroup) <= 1:
                    continue
                deleteFrom = 0 if len(sentNotifications) > 0 else 1
                for notification in notificationsPerGroup[deleteFrom:]:
                    i += 1
                    notification['status'] = 'deleted'
                    cacheService.setNotification(tenantKey='IL#handball#2025-26', target=target, id=gamePk, notificationType=notificationType, to=to, timestamp=notification['timestamp'], value=notification)
    print(i)
    print(total)
    exit(0)
    '''
    cacheService.setField(tenantKey='IL#football#2025-26', fieldName='טריאדור', value={'addressDetails': {'latitude': 31.768318, 'longitude': 35.213711}})
    cacheService.get_field_by_name(tenantKey='IL#football#2025-26', fieldName='פתח תקוה סירקין אימונים 3')
    tenants = cacheService.getTenants()
    for tenantKey, tenant in tenants.items():
        tournaments = cacheService.getTournaments(tenantKey=tenantKey)
        for tournamentName, tournament in tournaments.items():
            games = cacheService.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName)
            for gamePk, game in games.items():
                if game.get('removed', False) == True:
                    game['state'] = 'removed'
                elif game.get('canceled', False) == True:
                    game['state'] = 'canceled'
                elif game.get('archived', False) == True:
                    game['state'] = 'archived'
                else:
                    game['state'] = 'active'
            

    res = cacheService.getCachedKeyVal(tenantKey='GLOBAL', mobileNo='+972547799979', propertyName='2FA_PortalCode')
    cacheService.setCachedKeyVal(tenantKey='GLOBAL', mobileNo='+972547799979', value='abcdef', propertyName='2FA_PortalCode')
    res = cacheService.getCachedKeyVal(tenantKey='GLOBAL', mobileNo='+972547799979', propertyName='2FA_PortalCode')
    pass

    getCollectedItems = cacheService.getCollectedItems(tenantKey='IL#handball#2025-26', objType='games', mobileNo='+972547799979')
    countCollectedItems = cacheService.countCollectedItems(tenantKey='IL#handball#2025-26', objType='games')

    pendingGames = cacheService.getRefereeGames(tenantKey='IL#football#2025-26', refId='43679', from_date=datetime.now().isoformat())
    for game in pendingGames.values():
        gameDetail = cacheService.getGameDetail(tenantKey='IL#football#2025-26', game=game)
        if 'הכח' in gameDetail.get('gameTitle'):
            gameDetail['chatGroupId'] = '120363403511212950@g.us'
            cacheService.setTournamentGame(tenantKey='IL#football#2025-26', tournamentName=gameDetail.get('tournamentName'), gamePk=gameDetail.get('gamePk'), value=gameDetail)
    countCollectedItems = cacheService.countCollectedItems(tenantKey='IL#handball#2025-26', objType='games')
    pendingGamesCount = cacheService.countTournamentGames(tenantKey='IL#handball#2025-26', expr=(lambda x: x['date'] >= datetime.now() and x.get('state', 'active') != 'archived'))
    todayGamesCount = cacheService.countTournamentGames(tenantKey='IL#handball#2025-26', expr=(lambda x: x['date'].date() == datetime.now().date() and x.get('state', 'active') != 'archived'))
    refereeGamesCount = cacheService.countRefereeGames(tenantKey='IL#handball#2025-26', refId='100', expr=(lambda x: x.get('state', 'active') != 'archived'))
    #service.setRefereeTemplate(tenantKey='IL#football#2025-26', mobileNo='+972547799979', msgSid='1234567890', value={'status': 'stam', 'created': datetime.now()})
    sections = cacheService.getSections(tenantKey='IL#football#2025-26')
    for sectionName, section in sections.items():
        if 'sendRefereeGameUpdateReminder' in section:
            del section['sendRefereeGameUpdateReminder']
        if 'יל' in sectionName or 'טר' in sectionName:
            section['skipRefereeGameUpdateReminder'] = False
        else:
            section['skipRefereeGameUpdateReminder'] = True
        cacheService.setSection(tenantKey='IL#football#2025-26', sectionName=sectionName, value=section)
        print(sectionName, section)
    exit(0)