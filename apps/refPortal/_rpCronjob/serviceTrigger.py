"""
Service Trigger Utilities for RefPortal
Provides multiple ways to trigger one Python service from another
"""

import json
import asyncio
import httpx
import boto3
import os
from typing import Dict, Any, Optional
import sys 
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class ServiceTrigger:
    """Utility class for triggering other services"""
    
    def __init__(self, logger: Logger):
        self.logger = logger
    
    async def trigger_via_direct_call(self, service_instance, method_name: str, *args, **kwargs):
        """Direct method call - fastest, same process only"""
        try:
            method = getattr(service_instance, method_name)
            if asyncio.iscoroutinefunction(method):
                return await method(*args, **kwargs)
            else:
                return method(*args, **kwargs)
        except Exception as ex:
            self.logger.error(f'Direct call failed: {method_name}', ex)
            raise
    
    async def trigger_via_lambda(self, function_name: str, payload: Dict[str, Any], 
                                invocation_type: str = 'Event') -> bool:
        """AWS Lambda invocation - distributed, async"""
        try:
            env = os.getenv('app_env')
            boto3lambdaClient = boto3.client('lambda')
            
            response = boto3lambdaClient.invoke(
                FunctionName=f'{function_name}_{env}',
                InvocationType=invocation_type,  # 'Event' for async, 'RequestResponse' for sync
                Payload=json.dumps(payload)
            )
            
            self.logger.info(f'Lambda {function_name} triggered successfully')
            return True
            
        except Exception as ex:
            self.logger.error(f'Lambda invocation failed: {function_name}', ex)
            return False
    
    async def trigger_via_http(self, service_url: str, endpoint: str, 
                              payload: Dict[str, Any], timeout: int = 30) -> Optional[Dict]:
        """HTTP API call - language agnostic, debuggable"""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{service_url}/{endpoint}",
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as ex:
            self.logger.error(f'HTTP call failed: {service_url}/{endpoint}', ex)
            return None
    
    async def trigger_via_sqs(self, queue_url: str, message: Dict[str, Any], 
                             delay_seconds: int = 0, message_attributes: Dict = None) -> bool:
        """SQS message - decoupled, reliable"""
        try:
            from shared.sqsClient import SqsClient
            sqs_client = SqsClient(self.logger, queue_url)
            
            response = sqs_client.send_message(
                message=json.dumps(message),
                delay_seconds=delay_seconds,
                message_attributes=message_attributes
            )
            
            self.logger.info(f'SQS message sent to {queue_url}: {response["MessageId"]}')
            return True
            
        except Exception as ex:
            self.logger.error(f'SQS send failed: {queue_url}', ex)
            return False
    
    async def trigger_via_eventbridge(self, event_bus: str, source: str, 
                                     detail_type: str, detail: Dict[str, Any]) -> bool:
        """EventBridge event - event-driven architecture"""
        try:
            eventbridge = boto3.client('events')
            response = eventbridge.put_events(
                Entries=[{
                    'Source': source,
                    'DetailType': detail_type,
                    'Detail': json.dumps(detail),
                    'EventBusName': event_bus
                }]
            )
            
            self.logger.info(f'EventBridge event sent: {detail_type}')
            return True
            
        except Exception as ex:
            self.logger.error(f'EventBridge send failed: {detail_type}', ex)
            return False

# Example usage in your TournamentActions
class TournamentActionsWithTriggers:
    def __init__(self, logger: Logger, organizationService, serviceTrigger: ServiceTrigger):
        self.logger = logger
        self.organizationService = organizationService
        self.serviceTrigger = serviceTrigger
    
    async def processTournamentsWithTriggers(self, page, tournament, round, fixture):
        """Example showing different trigger methods"""
        
        # 1. Direct call (current pattern)
        await self.serviceTrigger.trigger_via_direct_call(
            self.organizationService, 
            'fetchTournamentGameSquadsByRoundAndFixture',
            page=page, tournament=tournament, round=round, fixture=fixture
        )
        
        # 2. Lambda trigger (for distributed processing)
        await self.serviceTrigger.trigger_via_lambda(
            'lambda_refportal_organization_service',
            {
                'action': 'fetchSquads',
                'tournament': tournament,
                'round': round,
                'fixture': fixture
            }
        )
        
        # 3. HTTP trigger (for RESTful services)
        await self.serviceTrigger.trigger_via_http(
            'https://your-organization-service.com',
            'api/v1/fetch-squads',
            {
                'tournament': tournament,
                'round': round,
                'fixture': fixture
            }
        )
        
        # 4. SQS trigger (for decoupled processing)
        await self.serviceTrigger.trigger_via_sqs(
            'https://sqs.region.amazonaws.com/account/queue-name',
            {
                'action': 'fetchSquads',
                'tournament': tournament,
                'round': round,
                'fixture': fixture
            }
        )
