import logging
import sys
import boto3
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime, timezone, timedelta
import os
from typing import Any, Dict, List, Optional, Tuple, Union
import hashlib
import json
import uuid
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db.dbClientBase import DbClientBase
from shared.db.cacheDecorator import CacheDecorator
from shared.logger import Logger
from shared.enumTypes import EntityType

class DynamodbClient(DbClientBase):
    def __init__(self, env, logger:Logger, dynamodbResource, dynamodbClient):
        try:
            super().__init__(env, logger)
            self.logDynamoDb = eval(os.getenv('logDynamoDb', 'False'))
            if self.logDynamoDb:
                self.dynamoDbLogger = Logger()
            self.dynamodbResource = dynamodbResource
            self.dynamodbClient = dynamodbClient
            self.tables = {}

            self.logger.info(f'DynamoDb Client starts...')

            self.init()

        except Exception as ex:
            self.logger.error(f'Error in DynamoDb init', ex)

    def init(self):
        self.cache = {}

        tables = [ tableName for tableName in self.dynamodbClient.list_tables()["TableNames"] if tableName.endswith(f'_{self.env}') ]

        for tableName in tables:
            tableObj = self.describeTable(tableName=tableName)
            self.tables[tableName] = tableObj

    def describeTable(self, tableName):
        response = self.dynamodbClient.describe_table(TableName=tableName)
        key_schema = response["Table"]["KeySchema"]
        keys = {key["KeyType"]: key["AttributeName"] for key in key_schema}
        table = self.dynamodbResource.Table(tableName)
        tableObj = { 'table': table, 'tenantKey': keys['HASH'], 'entityKey': keys.get('RANGE') }
        return tableObj
    
    def getTable(self, tableName):
        return self.tables[f'{tableName}_{self.env}']
                           
    def getKey(self, tableName, tenantKey, **entityKeys):
        table = self.getTable(tableName=tableName)
        tenantKeyCol = table['tenantKey']
        entityKeyCol = table.get('entityKey')
        
        key = { tenantKeyCol: tenantKey}
        if entityKeyCol and entityKeys:
            entityKey = '#'.join(str(v) for v in entityKeys.values())
            key[entityKeyCol] = entityKey
        return key

    def get_hash(self, value):
        dumps = jsonHelper.save_to_json(value)
        return hashlib.sha256(dumps.encode()).hexdigest()

    def valueChanged(self, value:dict):
        prevContentHash = value.get("content_hash")
        newValue = jsonHelper.preJsonSetToDynamoDb(obj=value, excludeProps=[ 'updated', 'content_hash' ])
        currentContentHash = self.get_hash(newValue)
        if not prevContentHash or prevContentHash != currentContentHash:
            return newValue, currentContentHash
        return newValue, None

    def put_item(self, table, value:dict):
        try:
            cleanedupValue = helpers.cleanUnpickleable(value)
            table.put_item(Item=cleanedupValue)
            return cleanedupValue
        except Exception as ex:
            self.logger.error(f'Error in DynamoDb put_item', ex)
            return None

    def set(self, tableName, value, tenantKey='GLOBAL', batchWriter=None, expiry=None, jsonDumps=False, **entityKeys):
        try:
            if jsonDumps:
                value = jsonHelper.save_to_json(value)

            now = helpers.localNow().isoformat()
            if not isinstance(value, dict):
                value = { 'value': value }
            value['created'] = value.get('created') or now
            # Add tenant metadata
            if tenantKey != 'GLOBAL':
                value['countryCode'] = tenantKey.split('#')[0]
                value['eventType'] = tenantKey.split('#')[1]
                value['season'] = tenantKey.split('#')[2]

            # If entityKeys are provided, add them to value and build entityKey
            entityKey = None
            if entityKeys:
                value.update(entityKeys)
                # Build entityKey from entityKeys values
                #GUY
                entityKey = '#'.join(str(v) for v in entityKeys.values() if v is not None)

            table = self.getTable(tableName=tableName)
            tenantKeyCol = table['tenantKey']
            entityKeyCol = table.get('entityKey')
            
            if tenantKeyCol == 'tenantKey':
                # Create tenant-aware partition key
                tenant_key = tenantKey
            else:
                tenant_key = entityKey
            value[tenantKeyCol] = tenant_key

            if entityKeyCol and entityKey:
                value[entityKeyCol] = entityKey
            newValue = None
            newContentHash = None
            try:
                newValue, newContentHash = self.valueChanged(value=value)
            except Exception as ex:
                self.logger.error(f'Error in DynamoDb valueChanged:', ex)
            if newContentHash:
                newValue['updated'] = now
                newValue['content_hash'] = newContentHash
                cleanedupValue = self.put_item(table=batchWriter or table['table'], value=newValue)
                if self.logDynamoDb:
                    auditLog = { 'table': tableName, 'tenantKey': tenant_key, 'entityKey': entityKey, 'value': cleanedupValue }
                    self.dynamoDbLogger.info(message=auditLog)
                newValue = jsonHelper.postJsonGetFromDynamoDb(obj=newValue)
                helpers.deep_merge_and_prune(target=value, updates=newValue)
                return value, True
            else:
                if self.logDynamoDb:
                    auditLog = { 'table': tableName, 'tenantKey': tenant_key, 'entityKey': entityKey, 'value': newValue, 'comment': 'no change' }
                    self.dynamoDbLogger.info(message=auditLog)
        
        except Exception as ex:
            self.logger.error(f'Error in DynamoDb set:', ex)

        return value, False

    def get(self, tableName, tenantKey='GLOBAL', jsonDumps=False, **entityKeys):
        try:
            key = self.getKey(tableName=tableName, tenantKey=tenantKey, **entityKeys)
            table = self.getTable(tableName=tableName)['table']
            value = table.get_item(Key=key, ConsistentRead=True)
            if value['ResponseMetadata']['HTTPStatusCode'] != 200:
                return None
            value = value.get('Item')
            value = jsonHelper.postJsonGetFromDynamoDb(value)
            if value and jsonDumps and value.get('value'):
                value = jsonHelper.load_from_json(value.get('value'))
            return value
        except Exception as ex:
            self.logger.error(f'Error in DynamoDb get:', ex)

    def getBatch(self, table, kwargs:dict=None):
        items = []
        last_evaluated_key = None
        
        while True:
            if last_evaluated_key:
                kwargs['ExclusiveStartKey'] = last_evaluated_key
            
            if kwargs:
                response = table['table'].query(**kwargs)
            else:
                response = table['table'].scan()
            batch_items = response.get('Items', [])
            items.extend(batch_items)
            
            # Check if there are more items
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break

        return items

    # Kwargs for DynamodbClient.getDict that are not DynamoDB key attributes
    _GET_DICT_OPTION_KEYS = frozenset({
        'jsonDumps', 'skipConversion', 'recentDays', 'asIsEntityKey', 'filters1',
    })

    def getDict(
        self,
        entityType: EntityType,
        tenantKey: str = 'GLOBAL',
        entityKeys: Optional[List[Tuple[str, str]]] = None,
        queryIterations: list = None,
        jsonDumps: bool = False,
        skipConversion: bool = False,
        recentDays: Any = None,
        asIsEntityKey: bool = False,
    ):
        try:
            table = self.getTable(tableName=str(entityType))
            meta = DbClientBase.CacheTypes.get(entityType) or {}
            num_partition = len(meta.get('partitionKeys') or [])
            key_condition = Key(table['tenantKey']).eq(tenantKey)

            partition_key_values = (entityKeys or [])[:num_partition]
            if partition_key_values:
                entityKeyPrefix = '#'.join(str(v) for (_, v) in partition_key_values)
                key_condition = key_condition & Key(table['entityKey']).begins_with(entityKeyPrefix)

            items = []
            for _filters in (queryIterations or [[]]):
                kwargs:dict = {
                    'KeyConditionExpression': key_condition
                }

                descendingSort = False
                # Optional filter expression
                filter_expr = Attr('nonexistsfield').not_exists()

                for filterName, filter in _filters:
                    if filterName:
                        if filter is not None:
                            if isinstance(filter, dict):
                                filterCondition = filter.get('condition')
                                filterValue = filter.get('value')
                                if isinstance(filterValue, set):
                                    filterValue = list(filterValue)
                                if isinstance(filterValue, list) and filterCondition == 'eq':
                                    filterCondition = 'is_in'
                                _filterValue = jsonHelper.preJsonSetToDynamoDb(obj=filterValue)
                                
                                if filterCondition == 'contains':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).contains(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'eq':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).eq(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'is_in':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).is_in(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'gte':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).gte(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'lte':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).lte(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'gt':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).gt(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'lt':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).lt(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'neq':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).ne(_filterValue))  # string "True" — adjust if it's a boolean
                                elif filterCondition == 'bw':
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).begins_with(_filterValue))  # string "True" — adjust if it's a boolean
                                else:
                                    filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).eq(_filterValue))  # string "True" — adjust if it's a boolean
                            else:
                                filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).eq(_filterValue))  # string "True" — adjust if it's a boolean
                        else:
                            filter_expr = filter_expr & (Attr(filterName).not_exists() | Attr(filterName).eq(_filterValue))  # string "True" — adjust if it's a boolean
                if recentDays:
                    dt = (helpers.localNow() - timedelta(days=recentDays)).isoformat()
                    filter_expr = filter_expr & Attr('created').gte(dt)
                    descendingSort = True
                if filter_expr:
                    kwargs['FilterExpression'] = filter_expr

                iterationItems = self.getBatch(table=table, kwargs=kwargs)
                items.extend(iterationItems)

            # Sort items by 'created' column if it exists
            if items and any('created' in item for item in items):
                items.sort(key=lambda x: x.get('created', ''), reverse=descendingSort)
            
            resultDict = {}
            for item in items:
                entityKeyValue = item[table['entityKey']] if table.get('entityKey') else None
                if not skipConversion:
                    value = jsonHelper.postJsonGetFromDynamoDb(item)
                else:
                    value = item
                if value and jsonDumps and value.get('value'):
                    value = jsonHelper.load_from_json(value.get('value'))
                
                # Strip partition key prefix from the sort key to produce the entity key
                if entityKeyValue and not asIsEntityKey and num_partition > 0:
                    parts = entityKeyValue.split('#')
                    if len(parts) > num_partition:
                        entityKeyValue = '#'.join(parts[num_partition:])
                
                resultDict[entityKeyValue] = value
            
            return resultDict
        except Exception as ex:
            self.logger.error(f'Error getting dict for {entityType}:', ex)
            return {}

    def setDict1(self, tableName, tenantKey, data, entityKeyColumns:list[str]):
        if isinstance(data, dict):
            table = self.getTable(tableName=tableName)
            entityKeyCol = table.get('entityKey')
            for key, value in data.items():
                if entityKeyCol and value.get(entityKeyCol):
                    self.set(tableName=tableName, tenantKey=tenantKey, value=value, **{entityKeyCol: value[entityKeyCol]})
                else:
                    entityColValue = ''
                    for entityKeyCol in entityKeyColumns:
                        if value.get(entityKeyCol):
                            entityColValue += f'#{value[entityKeyCol]}'
                        else:
                            entityColValue += f'#{key}'
                    entityColValue = entityColValue[1:]
                    self.set(tableName=tableName, tenantKey=tenantKey, value=value, **{entityKeyCol: entityColValue})

    def setDict(self, tableName, data, entityKeyColumns:list[str]):
        try:
            if not isinstance(data, dict):
                return
            
            table = self.getTable(tableName=tableName)
            entityKeyCol = table.get('entityKey')
            tenantKeyCol = table['tenantKey']
            now = helpers.localNow().isoformat()
            
            with table['table'].batch_writer() as batch:
                for key, value in data.items():
                    if not isinstance(value, dict):
                        value = {'value': value}
                    
                    # Prepare value similar to set method
                    value['created'] = value.get('created') or now
                    
                    # Add tenant metadata
                    tenantKey = value.get('tenantKey')
                    if tenantKey != 'GLOBAL':
                        value['countryCode'] = tenantKey.split('#')[0]
                        value['eventType'] = tenantKey.split('#')[1]
                        value['season'] = tenantKey.split('#')[2]
                    
                    # Build entity key
                    if entityKeyCol and value.get(entityKeyCol):
                        entityKeyValue = value[entityKeyCol]
                    else:
                        # Build entity key from entityKeyColumns
                        entityColValue = ''
                        for entityKeyColName in entityKeyColumns:
                            if value.get(entityKeyColName):
                                entityColValue += f'#{value[entityKeyColName]}'
                            else:
                                entityColValue += f'#{key}'
                        entityColValue = entityColValue[1:] if entityColValue else key
                        entityKeyValue = entityColValue
                    
                    # Set tenant key
                    if tenantKeyCol == 'tenantKey':
                        tenant_key = tenantKey
                    else:
                        tenant_key = entityKeyValue
                    value[tenantKeyCol] = tenant_key
                    
                    # Set entity key if applicable
                    if entityKeyCol and entityKeyValue:
                        value[entityKeyCol] = entityKeyValue
                    
                    # Check if value changed and update accordingly
                    newValue, newContentHash = self.valueChanged(value=value)
                    if newContentHash:
                        newValue['updated'] = now
                        newValue['content_hash'] = newContentHash
                    
                    # Put item using batch writer
                    cleanedupValue = helpers.cleanUnpickleable(newValue)
                    batch.put_item(Item=cleanedupValue)
                    pass
                    
        except Exception as ex:
            self.logger.error(f'Error setting dict for {tableName}:', ex)

    def processTableInBatches(self, tableName, process_func, batch_size=25, tenantKey=None):
        """
        Read full table in batches, process each batch with a lambda function, and batch write back.
        
        Args:
            tableName: Name of the table to process
            process_func: Lambda function that takes a list of items (dicts) and returns processed items
                         Signature: process_func(items: list[dict]) -> list[dict]
            batch_size: Number of items to process in each batch (default: 25)
            tenantKey: Optional tenant key to filter by. If None, processes entire table.
        
        Returns:
            Total number of items processed
        """
        try:
            now = helpers.localNow().isoformat()
            table = self.getTable(tableName=tableName)
            tenantKeyCol = table['tenantKey']
            entityKeyCol = table.get('entityKey')
            
            total_processed = 0
            last_evaluated_key = None
            
            self.logger.info(f'Starting batch processing for table: {tableName}')
            
            id = None

            while True:
                # Scan or query the table
                scan_kwargs = {'Limit': batch_size}
                if last_evaluated_key:
                    scan_kwargs['ExclusiveStartKey'] = last_evaluated_key
                
                if tenantKey:
                    # Query by tenant key
                    key_condition = Key(tenantKeyCol).eq(tenantKey)
                    query_kwargs = {'KeyConditionExpression': key_condition, 'Limit': batch_size}
                    if last_evaluated_key:
                        query_kwargs['ExclusiveStartKey'] = last_evaluated_key
                    response = table['table'].query(**query_kwargs)
                else:
                    # Scan entire table
                    response = table['table'].scan(**scan_kwargs)
                
                batch_items = response.get('Items', [])
                
                if not batch_items:
                    break
                
                # Convert DynamoDB items to Python dicts
                converted_items = []
                for item in batch_items:
                    id = item
                    converted_item = jsonHelper.postJsonGetFromDynamoDb(item)
                    converted_items.append(converted_item)
                
                # Process items using the provided function
                processed_items = process_func(converted_items)
                
                # Ensure processed_items is a list
                if not isinstance(processed_items, list):
                    self.logger.warning(f'process_func did not return a list, skipping batch')
                    last_evaluated_key = response.get('LastEvaluatedKey')
                    if not last_evaluated_key:
                        break
                    continue
                
                # Write processed items back using batch_writer
                if processed_items:
                    with table['table'].batch_writer() as batch:
                        for processed_item in processed_items:
                            # Ensure keys are preserved
                            key = {tenantKeyCol: processed_item[tenantKeyCol]}
                            if entityKeyCol and processed_item.get(entityKeyCol):
                                key[entityKeyCol] = processed_item[entityKeyCol]
                            
                            # Convert back to DynamoDB format
                            id = processed_item

                            newValue, newContentHash = self.valueChanged(value=processed_item)
                            if newContentHash:
                                newValue['updated'] = now
                                newValue['content_hash'] = newContentHash
                                cleanedupValue = self.put_item(table=batch, value=newValue)

                    total_processed += len(processed_items)
                    self.logger.info(f'Processed batch of {len(processed_items)} items (total: {total_processed})')
                
                # Check if there are more items
                last_evaluated_key = response.get('LastEvaluatedKey')
                if not last_evaluated_key:
                    break
            
            self.logger.info(f'Completed batch processing for table: {tableName}. Total items processed: {total_processed}')
            return total_processed
            
        except Exception as ex:
            self.logger.error(f'Error processing table {tableName} in batches: {id}', ex)
            return total_processed

    def exists(self, tableName, tenantKey, **entityKeys):
        # Use tenant-aware key generation
        result = self.get(tableName=tableName, tenantKey=tenantKey, **entityKeys)
        return result != None

    def rename(self, oldKey, newKey):
        pass

    def delete(self, tableName, tenantKey, **entityKeys):
        table = self.getTable(tableName=tableName)
        # Use tenant-aware key generation
        key = self.getKey(tableName=tableName, tenantKey=tenantKey, **entityKeys)

        response = table['table'].delete_item(
            Key=key
        )
        pass

    def deleteByFilter(self, tableName, tenantKey, filters, **entityKeys):
        items = self.getDict(tableName=tableName, tenantKey=tenantKey, filters=filters, **entityKeys)
        for entityKey in items:
            self.delete(tableName=tableName, tenantKey=tenantKey, **entityKeys)

    def truncate(self, tableName):
        table = self.getTable(tableName=tableName)
        tenantKeyCol = table['tenantKey']
        entityKeyCol = table.get('entityKey')

        while True:
            response = table['table'].scan(Limit=25)  # Fetch 25 items at a time
            items = response.get('Items', [])

            if not items:
                break  # Stop if no more items

            with table['table'].batch_writer() as batch:
                for item in items:
                    key = {tenantKeyCol: item[tenantKeyCol]}
                    if entityKeyCol:
                        key[entityKeyCol] = item[entityKeyCol]
                    batch.delete_item(Key=key)  # Adjust if SortKey exists

    def getFields(self, tenantKey, fieldName=None, contains_filterText=None):
        try:
            _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.FIELDS, tenantKey=tenantKey, fieldName=fieldName, contains_filterText=contains_filterText)
            value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
            return value
        except Exception as ex:
            self.logger.error(f'Error getting fields for {tenantKey}:', ex)
            return {}

    def setField(self, tenantKey, fieldName, value):
        return self.set(tableName='fields', tenantKey=tenantKey, value=value, fieldName=fieldName)

    def getRoles(self, tenantKey, roleName=None, contains_roleName=None,**entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.ROLES, tenantKey=tenantKey, roleName=roleName, contains_roleName=contains_roleName)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setRole(self, tenantKey, roleName, value):
        return self.set(tableName='roles', tenantKey=tenantKey, value=value, roleName=roleName)

    def getRules(self, tenantKey, ruleName=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.RULES, tenantKey=tenantKey, ruleName=ruleName)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setRule(self, tenantKey, ruleName, value):
        return self.set(tableName='rules', tenantKey=tenantKey, value=value, ruleName=ruleName)

    def getSeasons(self, season=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.SEASONS, season=season)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setSeason(self, season, value):
        return self.set(tableName='seasons', value=value, season=season)

    def getSections(self, tenantKey, sectionName=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.SECTIONS, tenantKey=tenantKey, sectionName=sectionName)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setSection(self, tenantKey, sectionName, value):
        return self.set(tableName='sections', tenantKey=tenantKey, value=value, sectionName=sectionName)

    def getTournaments(self, tenantKey, tournamentName=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.TOURNAMENTS, tenantKey=tenantKey, tournamentName=tournamentName)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setTournament(self, tenantKey, tournamentName, value):
        return self.set(tableName='tournaments', tenantKey=tenantKey, value=value, tournamentName=tournamentName)

    def getLeagueTables(self, tenantKey, tournamentName,  **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.LEAGUETABLES, tenantKey=tenantKey, tournamentName=tournamentName)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations, jsonDumps=True)
        return value

    def setLeagueTable(self, tenantKey, tournamentName, value):
        return self.set(tableName='leagueTables', tenantKey=tenantKey, value=value, jsonDumps=True, tournamentName=tournamentName)

    def getTournamentGames(self, tenantKey, tournamentName, gamePk=None, nonArchivedOnly=False, filters=[], **entityKeys):
        filters = []
        if nonArchivedOnly:
            from_date = helpers.localNow().date().isoformat()
            filters.append(('date', {'condition': 'gte', 'value': from_date }))
            #filters.append(('archived', False))
            filters.append(('state', {'condition': 'neq', 'value': 'archived' }))
        filters.append(('state', {'condition': 'neq', 'value': 'removed' }))
        filters.append(('state', {'condition': 'neq', 'value': 'canceled' }))
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.TOURNAMENTSGAMES, tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, filters=filters)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value
    
    def setTournamentGame(self, tenantKey, tournamentName, gamePk, value):
        currentValue = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
        if value and 'id' in value:
            referenceValue = {'tenantKey': tenantKey, 'gameId': value['id'], 'tournamentName': tournamentName, 'gamePk': gamePk}
            self.setReferenceId(target='tournamentGames', id=value['id'], value=referenceValue)

        try:
            if currentValue:
                historyValue = self.get(tableName='tournamentGamesHistory', tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
                if historyValue is None:
                    historyValue = {}
                historyValue['history'] = historyValue.get('history', {})
                historyValue['history'][jsonHelper.datetime_to_strfull(helpers.localNow())] = helpers.safeClone(value)
                top_n = 10
                if len(historyValue['history']) > top_n:
                    sortedItems = sorted(historyValue['history'].items())
                    topItems = sortedItems[:top_n]
                    historyValue['history'] = dict(topItems)
                self.set(tableName='tournamentGamesHistory', tenantKey=tenantKey, value=historyValue, tournamentName=tournamentName, gamePk=gamePk)
        except Exception as ex:
            self.logger.error(f'setTournamentGameHistory', ex)
        
        return self.set(tableName='tournamentGames', tenantKey=tenantKey, value=value, tournamentName=tournamentName, gamePk=gamePk)

    def archiveTournamentGame(self, tenantKey, tournamentName, gamePk):
        value = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
        if value:
            changed = self.set(tableName='tournamentGamesArchived', tenantKey=tenantKey, value=value, tournamentName=tournamentName, gamePk=gamePk)
            self.delete(tableName='tournamentGames', tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)

    def deleteTournamentGame(self, tenantKey, tournamentName, gamePk):
        self.delete(tableName='tournamentGames', tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)

    def getTournamentGamesArchived(self, tenantKey, tournamentName, gamePk=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.TOURNAMENTGAMESARCHIVED, tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value
    
    def getReferee(self, tenantKey=None, mobileNo=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREES, tenantKey=tenantKey, mobileNo=mobileNo)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def getRefereeProperties(self, tenantKey='GLOBAL', mobileNo=None, propertyName=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREES, tenantKey=tenantKey, mobileNo=mobileNo)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        if mobileNo and propertyName and value:
            value = list(value.values())[0].get(propertyName)
        return value

    def setRefereeProperties(self, tenantKey, mobileNo, value, propertyName=None):
        item = value
        if propertyName:
            item = self.getReferee(tenantKey=tenantKey, mobileNo=mobileNo)
            if not item:
                return
            item = item[mobileNo]
            item[propertyName] = value
        return self.set(tableName='referees', tenantKey=tenantKey, value=item, mobileNo=mobileNo)

    def getRefereeAvailaiblity(self, mobileNo:str, from_date:datetime=None, to_date:datetime=None):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREEAVAILABILITY, mobileNo=mobileNo, from_date=from_date, to_date=to_date)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations, skipConversion=True)
        return value

    def setRefereeAvailaiblity(self, mobileNo:str, value):
        updated = False
        for date, availability in value.items():
            availability['mobileNo'] = mobileNo
            availability['date'] = date
            result = self.set(tableName='refereeAvailability', value=availability, mobileNo=mobileNo, date=date)
            if result[1]:
                updated = True
        return updated
        #return self.setDict(tableName='refereeAvailability', data=value, entityKeyColumns=entityKeyColumns)

    def getClientIdentifier(self, clientIdentifier, from_created: datetime = None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.CLIENTIDENTIFIERS, tenantKey='GLOBAL', clientIdentifier=clientIdentifier, from_created=from_created)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        #self.logger.info(f"getClientIdentifier clientIdentifier: {clientIdentifier} value: {value}")
        return value

    def setClientIdentifier(self, clientIdentifier, sessionIdentifier, pushSubscription=None, mobileNo=None, userAgent=None, platform=None, status=None):
        value = self.getClientIdentifier(clientIdentifier)
        if isinstance(value, dict) and value.get(clientIdentifier):
            value = value[clientIdentifier]
            value['sessionIdentifier'] = sessionIdentifier
            value['pushSubscription'] = pushSubscription or value['pushSubscription']
            value['mobileNo'] = mobileNo or value['mobileNo']
            value['userAgent'] = userAgent or value['userAgent']
            value['platform'] = platform or value['platform']
        else:
            value = {
                'sessionIdentifier': sessionIdentifier,
                'pushSubscription': pushSubscription,
                'mobileNo': mobileNo,
                'status': status,
                'userAgent': userAgent,
                'platform': platform,
                'whatsappUuid': str(uuid.uuid5(uuid.NAMESPACE_URL, clientIdentifier))
            }
        #self.logger.info(f"setClientIdentifier clientIdentifier: {clientIdentifier} mobileNo: {mobileNo} value :{value}")
        return self.set(tableName='clientIdentifiers', value=value, clientIdentifier=clientIdentifier)

    def getRefereeGames(self, tenantKey, refId, gamePk=None, includeArchived=False, includeRemoved=False, includeCanceled=False, from_date:datetime = None, to_date:datetime = None, from_created:datetime = None, to_created:datetime = None, **entityKeys):
        filters = []
        if includeArchived == False:
            filters.append(('state', {'condition': 'neq', 'value': 'archived' }))
        if includeRemoved == False:
            filters.append(('state', {'condition': 'neq', 'value': 'removed' }))
        if includeCanceled == False:
            filters.append(('state', {'condition': 'neq', 'value': 'canceled' }))
        entityType, tenantKey, entityKeys, queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREEGAMES, tenantKey=tenantKey, refId=refId, gamePk=gamePk, filters=filters, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
        value = self.getDict(entityType=entityType, tenantKey=tenantKey, entityKeys=entityKeys, queryIterations=queryIterations)
        return value

    def getRefereeGamesNew(self, tenantKey, mobileNo, gamePk=None, includeArchived=False, includeRemoved=False, includeCanceled=False, from_date:datetime = None, to_date:datetime = None, from_created:datetime = None, to_created:datetime = None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREEGAMES, tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, from_date=from_date, to_date=to_date, from_created=from_created, to_created=to_created)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setRefereeGame(self, tenantKey, refId, gamePk, value):
        gameDetail = None
        if value.get('gameDetail'):
            gameDetail = value['gameDetail']
            del value['gameDetail']
            
        result = self.set(tableName='refereeGames', tenantKey=tenantKey, value=value, refId=refId, gamePk=gamePk)
        if gameDetail:
            value['gameDetail'] = gameDetail

        return result

    def setRefereeGameNew(self, tenantKey, mobileNo, gamePk, value):
        gameDetail = None
        if value.get('gameDetail'):
            gameDetail = value['gameDetail']
            del value['gameDetail']
            
        result = self.set(tableName='refereeGames', tenantKey=tenantKey, value=value, mobileNo=mobileNo, gamePk=gamePk)
        if gameDetail:
            value['gameDetail'] = gameDetail

        return result

    def removeRefereeGame(self, tenantKey, refId, gamePk):
        value = self.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
        if value:
            self.set(tableName='refereeGamesRemoved', value=value, refId=refId, gamePk=gamePk)
            self.delete(tableName='refereeGames', tenantKey=tenantKey, refId=refId, gamePk=gamePk)

    def removeRefereeGameNew(self, tenantKey, mobileNo, gamePk):
        value = self.getRefereeGamesNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
        if value:
            self.set(tableName='refereeGamesRemoved', value=value, mobileNo=mobileNo, gamePk=gamePk)
            self.delete(tableName='refereeGames', tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)

    def archiveRefereeGame(self, tenantKey, refId, gamePk):
        value = self.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=gamePk)
        if value:
            self.set(tableName='refereeGamesArchived', tenantKey=tenantKey, value=value, refId=refId, gamePk=gamePk)
            self.delete(tableName='refereeGames', tenantKey=tenantKey, refId=refId, gamePk=gamePk)

    def archiveRefereeGameNew(self, tenantKey, mobileNo, gamePk):
        value = self.getRefereeGames(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)
        if value:
            self.set(tableName='refereeGamesArchived', tenantKey=tenantKey, value=value, mobileNo=mobileNo, gamePk=gamePk)
            self.delete(tableName='refereeGames', tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)

    def getRefereeReviews(self, tenantKey, refId=None, gamePk=None, removed=False, from_date=None, to_date=None, **entityKeys):
        filters = []
        if removed:
            filters.append(('state', {'condition': 'neq', 'value': 'removed' }))
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREEREVIEWS, tenantKey=tenantKey, refId=refId, gamePk=gamePk, filters=filters, from_date=from_date, to_date=to_date)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def getRefereeReviewsNew(self, tenantKey, mobileNo, gamePk=None, removed=False, from_date=None, to_date=None, **entityKeys):
        filters = []
        if removed:
            filters.append(('state', {'condition': 'neq', 'value': 'removed' }))
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREEREVIEWS, tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk, filters=filters, from_date=from_date, to_date=to_date)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setRefereeReview(self, tenantKey, refId, gamePk, value):
        return self.set(tableName='refereeReviews', tenantKey=tenantKey, value=value, refId=refId, gamePk=gamePk)

    def setRefereeReviewNew(self, tenantKey, mobileNo, gamePk, value):
        return self.set(tableName='refereeReviews', tenantKey=tenantKey, value=value, mobileNo=mobileNo, gamePk=gamePk)

    def removeRefereeReview(self, tenantKey, refId, gamePk):
        value = self.getRefereeReviews(refId, gamePk)
        if value:
            #self.set('refereeGamesRemoved', value, refId, gamePk)
            self.delete(tableName='refereeReviews', tenantKey=tenantKey, refId=refId, gamePk=gamePk)

    def removeRefereeReviewNew(self, tenantKey, mobileNo, gamePk):
        value = self.getRefereeReviewsNew(mobileNo, gamePk)
        if value:
            #self.set('refereeGamesRemoved', value, refId, gamePk)
            self.delete(tableName='refereeReviews', tenantKey=tenantKey, mobileNo=mobileNo, gamePk=gamePk)

    def getRefereeTemplates(self, tenantKey, mobileNo, action:str = None, msgSid:str = None, status:str = None, from_created: datetime = None, to_created: datetime = None, from_updated: datetime = None, to_updated: datetime = None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREETEMPLATES, tenantKey=tenantKey, mobileNo=mobileNo, action=action, msgSid=msgSid, status=status, from_created=from_created, to_created=to_created, from_updated=from_updated, to_updated=to_updated)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setRefereeTemplate(self, tenantKey, mobileNo, msgSid, value):
        return self.set(tableName='refereeTemplates', tenantKey=tenantKey, value=value, mobileNo=mobileNo, msgSid=msgSid)

    def getRefereeMessages(self, mobileNo, direction, msgSid=None, recentDays=None, from_created=None, to_created=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREEMESSAGES, mobileNo=mobileNo, direction=direction, msgSid=msgSid, recentDays=recentDays, from_created=from_created, to_created=to_created)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations, recentDays=recentDays)
        return value

    def setRefereeMessage(self, mobileNo, direction, msgSid, value):
        return self.set(tableName='refereeMessages', value=value, mobileNo=mobileNo, direction=direction, msgSid=msgSid)

    def getGameDetail(self, game:dict, **entityKeys):
        tenantKey = game.get('tenantKey')
        tournamentName = game.get('tournamentName')
        gamePk = game.get('gamePk')
        if not gamePk:
            return None
        gameDetail = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, **entityKeys)        
        return gameDetail

    def getGameDetailById(self, gameId:str, **entityKeys):
        reference = self.getReferenceId(target='tournamentGames', id=gameId)
        if reference is None:
            return None
        tenantKey = reference.get('tenantKey')
        tournamentName = reference.get('tournamentName')
        gamePk = reference.get('gamePk')
        if gamePk is None:
            return None
        gameDetail = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, **entityKeys)        
        return gameDetail

    def getMessage(self, msgSid, **entityKeys):
        value = self.get(tableName='messages', msgSid=msgSid, **entityKeys)
        return value

    def setMessage(self, msgSid, value, **entityKeys):
        return self.set(tableName='messages', value=value, msgSid=msgSid, **entityKeys)

    def getKeyVal(self, key, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.KEYVAL, key=key)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations, jsonDumps=True)
        return value

    def setKeyVal(self, key, value):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.KEYVAL, key=key)
        return self.set(tableName=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations, value=value, jsonDumps=True)

    def getPositionUpdates(self, mobileNo, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.POSITIONUPDATES, mobileNo=mobileNo)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setPositionUpdate(self, mobileNo, timestamp, value):
        result = self.set(tableName='positionUpdates', value=value, mobileNo=mobileNo, timestamp=timestamp)
        return result

    def getRefereeLocations(self, mobileNo, timestamp=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFEREELOCATIONS, mobileNo=mobileNo, timestamp=timestamp)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setRefereeLocation(self, mobileNo, timestamp, value):
        result = self.set(tableName='refereeLocations', mobileNo=mobileNo, timestamp=timestamp, value=value)
        return result

    def setInvocation(self, tenantKey, invocationId, value, **entityKeys):
        return self.set(tableName='lambdaInvocationsTracking', tenantKey=tenantKey, value=value, invocationId=invocationId, **entityKeys)

    def getReferenceId(self, target:str, id:str=None, **entityKeys):       
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.REFERENCEIDS, tenantKey='GLOBAL', target=target, id=id)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations, jsonDumps=True)
        return value

    def setReferenceId(self, target:str, id:str, value, **entityKeys):
        return self.set(tableName='referenceIds', tenantKey='GLOBAL', value=value, jsonDumps=True, target=target, id=id, **entityKeys)

    def getNotifications(self, tenantKey:str, target:str, id:str=None, notificationType:str=None, to:str=None, timestamp:int=None, status:str=None, from_created:datetime=None, to_created:datetime=None, from_updated:datetime=None, to_updated:datetime=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.NOTIFICATIONS, tenantKey=tenantKey, target=target, id=id, notificationType=notificationType, to=to, timestamp=timestamp, status=status, from_created=from_created, to_created=to_created, from_updated=from_updated, to_updated=to_updated)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def setNotifications(self, tenantKey:str, target:str, id:str, notificationType:str, to:str, timestamp:int, value, **entityKeys):
        return self.set(tableName='notifications', tenantKey=tenantKey, value=value, target=target, id=id, notificationType=notificationType, to=to, timestamp=timestamp, **entityKeys)

    def getDocuments(self, tenantKey:str):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.DOCUMENTS, tenantKey=tenantKey)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def getTenants(self):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.TENANTS, tenantKey='GLOBAL')
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value

    def getPolls(self, pollId=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.POLLS, tenantKey='GLOBAL', pollId=pollId)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value or {}

    def setPoll(self, pollId, value=None):
        return self.set(tableName='polls', pollId=pollId, value=value)
    
    def getPollVotes(self, pollId, mobileNo=None, questionId=None, **entityKeys):
        _entityType, _tenantKey, _entityKeys, _queryIterations = CacheDecorator.getEntityKeysAndFilters(entityType=EntityType.POLLVOTES, tenantKey='GLOBAL', pollId=pollId, mobileNo=mobileNo, questionId=questionId)
        value = self.getDict(entityType=_entityType, tenantKey=_tenantKey, entityKeys=_entityKeys, queryIterations=_queryIterations)
        return value or {}
    
    def setPollVote(self, pollId=None, mobileNo=None, questionId=None, value=None):
        return self.set(tableName='pollVotes', pollId=pollId, mobileNo=mobileNo, questionId=questionId, value=value)

    def recreateTablesLocally(db, fromSuffix, toSuffix):
        # Fetch all table names from AWS
        from_tables = [ tableName.rstrip(fromSuffix) for tableName in db.list_tables()["TableNames"] if tableName.endswith(fromSuffix) ]

        # Function to fetch table schema
        def get_table_schema(table_name):
            response = db.describe_table(TableName=f'{table_name}{fromSuffix}')
            return response["Table"]

        # Function to create table in Local DynamoDB
        def create_local_table(table_schema):
            try:
                table_name = table_schema["TableName"].rstrip(fromSuffix)
                key_schema = table_schema["KeySchema"]
                attribute_definitions = table_schema["AttributeDefinitions"]
                billing_mode = table_schema.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")

                create_params = {
                    "TableName": f'{table_name}{toSuffix}',
                    "KeySchema": key_schema,
                    "AttributeDefinitions": attribute_definitions,
                    "BillingMode": billing_mode
                }

                # Add ProvisionedThroughput for Provisioned mode
                if billing_mode == "PROVISIONED":
                    create_params["ProvisionedThroughput"] = {
                        "ReadCapacityUnits": table_schema["ProvisionedThroughput"]["ReadCapacityUnits"],
                        "WriteCapacityUnits": table_schema["ProvisionedThroughput"]["WriteCapacityUnits"]
                    }

                # Add Global Secondary Indexes (GSI) if present
                if "GlobalSecondaryIndexes" in table_schema:
                    create_params["GlobalSecondaryIndexes"] = [
                        {
                            "IndexName": gsi["IndexName"],
                            "KeySchema": gsi["KeySchema"],
                            "Projection": gsi["Projection"],
                            "ProvisionedThroughput": gsi["ProvisionedThroughput"]
                            if billing_mode == "PROVISIONED" else {}
                        }
                        for gsi in table_schema["GlobalSecondaryIndexes"]
                    ]

                # Create table locally
                print(f"Creating table: {table_name} in DynamoDB")

                jsonHelper.save_to_file(obj=create_params, fileName=f'create_dynamodb_table_{table_name}.json')

                db.create_table(**create_params)
                print(f"Table {table_name} created successfully!")
            except Exception as ex:
                logging.error(f"Error creating table {table_name}:", ex)

        # Process each table
        for table in from_tables:
            schema = get_table_schema(tableName=table)
            create_local_table(tableSchema=schema)

        print("All tables have been migrated to Local DynamoDB.")

    def importReminders(self):
        for refId in self.getReferee().keys():
            for gamePk, refereeGame in self.getRefereeGames(refId=refId).items():
                reminders = refereeGame['reminders']
                for reminderId, reminder in reminders.items():
                    self.setRefGameActions(refId, gamePk, f'reminder_{reminderId}', reminder)

        for tournamentName in self.getTournaments().keys():
            for gamePk, tournamentGame in self.getTournamentGames(tournamentName=tournamentName).items():
                reminders = tournamentGame['reminders']
                for reminderId, reminder in reminders.items():
                    self.setGameActions(gamePk, f'reminder_{reminderId}', reminder)

    def updateReferenceGameIds(self, tenantKey):
        now = helpers.localNow()
        for tournamentName in self.getTournaments(tenantKey=tenantKey).keys():
            tournamentGames = self.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName)
            for gamePk, tournamentGame in tournamentGames.items():
                if 'נערים' not in gamePk or 'הפועל ניר רמה' not in gamePk or 'איחוד בני בקה' not in gamePk:
                    continue
                target = 'tournamentGames'
                gameId = tournamentGame['id']
                value = {'tenantKey': tenantKey, 'gameId': gameId, 'tournamentName': tournamentGame['tournamentName'], 'gamePk': gamePk}
                self.setReferenceId(target=target, id=gameId, value=value)

    def updateRefereeGamesArchivedRemoved(self):
        now = helpers.localNow()

        referees = self.getReferee()
        for refId in referees:
            if False and refId != '7161':
                continue
            refereeGames = self.getRefereeGames(refId=refId)
            for gamePk, refereeGame in refereeGames.items():
                if 'state' not in refereeGame:
                    refereeGame['state'] = 'active'
                if refereeGame['archived']:
                    refereeGame['state'] = 'archived'
                elif refereeGame['removed']:
                    refereeGame['state'] = 'removed'
                elif refereeGame['canceled']:
                    refereeGame['state'] = 'canceled'
                self.setRefereeGame(refId=refId, gamePk=gamePk, value=refereeGame)

    def insert_into_table(self, data, table_name, batch_size=25, recordconvertFunc=None):
        try:
            if isinstance(data, dict):
                data = list(data.values())

            if not isinstance(data, list):
                print(f"❌ Invalid data format. Expected list, got {type(data)}")
                return False
            
            print(f"📊 Found {len(data)} items to import")
            
            # Get the table
            table = self.dynamodbResource.Table(table_name)
            
            # Process items in batches
            imported_count = 0
            skipped_count = 0
            error_count = 0
            
            for i in range(0, len(data), batch_size):
                batch = data[i:i + batch_size]
                batch_items = []
                
                for item in batch:
                    try:
                        # Add tenant metadata if not present
                        if isinstance(item, dict):
                            if 'tenantKey' in item:
                                item['countryCode'] = item['tenantKey'].split('#')[0]
                                item['eventType'] = item['tenantKey'].split('#')[1]
                                item['season'] = item['tenantKey'].split('#')[2]
                        
                        if recordconvertFunc:
                            item = recordconvertFunc(item)

                        # Clean up the item for DynamoDB
                        cleaned_item = helpers.cleanUnpickleable(item)
                        batch_items.append(cleaned_item)
                        
                    except Exception as e:
                        print(f"    -> Error processing item:", e)
                        error_count += 1
                
                if batch_items:
                    try:
                        # Write batch to DynamoDB
                        with table.batch_writer(overwrite_by_pkeys=['tenantKey', 'entityKey'] if True else None) as batch:
                            for item in batch_items:
                                batch.put_item(Item=item)
                        
                        imported_count += len(batch_items)
                        print(f"    -> Imported batch {i//batch_size + 1}: {len(batch_items)} items")
                        
                    except Exception as e:
                        print(f"    -> Error writing batch {i//batch_size + 1}:", e)
                        error_count += len(batch_items)
            
            print(f"✅ Import completed for '{table_name}'")
            print(f"   📥 Imported: {imported_count} items")
            print(f"   ⏭️  Skipped: {skipped_count} items")
            print(f"   ❌ Errors: {error_count} items")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to import table '{table_name}':", e)
            return False

    def moveRefereeGamesArchivedRemoved(self):
        now = helpers.localNow()

        '''
        archivedRefereeGames = self.getDict(tableName='refereeGamesArchived', skipConversion=True, season='2024-25')
        l = len(archivedRefereeGames.keys())        
        self.insert_into_table(data=archivedRefereeGames, table_name='refereeGames_prod', batch_size=25, \
            recordconvertFunc=lambda x: {'archived': 'True', **x, 'updated': now.isoformat()})
        
        removedRefereeGames = self.getDict(tableName='refereeGamesRemoved', skipConversion=True, season='2024-25')
        l = len(removedRefereeGames.keys())        
        self.insert_into_table(data=removedRefereeGames, table_name='refereeGames_prod', batch_size=25, \
            recordconvertFunc=lambda x: {'removed': 'True', **x, 'updated': now.isoformat()})
        '''
        pass
        archivedTournamentGames = self.getDict(tableName='tournamentGamesArchived', skipConversion=True, season='2024-25')
        historyTournamentGames = self.getDict(tableName='tournamentGamesHistory', skipConversion=True, season='2024-25')
        l = len(archivedTournamentGames.keys())   
        gamePk = 'ליגת העל לנוערבני סכנין - הפועל חדרה27'
        archivedTournamentGame = archivedTournamentGames.get(gamePk)
        historyTournamentGame = historyTournamentGames.get(gamePk)
        #archivedTournamentGames=[archivedTournamentGame]
        self.insert_into_table(data=archivedTournamentGames, table_name='tournamentGames_prod', batch_size=25, \
            recordconvertFunc=lambda x: {'archived': 'True', 'removed': 'False', **x, 'updated': now.isoformat()})
        pass
    
    def export_all_tables_to_s3(self, bucket_name, table_suffix=""):
        """
        Finds all DynamoDB tables and initiates an export-to-S3 job for each one.
        Handles tables with and without Point-in-Time Recovery enabled.
        """
        print(f"Starting export process for tables with prefix '{table_suffix}'...")
        
        try:
            # Get a list of all tables
            paginator = self.dynamodbClient.get_paginator('list_tables')
            for page in paginator.paginate():
                for table_name in page['TableNames']:
                    if table_name.endswith(table_suffix):
                        print(f"Found table: {table_name}. Checking PITR status...")
                        
                        # Check if Point-in-Time Recovery is enabled
                        try:
                            table_info = self.dynamodbClient.describe_table(TableName=table_name)
                            pitr_enabled = table_info['Table'].get('PointInTimeRecoveryDescription', {}).get('PointInTimeRecoveryStatus') == 'ENABLED'
                            
                            if pitr_enabled:
                                print(f"  -> PITR enabled. Using export_table_to_point_in_time...")
                                # Create a unique prefix in S3 for this export
                                s3_prefix = f"{table_name}/{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}"
                                
                                try:
                                    response = self.dynamodbClient.export_table_to_point_in_time(
                                        TableArn=f"arn:aws:dynamodb:{self.dynamodbClient.meta.region_name}:{boto3.client('sts').get_caller_identity().get('Account')}:table/{table_name}",
                                        S3Bucket=bucket_name,
                                        S3Prefix=s3_prefix,
                                        ExportFormat='DYNAMODB_JSON'
                                    )
                                    print(f"  -> Successfully started export for '{table_name}'. Export ARN: {response['ExportDescription']['ExportArn']}")
                                except Exception as e:
                                    print(f"  -> FAILED to start export for '{table_name}':", e)
                            else:
                                print(f"  -> PITR not enabled. Using scan and manual export...")
                                self._export_table_manually(table_name, bucket_name)
                                
                        except Exception as e:
                            print(f"  -> Error checking PITR status for '{table_name}':", e)
                            print(f"  -> Attempting manual export...")
                            self._export_table_manually(table_name, bucket_name)

        except Exception as e:
            print(f"An error occurred listing tables:", e)

                
    def enable_point_in_time_recovery(self, table_name):
        """
        Enable Point-in-Time Recovery for a DynamoDB table
        """
        try:
            response = self.dynamodbClient.update_continuous_backups(
                TableName=table_name,
                PointInTimeRecoverySpecification={
                    'PointInTimeRecoveryEnabled': True
                }
            )
            print(f"✅ Successfully enabled Point-in-Time Recovery for table '{table_name}'")
            return True
        except Exception as e:
            print(f"❌ Failed to enable Point-in-Time Recovery for table '{table_name}':", e)
            return False
    
    def enable_pitr_for_all_tables(self, table_suffix=""):
        """
        Enable Point-in-Time Recovery for all tables with the specified suffix
        """
        print(f"Enabling Point-in-Time Recovery for tables with suffix '{table_suffix}'...")
        
        try:
            # Get a list of all tables
            paginator = self.dynamodbClient.get_paginator('list_tables')
            for page in paginator.paginate():
                for table_name in page['TableNames']:
                    if table_name.endswith(table_suffix):
                        print(f"Processing table: {table_name}")
                        
                        # Check current PITR status
                        try:
                            table_info = self.dynamodbClient.describe_table(TableName=table_name)
                            pitr_status = table_info['Table'].get('PointInTimeRecoveryDescription', {}).get('PointInTimeRecoveryStatus')
                            
                            if pitr_status == 'ENABLED':
                                print(f"  -> PITR already enabled for '{table_name}'")
                            else:
                                print(f"  -> Enabling PITR for '{table_name}'...")
                                self.enable_point_in_time_recovery(table_name)
                                
                        except Exception as e:
                            print(f"  -> Error processing table '{table_name}':", e)
                            
        except Exception as e:
            print(f"An error occurred listing tables:", e)
    
    def import_table_from_s3(self, table_name, s3_bucket, s3_key, overwrite=False, batch_size=25):
        """
        Import table data from S3 JSON file
        
        Args:
            table_name: Name of the DynamoDB table to import into
            s3_bucket: S3 bucket name
            s3_key: S3 key path to the JSON file
            overwrite: Whether to overwrite existing items
            batch_size: Number of items to write in each batch
        """
        try:
            # Initialize S3 client
            s3_client = boto3.client('s3')
            
            print(f"📥 Starting import for table '{table_name}' from s3://{s3_bucket}/{s3_key}")
            
            # Download and parse the JSON file
            response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            data = json.loads(response['Body'].read().decode('utf-8'))
            
            if not isinstance(data, list):
                print(f"❌ Invalid data format. Expected list, got {type(data)}")
                return False
            
            print(f"📊 Found {len(data)} items to import")
            
            # Get the table
            table = self.dynamodbResource.Table(table_name)
            
            # Process items in batches
            imported_count = 0
            skipped_count = 0
            error_count = 0
            
            for i in range(0, len(data), batch_size):
                batch = data[i:i + batch_size]
                batch_items = []
                
                for item in batch:
                    try:
                        # Add tenant metadata if not present
                        if isinstance(item, dict):
                            if 'tenantKey' in item:
                                item['countryCode'] = item['tenantKey'].split('#')[0]
                                item['eventType'] = item['tenantKey'].split('#')[1]
                                item['season'] = item['tenantKey'].split('#')[2]
                        
                        # Clean up the item for DynamoDB
                        cleaned_item = helpers.cleanUnpickleable(item)
                        batch_items.append(cleaned_item)
                        
                    except Exception as e:
                        print(f"    -> Error processing item:", e)
                        error_count += 1
                
                if batch_items:
                    try:
                        # Write batch to DynamoDB
                        with table.batch_writer(overwrite_by_pkeys=['tenantKey', 'entityKey'] if overwrite else None) as batch:
                            for item in batch_items:
                                batch.put_item(Item=item)
                        
                        imported_count += len(batch_items)
                        print(f"    -> Imported batch {i//batch_size + 1}: {len(batch_items)} items")
                        
                    except Exception as e:
                        print(f"    -> Error writing batch {i//batch_size + 1}:", e)
                        error_count += len(batch_items)
            
            print(f"✅ Import completed for '{table_name}'")
            print(f"   📥 Imported: {imported_count} items")
            print(f"   ⏭️  Skipped: {skipped_count} items")
            print(f"   ❌ Errors: {error_count} items")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to import table '{table_name}':", e)
            return False
    
    def import_all_tables_from_s3(self, s3_bucket, s3_prefix="tablesBackup", table_suffix="", overwrite=False):
        """
        Import all tables from S3 backup
        
        Args:
            s3_bucket: S3 bucket name
            s3_prefix: S3 prefix where backups are stored
            table_suffix: DynamoDB table suffix to filter
            overwrite: Whether to overwrite existing items
        """
        try:
            # Initialize S3 client
            s3_client = boto3.client('s3')
            
            print(f"📥 Starting import of all tables from s3://{s3_bucket}/{s3_prefix}")
            
            # List all objects in the S3 prefix
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix)
            
            # Group files by table name
            table_files = {}
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        
                        # Parse table name from S3 key
                        # Expected format: tablesBackup/table_name/timestamp/data.json
                        parts = key.split('/')
                        if len(parts) >= 4 and parts[-1] == 'data.json':
                            table_name = parts[1]
                            
                            # Filter by table suffix if specified
                            if not table_suffix or table_name.endswith(table_suffix):
                                if table_name not in table_files:
                                    table_files[table_name] = []
                                table_files[table_name].append({
                                    'key': key,
                                    'last_modified': obj['LastModified']
                                })
            
            if not table_files:
                print(f"❌ No backup files found in s3://{s3_bucket}/{s3_prefix}")
                return False
            
            # Import each table (use the most recent backup for each table)
            for table_name, files in table_files.items():
                # Sort by last modified date and use the most recent
                files.sort(key=lambda x: x['last_modified'], reverse=True)
                latest_file = files[0]
                
                print(f"\n📥 Importing table '{table_name}' from {latest_file['key']}")
                
                # Check if table exists
                try:
                    self.dynamodbClient.describe_table(TableName=table_name)
                except Exception as e:
                    print(f"❌ Table '{table_name}' does not exist. Skipping...")
                    continue
                
                # Import the table
                success = self.import_table_from_s3(
                    table_name=table_name,
                    s3_bucket=s3_bucket,
                    s3_key=latest_file['key'],
                    overwrite=overwrite
                )
                
                if not success:
                    print(f"❌ Failed to import table '{table_name}'")
            
            print(f"\n✅ Import process completed")
            return True
            
        except Exception as e:
            print(f"❌ Failed to import tables:", e)
            return False
    
    def list_s3_backups(self, s3_bucket, s3_prefix="tablesBackup"):
        """
        List all available S3 backups
        
        Args:
            s3_bucket: S3 bucket name
            s3_prefix: S3 prefix where backups are stored
        """
        try:            
            # Initialize S3 client
            s3_client = boto3.client('s3')
            
            print(f"📋 Listing backups in s3://{s3_bucket}/{s3_prefix}")
            
            # List all objects in the S3 prefix
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix)
            
            table_backups = {}
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        
                        # Parse table name from S3 key
                        parts = key.split('/')
                        if len(parts) >= 4 and parts[-1] == 'data.json':
                            table_name = parts[1]
                            timestamp = parts[2]
                            
                            if table_name not in table_backups:
                                table_backups[table_name] = []
                            
                            table_backups[table_name].append({
                                'timestamp': timestamp,
                                'key': key,
                                'last_modified': obj['LastModified'],
                                'size': obj['Size']
                            })
            
            if not table_backups:
                print("❌ No backups found")
                return
            
            # Display backups grouped by table
            for table_name, backups in table_backups.items():
                print(f"\n📊 Table: {table_name}")
                
                # Sort by timestamp (newest first)
                backups.sort(key=lambda x: x['timestamp'], reverse=True)
                
                for backup in backups:
                    size_mb = backup['size'] / (1024 * 1024)
                    print(f"  📅 {backup['timestamp']} - {size_mb:.2f} MB")
                    print(f"     📁 {backup['key']}")
            
            return table_backups
            
        except Exception as e:
            print(f"❌ Failed to list backups:", e)
            return None

    def updateNewSeasonLeagues(self):
        """
        Update new season leagues
        """
        self.logger.info(f"🔧 Updating new season leagues...")
        leagues = self.getDict(tableName='tournaments')
        for leagueName, league in leagues.items():
            if 'href' in league:
                league['href'] = f"{league['href']}".replace('&season_id=26','').replace('&season_id=27','')
                self.set(tableName='tournaments', value=league, tournamentName=leagueName)
        self.logger.info(f"✅ New season leagues updated")
        return True

    def addDocuments(self):
        docs = [
            ("חוקת ילדים ב וטרומים 2025-26.pdf", "מסמך חוקת ילדים"),
            ("חוקת המשחק כולל שינויים 2025-26.pdf", "מסמך חוקי המשחק מלא"),
            ("נוהל רשימות שחקנים.pdf", "טופס רשימת שחקנים וכוננים"),
            ("חוקת כדורגל נשים ונערות 2025-26.pdf", "מסמך חוקת נשים ונערות"),
            ("טבלת עזר זמנים וחילופים 2025-26.pdf", "מסמך זמנים וחילופים"),
            ("שינויים תקנון רפואי 2024-25.pdf", "מסמך תקנון רפואי"),
            ("טופס החלפת שחקן.pdf", "טופס החלפת שחקן"),
            ("הנחיות למשחקי גביע.pdf", "מסמך משחקי גביע"),
            ("שינויי חוקה והנחיות ועדת שיפוט ארצית עונת 2025-26.pdf", "שינויי חוקה 2025-26"),
            ("כושר גופני לאזורים.pdf", "מסמך כושר גופני לאזורים"),
            ("טופס בקשה להחזר הוצאות נסיעה.docx","טופס בקשה להחזר הוצאות נסיעה")
        ]
        for docFile, docName in docs:
            self.set(tableName='documents', value={"docFile":docFile}, docName=docName)
        self.logger.info(f"✅ Documents added")
        return True

    def readGamesCsv(self):
        import csv
        csvFile = './tmp/ref43679_commute'
        games = []
        with open(f'{csvFile}.csv', 'r') as file:
            reader = csv.reader(file)
            header = []
            for row in reader:
                if not header:
                    header = row
                    continue
                dataRow = { header[i]: row[i] for i in range(len(header))}
                games.append(dataRow)
        
        self.checkGamesDistances(games)

        header.append('מרחק')
        with open(f'{csvFile}_distances.csv', 'w') as file:
            writer = csv.writer(file)
            writer.writerow(header)
            for game in games:
                writer.writerow(game.values())
        
        return True

    def checkGamesDistances(self, games:list):
        refereeDetail = self.getReferee(tenantKey='GLOBAL', mobileNo='+972547799979')
        refereeDetail = refereeDetail.get('+972547799979')
        refereeLatitude = refereeDetail.get('addressDetails').get('coordinates').get('lat')
        refereeLongitude = refereeDetail.get('addressDetails').get('coordinates').get('lng')
        tenantKey = 'IL#football#2024-25'
        for game in games:
            gameDetail = None
            distance = 0
            tournamentName = game['מסגרת משחקים']
            gameTitle = game['משחק/פעילות']
            homeTeamName = gameTitle.split(' - ')[0].strip()
            guestTeamName = gameTitle.split(' - ')[1].strip()
            date = helpers.convert_to_datetime(game['תאריך']).isoformat()[:10]
            
            entityKeys = {
                'tournamentName': tournamentName,
            }
            filters = [
                ('homeTeamName', {'condition': 'contains', 'value': homeTeamName}),
                ('guestTeamName', {'condition': 'contains', 'value': guestTeamName})
            ]
            gameDetails = self.getDict(tableName='tournamentGames', tenantKey=tenantKey, filters=filters, **entityKeys)
            if len(gameDetails) == 0:
                filters = [
                    ('homeTeamName', {'condition': 'contains', 'value': homeTeamName}),
                ]
                gameDetails = self.getDict(tableName='tournamentGames', tenantKey=tenantKey, filters=filters, **entityKeys)
                if len(gameDetails) == 0:
                    filters = [
                        ('tournamentName', {'condition': 'eq', 'value': tournamentName}),
                        ('date', {'condition': 'bw', 'value': date}),
                    ]
                    gameDetails = self.getDict(tableName='tournamentGames', tenantKey=tenantKey, filters=filters)
                    result = helpers.find_intuitive_matches(query=gameTitle, choices=list(gameDetails.keys()), cutoff=0.3)
                    if result:
                        gamePk = result[0]
                        gameDetails = { gamePk: gameDetails[gamePk] }
                    else:
                        pass
            
            if len(gameDetails) > 0:
                gameDetail = list(gameDetails.values())[0]
                field = self.getFields(tenantKey=gameDetail['tenantKey'], fieldName=gameDetail.get('field') or gameDetail.get('מגרש'))
                if field and field.get('addressDetails') and field.get('addressDetails').get('coordinates'):
                    coordinates = field.get('addressDetails').get('coordinates')
                    if coordinates.get('lat') and coordinates.get('lng'):
                        distance = helpers.calculate_distance_between_coordinates(lat1=coordinates.get('lat'), lng1=coordinates.get('lng'), lat2=refereeLatitude, lng2=refereeLongitude, unit='km')
                else:
                    pass
            else:
                pass
            game['distance'] = distance            

        jsonHelper.save_to_file(games, './tmp/ref43679_commute.json')
        return True

