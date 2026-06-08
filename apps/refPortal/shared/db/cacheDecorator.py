import functools
import hashlib
import json
from datetime import timedelta, date, datetime
from typing import Callable, Any, Dict, Tuple, List, Optional
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.enumTypes import EntityType, ActionType
from shared.logger import Logger
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db.dbClientBase import DbClientBase

class CacheDecorator:
    """Class-based decorator that can hold cache instance"""

    # Kwargs for DynamodbClient.getDict that are not DynamoDB key attributes
    _GET_DICT_OPTION_KEYS = frozenset({
        'jsonDumps', 'skipConversion', 'recentDays', 'asIsEntityKey', 'filters1', 'forceReload', 'entityType', 'value', 'onlyCache', 'expr', 'ttlSeconds'
    })
    
    def __init__(self):
        pass

    @staticmethod
    def getEntityKeysAndFilters(
        entityType: EntityType,
        **kwargs: Any,
    ) -> Tuple[EntityType, str, List[Tuple[str, str]], List[List[Tuple[str, Any]]]]:
        """
        Split call parameters into a list of **range key components** and query filter iterations,
        in :meth:`CacheTypes` key order (``refId/mobileNo`` uses the first non-None match).

        - Remaining arguments become filter tuples ``(name, {condition, value, ...?})``;
          plain values become ``{'condition': 'eq', 'value': value}`` (with from*/to* gte/lte).
        - ``getDict``-only options (``jsonDumps``, ``skipConversion``, ``recentDays``,
          ``asIsEntityKey``, ``filters``) are stripped from kwargs.

        :param tenantKey: Partition key for the query; not part of the returned list.
        :return: ``(entity_type, tenantKey, entity_key_parts, queryIterations)`` where
          ``entity_key_parts`` is e.g. ``['a', 'b']`` (join with ``#`` for a literal prefix) or ``[]``.
        """
        remaining: Dict[str, Any] = dict(kwargs)

        tenantKey = remaining.pop('tenantKey', 'GLOBAL')
        remaining.pop('entityType', None)
        filters: List[Tuple[str, Any]] = remaining.pop('filters', [])

        recentDays = remaining.get('recentDays')
        if recentDays:
            dt = (helpers.localNow() - timedelta(days=int(recentDays))).isoformat()
            filters.append(('created', {'condition': 'gte', 'value': dt}))

        for opt in CacheDecorator._GET_DICT_OPTION_KEYS:
            remaining.pop(opt, None)

        meta = DbClientBase.CacheTypes.get(entityType) or {}
        key_specs: List[str] = list(meta.get('partitionKeys') or []) + list(meta.get('entityKeys') or [])

        prefix_parts: List[str, str] = []
        for spec in key_specs:
            spec = spec.strip()
            if not spec:
                continue
            if '/' in spec:
                alts = [a.strip() for a in spec.split('/') if a.strip()]
                keepLoop = False
                for a in alts:
                    if a in remaining and remaining.get(a) is not None:
                        keyVal = remaining.get(a)
                        if isinstance(keyVal, list) or isinstance(keyVal, set):
                            break
                        keepLoop = True
                        prefix_parts.append((a, str(remaining.get(a))))
                        break
                if keepLoop == False:
                    break
            else:
                if spec in remaining and remaining.get(spec) is not None:
                    keyVal = remaining.get(spec)
                    if isinstance(keyVal, list) or isinstance(keyVal, set):
                        break
                    prefix_parts.append((spec, str(remaining.get(spec))))
                else:
                    break

        splitFilterName = None
        for name, value in remaining.items():
            if value is None:
                continue
            if isinstance(value, dict) and 'condition' in value:
                filters.append((name, value))
            else:
                condition = 'eq'
                if name.startswith('from_'):
                    name = name.replace('from_', '')
                    condition = 'gte'
                    if isinstance(value, date):
                        value = datetime.combine(value, datetime.min.time()).replace(tzinfo=None)
                elif name.startswith('to_'):
                    name = name.replace('to_', '')
                    condition = 'lte'
                    if isinstance(value, date):
                        #convert date to datetime
                        value = datetime.combine(value, datetime.max.time()).replace(tzinfo=None)
                if isinstance(value, set):
                    value = list(value)
                if isinstance(value, list) and len(value) > 100:
                    splitFilterName = name
                    continue
                filters.append((name, {'condition': condition, 'value': value}))

        queryIterations = []
        if splitFilterName:
            for i in range(0, len(value), 100):
                queryIterations.append(filters.copy())
                queryIterations[len(queryIterations)-1].append((splitFilterName, {'condition': 'is_in', 'value': value[i:i+100]}))
        elif filters and len(filters) > 0:
            queryIterations.append(filters.copy())

        return entityType, tenantKey, prefix_parts, queryIterations

    def initialize(self, logger:Logger, cacheLogger:Logger, cacheService):
        from .cacheService import CacheService
        self.logger = logger
        self.cacheLogger = cacheLogger
        self.cacheService:CacheService = cacheService
        self.pk_separator = cacheService.pk_separator

    def generate_identifier(self, partitionKeys: list, entityKeys: list, *args, **kwargs):
        remaining: Dict[str, Any] = dict(kwargs)
        identifier = ''
        query_filters = {}
        for key, value in remaining.items():
            if key not in ['tenantKey', 'forceReload', 'onlyCache', 'value', 'ttlSeconds'] and key not in entityKeys:
                query_filters[key] = value
        for identifier_param in partitionKeys + entityKeys:
            if remaining.pop(identifier_param):
                if identifier:
                    identifier += ':'
                identifier += str(remaining.pop(identifier_param))  
        return identifier, query_filters
  
    def generate_cache_entity_identifier(self, partitionKeys: list, entityKeys: list, actualEntityKeys: list, queryIterations: list, *args, **kwargs) -> str:
        try:
            """Generate a unique cache key from method parameters"""
            remaining: Dict[str, Any] = dict(kwargs)
            #identifier, query_filters = self.generate_identifier(partitionKeys, entityKeys, *args, **kwargs)
            num_partition = len(partitionKeys)
            cache_identifier = ':'.join([str(value) for (key, value) in actualEntityKeys[:num_partition]])

            newQueryFilters = []
            if queryIterations:
                for queryIteration in queryIterations:
                    for key, value in queryIteration:
                        if key not in partitionKeys and key not in entityKeys:
                            newQueryFilters.append((key, value))
                    break

            if newQueryFilters and len(newQueryFilters) > 0:
                # Create a dictionary of all parameters
                params = {
                    #'args': args,
                    'filters': newQueryFilters
                }
                
                # Convert to JSON string for consistent hashing
                # sort_keys=True ensures consistent ordering across different Python versions
                params_str = json.dumps(params, sort_keys=True, default=str)

                # Generate hash - MD5 is deterministic: same input = same hash on all machines
                # Explicit UTF-8 encoding ensures consistency across different systems
                hash_object = hashlib.md5(params_str.encode('utf-8'))

                if cache_identifier:
                    return f"{cache_identifier}:{hash_object.hexdigest()}", queryIterations
                else:
                    return hash_object.hexdigest(), queryIterations

            if cache_identifier:
                cache_identifier += f':{self.pk_separator}'
            else:
                cache_identifier = f'{self.pk_separator}'
            pass

            return cache_identifier, newQueryFilters
        except Exception as ex:
            self.logger.error(f"Error generating cache entity identifier:", ex)
            return '', {}

    def set_cache(self, tenantKey: str, entityType: EntityType, cache_identifier: str, result: Any, query_filters: Dict[str, Any], ttl_seconds: int = None):
        ttl_seconds = ttl_seconds or DbClientBase.CacheTypes.get(entityType, {}).get('ttl', 3600)
        if query_filters:
            result_keys = list(result.keys()) if isinstance(result, dict) else []
            cached_value = {'keys': result_keys, 'filters': query_filters}
            self.cacheService._redis_cache_set(tenantKey=tenantKey, entityType=entityType, data=cached_value, identifier=cache_identifier, ttl_seconds=ttl_seconds)
        else:
            self.cacheService._redis_cache_set(tenantKey=tenantKey, entityType=entityType, data=result or {}, identifier=cache_identifier, ttl_seconds=ttl_seconds)

    def set_cache_batch(self, tenantKey: str, entityType: EntityType, cache_identifier: str, result: Any, ttl_seconds: int = None):
        ttl_seconds = ttl_seconds or DbClientBase.CacheTypes.get(entityType, {}).get('ttl', 3600)
        items = []
        for key, value in result.items():
            #cacheKey = self._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=f'{key}:AAA')
            identifier = f'{cache_identifier}:{key}' if cache_identifier else key
            cache_key = self.cacheService._get_cache_key(tenantKey=tenantKey, entityType=entityType, identifier=identifier)
            items.append({'key': cache_key, 'value': value, 'ttl_seconds': ttl_seconds})
        self.cacheService._redis_set_batch(items=items)

    @staticmethod
    def _detect_entity_key_filter(queryIterations: list, entityKeys: list) -> Optional[tuple]:
        """Return (field_name, [values]) if queryIterations has an is_in/eq filter on an entity key, else None."""
        if not queryIterations or not entityKeys:
            return None
        for name, filter_dict in (queryIterations[0] if queryIterations else []):
            if name in entityKeys and isinstance(filter_dict, dict):
                condition = filter_dict.get('condition')
                value = filter_dict.get('value')
                if condition == 'is_in' and isinstance(value, list):
                    return name, value
                if condition == 'eq':
                    return name, [value] if not isinstance(value, list) else value
        return None

    @staticmethod
    def _matches_filter(item_value: Any, condition: str, filter_value: Any) -> bool:
        """Mirror DynamoDB's Attr.not_exists() | Attr.<condition>() logic in Python."""
        if item_value is None:
            return True
        try:
            sv, sfv = str(item_value), str(filter_value)
            if condition == 'eq':       return sv == sfv
            if condition == 'neq':      return sv != sfv
            if condition == 'is_in':    return sv in [str(v) for v in (filter_value or [])]
            if condition == 'contains': return sfv in sv
            if condition == 'bw':       return sv.startswith(sfv)
            if condition in ('gte', 'lte', 'gt', 'lt'):
                try:
                    a, b = float(item_value), float(filter_value)
                except (ValueError, TypeError):
                    a, b = sv, sfv
                return {'gte': a >= b, 'lte': a <= b, 'gt': a > b, 'lt': a < b}[condition]
        except Exception:
            return True
        return True

    @staticmethod
    def _apply_filters_in_memory(result: dict, queryIterations: list, entityKeys: list) -> dict:
        """Filter result dict using non-entity-key conditions from queryIterations."""
        if not result or not queryIterations:
            return result
        filtered = {}
        for item_key, item_value in result.items():
            if not isinstance(item_value, dict):
                filtered[item_key] = item_value
                continue
            match = True
            for _filters in queryIterations:
                for name, filter_dict in _filters:
                    if not name or name in entityKeys:
                        continue
                    attr_val = item_value.get(name)
                    ok = (CacheDecorator._matches_filter(attr_val, filter_dict.get('condition'), filter_dict.get('value'))
                          if isinstance(filter_dict, dict)
                          else str(attr_val) == str(filter_dict))
                    if not ok:
                        match = False
                        break
                if not match:
                    break
            if match:
                filtered[item_key] = item_value
        return filtered

    def _extract_single_record(self, result: Any, partitionKeys: list, entityKeys: list, actualEntityKeys: list) -> Any:
        if not isinstance(result, dict):
            return result
        num_partition = len(partitionKeys)
        partition_key_parts = actualEntityKeys[:num_partition]
        entity_key_parts = actualEntityKeys[num_partition:]
        if False and not entity_key_parts:
            return result
        if bool(entityKeys) and len(entity_key_parts) == len(entityKeys):
            lookup_key = '#'.join([str(v) for (k, v) in entity_key_parts])
        else:
            lookup_key = '#'.join([str(v) for (k, v) in partition_key_parts])
        return result.get(lookup_key)

    def cache(self, entityType: EntityType, actionType: ActionType, identifierArgs: list=[]):
        """Decorator that automatically generates cache keys"""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    # Generate cache key
                    with self.cacheService._internal_lock:
                        remaining: Dict[str, Any] = dict(kwargs)
                        tenantKey: str = remaining.pop('tenantKey', 'GLOBAL')
                        forceReload: bool = remaining.pop('forceReload', False)
                        ttlSeconds = remaining.pop('ttlSeconds', None)
                        if 'ttlSeconds' in kwargs:
                            del kwargs['ttlSeconds']
                        filters: list = remaining.pop('filters', [])
                        expr = remaining.pop('expr', None)
                        remaining.pop('expr', None)
                        
                        cacheTypeMeta = DbClientBase.CacheTypes.get(entityType, {})
                        partitionKeys = cacheTypeMeta.get('partitionKeys', [])
                        entityKeys = cacheTypeMeta.get('entityKeys', [])
                        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=entityType, **kwargs)
                        cache_identifier, query_filters = self.generate_cache_entity_identifier(partitionKeys, entityKeys, _entityKeys, _queryIterations, *args, **kwargs)
                        partition_key_parts = _entityKeys[:len(partitionKeys)]
                        entity_key_parts = _entityKeys[len(partitionKeys):]                        
                        singleRecordResponse = bool(entityKeys) and len(entity_key_parts) == len(entityKeys) or len(entityKeys) == 0 and len(partition_key_parts) == len(partitionKeys)
                        excludeKeys = cacheTypeMeta.get('excludeKeys', [])

                        cacheLog = {
                            'actionType': str(actionType),
                            'entityType': str(entityType),
                            'cache_identifier': cache_identifier,
                            'query_filters': jsonHelper.save_to_json(data=query_filters),
                            'tenantKey': tenantKey,
                            'ttl_seconds': ttlSeconds,
                            'forceReload': forceReload,
                            #'onlyCache': onlyCache,
                            #'args': args,
                            'fromCache': True,
                            'value': None,
                            'count': -1
                        }
                        cacheLog = kwargs | cacheLog

                        if actionType in [ActionType.GET, ActionType.COUNT]:
                            entity_key_filter = CacheDecorator._detect_entity_key_filter(_queryIterations, entityKeys)
                            tournament_name_for_partition: Optional[str] = None
                            if entityType == EntityType.TOURNAMENTSGAMES and partitionKeys and len(_entityKeys) >= len(partitionKeys):
                                tournament_name_for_partition = str(_entityKeys[0][1])

                            if entity_key_filter and not forceReload:
                                # ----------------------------------------------------------
                                # Path 1: entity key is_in / eq
                                # Check individual cache keys; fetch only misses from DB
                                # (DB uses entity key FilterExpression for targeted query)
                                # ----------------------------------------------------------
                                _, requested_keys = entity_key_filter
                                num_partition = len(partitionKeys)
                                partition_vals = ':'.join([str(v) for (k, v) in _entityKeys[:num_partition]])
                                aaaa_id = f'{partition_vals}:{self.pk_separator}' if partition_vals else f'{self.pk_separator}'

                                result = {}
                                missing_keys = []
                                for key_val in requested_keys:
                                    rk = self.cacheService._get_cache_key(tenantKey, entityType, f'{aaaa_id}:{key_val}')
                                    val = self.cacheService._redis_get(rk)
                                    if val is None:
                                        missing_keys.append(key_val)
                                    elif bool(CacheDecorator._apply_filters_in_memory({str(key_val): val}, _queryIterations, entityKeys)):
                                        result[str(key_val)] = val

                                if missing_keys:
                                    cacheLog['fromCache'] = False
                                    db_result = func(*args, **kwargs)
                                    if isinstance(db_result, dict):
                                        self.set_cache_batch(tenantKey=tenantKey, entityType=entityType, cache_identifier=aaaa_id, result=db_result, ttl_seconds=ttlSeconds)
                                        if tournament_name_for_partition:
                                            self.cacheService.clear_tournament_games_partition_complete(tenantKey, tournament_name_for_partition)
                                        #self.set_cache(tenantKey=tenantKey, entityType=entityType, cache_identifier=aaaa_id, result=db_result, query_filters=[], ttl_seconds=ttlSeconds)
                                        result.update(db_result)

                                self.cacheLogger.info(cacheLog)
                                if singleRecordResponse:
                                    return self._extract_single_record(result, partitionKeys, entityKeys, _entityKeys)
                                return result

                            # ----------------------------------------------------------
                            # Paths 2 & 3: full-partition or hash-key flow
                            # ----------------------------------------------------------
                            tournament_partition_incomplete_skip_redis = (
                                entityType == EntityType.TOURNAMENTSGAMES
                                and actionType in (ActionType.GET, ActionType.COUNT)
                                and not singleRecordResponse
                                and bool(tournament_name_for_partition)
                                and cache_identifier.endswith(f':{self.pk_separator}')
                                and not self.cacheService.tournament_games_partition_cache_is_complete(tenantKey, tournament_name_for_partition)
                            )

                            if forceReload or not self.cacheService._is_cache_valid(tenantKey=tenantKey, entityType=entityType, identifier=cache_identifier):
                                forceReload = True
                                cacheLog['forceReload'] = forceReload

                            if not forceReload and not tournament_partition_incomplete_skip_redis:
                                result = self.cacheService._redis_cache_get(tenantKey=tenantKey, entityType=entityType, identifier=cache_identifier)
                                # Skip metadata-only hash-key records (stored for future two-step retrieval)
                                is_hash_metadata = isinstance(result, dict) and set(result.keys()) <= {'keys', 'filters'}
                                if result and not is_hash_metadata:
                                    # Path 2: warm AAAA partition — apply non-entity-key filters in-memory
                                    if cache_identifier.endswith(f':{self.pk_separator}') and _queryIterations:
                                        result = CacheDecorator._apply_filters_in_memory(result, _queryIterations, entityKeys)
                                    if singleRecordResponse:
                                        return self._extract_single_record(result, partitionKeys, entityKeys, _entityKeys)
                                    return result
                                elif 'value' in result and result['value'] is not None and (not isinstance(result['value'], list) and not isinstance(result['value'], dict) or len(result['value']) > 0):
                                    try:
                                        self.cacheLogger.info(cacheLog)
                                    except Exception as ex:
                                        self.logger.error(f"Error logging cache log:", ex)
                                    return result['value']

                            # Path 3: cold — call DB (FilterExpression applied server-side),
                            # store result (individual records for AAAA, hash metadata for filtered queries)
                            cacheLog['fromCache'] = False
                            result = func(*args, **kwargs)

                            if result is not None and isinstance(result, dict):    
                                self.set_cache_batch(tenantKey=tenantKey, entityType=entityType, cache_identifier=cache_identifier, result=result, ttl_seconds=ttlSeconds)
                            else:
                                self.logger.warning(f"Result is not a dict, setting cache failed for entityType: {entityType} and cache_identifier: {cache_identifier} result: {result}")
                                self.set_cache(tenantKey=tenantKey, entityType=entityType, cache_identifier=cache_identifier, result=result, query_filters=query_filters, ttl_seconds=ttlSeconds)
                            
                            if (
                                entityType == EntityType.TOURNAMENTSGAMES
                                and actionType in (ActionType.GET, ActionType.COUNT)
                                and not singleRecordResponse
                                and tournament_name_for_partition
                                and cache_identifier.endswith(f':{self.pk_separator}')
                            ):
                                self.cacheService.mark_tournament_games_partition_complete(tenantKey, tournament_name_for_partition, ttl_seconds=ttlSeconds)
                            #self.set_cache(tenantKey=tenantKey, entityType=entityType, cache_identifier=cache_identifier, result=result, query_filters=query_filters, ttl_seconds=ttlSeconds, single=False)

                            if actionType == ActionType.COUNT:
                                if result:
                                    filteredResult = [item for item in result.values() if expr(item)] if expr else result.values()
                                    count = len(filteredResult)
                                    cacheLog['count'] = count
                                    self.cacheLogger.info(cacheLog)
                                    return count
                                else:
                                    cacheLog['count'] = -1
                                    self.cacheLogger.warning(cacheLog)
                                    return -1

                            self.cacheLogger.info(cacheLog)
                            if singleRecordResponse:
                                return self._extract_single_record(result, partitionKeys, entityKeys, _entityKeys)
                            return result
                        
                        elif actionType == ActionType.SET:
                            # Execute function and cache result
                            cacheLog['fromCache'] = False
                            excludedKeyValues = {}
                            if excludeKeys:
                                for excludeKey in excludeKeys:
                                    value = kwargs.get('value')
                                    if value and excludeKey in value:
                                        excludedKeyValues[excludeKey] = value[excludeKey]
                                        del value[excludeKey]
                            result = func(*args, **kwargs)
                            if result is None:
                                result = (None, True)
                            if excludedKeyValues:
                                value = result[0]
                                if value:
                                    value = value | excludedKeyValues
                                    result = value, result[1]
                            invalidated = result[1]
                            jsonValue = jsonHelper.preJsonSetToDynamoDb(obj=result[0])#, excludeProps=[ 'updated', 'content_hash' ])
                            cacheLog['value'] = jsonValue
                            cacheLog['invalidated'] = invalidated
                            if invalidated:
                                num_partition = len(partitionKeys)
                                if num_partition > 0:
                                    expire_identifier = ':'.join([str(v) for (k, v) in _entityKeys[:num_partition]]) or None
                                    self.cacheService.expire_cache(tenantKey=tenantKey, entityType=entityType, identifier=expire_identifier)
                                else:
                                    # Static entity (no partition keys): update the specific cache entry
                                    entity_key_val = '#'.join([str(v) for (k, v) in _entityKeys])
                                    specific_id = f'{self.pk_separator}:{entity_key_val}' if entity_key_val else f'{self.pk_separator}'
                                    new_value = result[0]
                                    if new_value is not None:
                                        ttl = ttlSeconds or DbClientBase.CacheTypes.get(entityType, {}).get('ttl', 3600)
                                        self.cacheService._redis_cache_set(tenantKey=tenantKey, entityType=entityType, data=new_value, identifier=specific_id, ttl_seconds=ttl)

                            cacheLog['cache_identifier'] = cache_identifier
                            cacheLog['query_filters'] = jsonHelper.save_to_json(data=query_filters)
                            jsonValue = jsonHelper.preJsonSetToDynamoDb(obj=result)#, excludeProps=[ 'updated', 'content_hash' ])
                            cacheLog['value'] = jsonValue
                            self.cacheLogger.info(cacheLog)
                            return result
                        
                except Exception as ex:
                    self.logger.error(f"Error caching function:", ex)
                    return None
            return wrapper
        return decorator

cacheDecorator = CacheDecorator()