if __name__ == '__main__':
    def updateStates(awsDynamodbClient, tableName, entitySegmentTableName, entityKeyColumns):
        tenants = awsDynamodbClient.getDict(tableName='tenants')
        for tenantKey, tenant in tenants.items():
            entitySegments = awsDynamodbClient.getDict(tableName=entitySegmentTableName, tenantKey=tenantKey)
            for tournamentName in entitySegments.keys():
                games = awsDynamodbClient.getDict(tableName=tableName, tenantKey=tenantKey, tournamentName=tournamentName)
                print(f"🔍 Found {len(games)} games for {tenantKey}#{tournamentName}")
                for gamePk, game in games.items():
                    if game.get('removed', False) == True:
                        game['state'] = 'removed'
                    elif game.get('canceled', False) == True:
                        game['state'] = 'canceled'
                    elif game.get('archived', False) == True:
                        game['state'] = 'archived'
                    else:
                        game['state'] = 'active'
                awsDynamodbClient.setDict(tableName=tableName, data=games, entityKeyColumns=entityKeyColumns)
                pass

        pass

    def updateGameDetailState(gameDetails):
        for gameDetail in gameDetails:
            if gameDetail.get('removed', False) == True:
                gameDetail['state'] = 'removed'
            elif gameDetail.get('canceled', False) == True:
                gameDetail['state'] = 'canceled'
            elif gameDetail.get('archived', False) == True:
                gameDetail['state'] = 'archived'
            else:
                gameDetail['state'] = 'active'

            if 'removed' in gameDetail:
                del gameDetail['removed']
            if 'canceled' in gameDetail:
                del gameDetail['canceled']
            if 'archived' in gameDetail:
                del gameDetail['archived']

            if 'nested' in gameDetail and 'referees' not in gameDetail:
                gameDetail['referees'] = list(gameDetail.get('nested', {}).values())
                del gameDetail['nested']

        return gameDetails

    def updateRefereeGameState(refereeGames):
        for refereeGame in refereeGames:
            if refereeGame.get('removed', False) == True:
                refereeGame ['state'] = 'removed'
            elif refereeGame.get('canceled', False) == True:
                refereeGame['state'] = 'canceled'
            elif refereeGame.get('archived', False) == True:
                refereeGame['state'] = 'archived'
            else:
                refereeGame['state'] = 'active'

            if 'removed' in refereeGame:
                del refereeGame['removed']
            if 'canceled' in refereeGame:
                del refereeGame['canceled']
            if 'archived' in refereeGame:
                del refereeGame['archived']

        return refereeGames

    def updateRefereeReviewsState(refereeReviews):
        objType = 'reviews'
        for refereeReview in refereeReviews:
            tenantKey = refereeReview['tenantKey']
            if refereeReview.get('removed', False) == True:
                refereeReview ['state'] = 'removed'
            elif refereeReview.get('canceled', False) == True:
                refereeReview['state'] = 'canceled'
            elif refereeReview.get('archived', False) == True:
                refereeReview['state'] = 'archived'
            else:
                refereeReview['state'] = 'active'

            if 'removed' in refereeReview:
                del refereeReview['removed']
            if 'canceled' in refereeReview:
                del refereeReview['canceled']
            if 'archived' in refereeReview:
                del refereeReview['archived']

            #refereeReview = self.multiTenantSupport.mapItem(tenantKey=tenantKey, objType=objType, obj=refereeReview)

        return refereeReviews

if __name__ == '__main__':
    # Increase PyDev debugger limit for large containers
    os.environ.setdefault('PYDEVD_CONTAINER_RANDOM_ACCESS_MAX_ITEMS', '2000')
    
    dynamodbResource = boto3.resource(
        "dynamodb",
        region_name=os.getenv('awsRegion'),
        endpoint_url=os.getenv('dynamoDbEndpointUrl'))
    dynamodbClient = boto3.client(
        "dynamodb",
        region_name=os.getenv('awsRegion'),
        endpoint_url=os.getenv('dynamoDbEndpointUrl'))
    awsDynamodbClient = DynamodbClient(env=os.getenv('app_env'), logger=logging.getLogger(), dynamodbResource=dynamodbResource, dynamodbClient=dynamodbClient)
    #import shared.orgRelated.multiTenantSupport as MultiTenantSupport
    #multiTenantSupport = MultiTenantSupport(logger=logging.getLogger(), dbClient=awsDynamodbClient, mapConfig=awsDynamodbClient.mapConfig)
    pass
    #awsDynamodbClient.processTableInBatches(tableName='tournamentGames', process_func=lambda x: updateGameDetailState(x), batch_size=100, tenantKey=None)
    pass
    #awsDynamodbClient.processTableInBatches(tableName='refereeGames', process_func=lambda x: updateRefereeGameState(x), batch_size=100, tenantKey=None)
    pass
    awsDynamodbClient.processTableInBatches(tableName='refereeReviews', process_func=lambda x: updateRefereeReviewsState(x), batch_size=100, tenantKey=None)
    pass
    #S3_BUCKET_NAME = f"refereex-refportal-bucket-{os.getenv('app_env')}"  # The S3 bucket to export to
    #TABLE_SUFFIX = f"_{os.getenv('app_env')}"

    #awsDynamodbClient.readGamesCsv()
    #pass

    #awsDynamodbClient.addDocuments()
    pass

    #awsDynamodbClient.moveRefereeGamesArchivedRemoved()

    # Check command line arguments
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        
        if action == "enable-pitr":
            print("🔧 Enabling Point-in-Time Recovery for all tables...")
            awsDynamodbClient.enable_pitr_for_all_tables(table_suffix=TABLE_SUFFIX)
        elif action == "export":
            print("📤 Exporting all tables to S3...")
            awsDynamodbClient.export_all_tables_to_s3(bucket_name=S3_BUCKET_NAME, table_suffix=TABLE_SUFFIX)
        elif action == "import":
            print("📥 Importing all tables from S3...")
            awsDynamodbClient.import_all_tables_from_s3(bucket_name=S3_BUCKET_NAME, table_suffix=TABLE_SUFFIX)
        elif action == "import-tenant":
            if len(sys.argv) >= 4:
                source_country = sys.argv[2]
                source_event = sys.argv[3]
                print(f"📥 Importing tenant data for {source_country}#{source_event}...")
                awsDynamodbClient.import_tenant_data(
                    s3_bucket=S3_BUCKET_NAME,
                    source_country_code=source_country,
                    source_event_type=source_event
                )
            else:
                print("Usage: python dynamodbClient.py import-tenant <country_code> <event_type>")
        elif action == "list-backups":
            print("📋 Listing S3 backups...")
            awsDynamodbClient.list_s3_backups(bucket_name=S3_BUCKET_NAME)
        elif action == "both":
            print("🔧 Enabling Point-in-Time Recovery for all tables...")
            awsDynamodbClient.enable_pitr_for_all_tables(table_suffix=TABLE_SUFFIX)
            print("\n📤 Exporting all tables to S3...")
            awsDynamodbClient.export_all_tables_to_s3(bucket_name=S3_BUCKET_NAME, table_suffix=TABLE_SUFFIX)
        else:
            print("Usage: python dynamodbClient.py [enable-pitr|export|import|import-tenant|list-backups|both]")
            print("  enable-pitr: Enable Point-in-Time Recovery for all tables")
            print("  export: Export all tables to S3 (uses PITR if available, manual scan otherwise)")
            print("  import: Import all tables from S3 backup")
            print("  import-tenant <country> <event>: Import specific tenant data from S3")
            print("  list-backups: List all available S3 backups")
            print("  both: Enable PITR and then export")
    else:
        # Default action: export
        print("📤 Exporting all tables to S3...")
        awsDynamodbClient.export_all_tables_to_s3(bucket_name=S3_BUCKET_NAME, table_suffix=TABLE_SUFFIX)
    
    #awsDynamodbClient.updateRefereeGamesArchivedRemoved()
    #awsDynamodbClient.setRefereeProperties(refId='+123456789', value=True, propertyName='joinConfirmationReply') or True
    #v = awsDynamodbClient.getRefereeProperties(refId='+123456789', propertyName='joinConfirmationReply') != False
    #awsDynamodbClient.archiveGames()
    #awsDynamodbClient.truncate('refereeMessages')
    #DynamodbClient.recreateTablesLocally(awsDynamodbClient.dynamodbClient, '_local', '_stage')
    #ref = awsDynamodbClient.getReferee('43679')
    #val = awsDynamodbClient.setRefereeProperties('43679', 'testPropValue', 'testProp1')
    #awsDynamodbClient.updateRefereeGameReminder()
    pass

    #'calcGameDuration', 'getGameActions', 'getGameDetailById', 'getMessage', 'getRefGameActions', 'getReferenceId', 'removeRefereeReview', 'setGameActions', 'setRefGameActions', 'setReferenceId', 'valueChanged'
