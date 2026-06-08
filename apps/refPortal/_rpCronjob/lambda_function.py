"""
AWS Lambda function handler for RefPortal Cronjob Client
Handles scheduled tasks and cronjob execution
"""

import json
import asyncio
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional

# Add shared modules to path
sys.path.append('/shared')
sys.path.append('/rpCronjob')

from shared.logger import Logger
from shared.db import CacheService
from shared.messaging import MessagingService
from rpCronjob.cronjobClient import CronjobClient
from shared.appContainer import AppContainer

# Global variables for reuse across invocations
logger: Optional[Logger] = None
cronjob_client: Optional[CronjobClient] = None
app_container: Optional[AppContainer] = None

def initialize_services():
    """Initialize services on cold start"""
    global logger, cronjob_client, app_container
    
    try:
        # Initialize dependency injection container
        app_container = AppContainer()
        
        # Get services from container
        logger = app_container.logger()
        db_client = app_container.db_client()
        messaging_service = app_container.messaging_service()
        
        # Initialize cronjob client
        cronjob_client = CronjobClient(logger, db_client, messaging_service)
        
        logger.info("Cronjob client services initialized successfully")
        
    except Exception as ex:
        print(f"Failed to initialize services:", ex)
        raise

async def run_cronjob_tasks():
    """Run all scheduled cronjob tasks"""
    global cronjob_client, logger
    
    if not cronjob_client:
        raise Exception("Cronjob client not initialized")
    
    try:
        logger.info("Starting cronjob task execution")
        
        # Get all registered tasks
        all_stats = cronjob_client.get_all_stats()
        logger.info(f"Found {len(all_stats)} registered tasks")
        
        # Run each enabled task
        for task_id, stats in all_stats.items():
            if stats.get('enabled', True):
                logger.info(f"Running task: {task_id}")
                success = await cronjob_client.run_task_immediately(task_id)
                if success:
                    logger.info(f"Task {task_id} completed successfully")
                else:
                    logger.warning(f"Task {task_id} completed with errors")
            else:
                logger.info(f"Task {task_id} is disabled, skipping")
        
        logger.info("All cronjob tasks completed")
        return True
        
    except Exception as ex:
        logger.error("Error running cronjob tasks", ex)
        return False

async def run_specific_task(task_id: str, context: Dict[str, Any] = None):
    """Run a specific task by ID"""
    global cronjob_client, logger
    
    if not cronjob_client:
        raise Exception("Cronjob client not initialized")
    
    try:
        logger.info(f"Running specific task: {task_id}")
        success = await cronjob_client.run_task_immediately(task_id, context or {})
        
        if success:
            logger.info(f"Task {task_id} completed successfully")
        else:
            logger.warning(f"Task {task_id} completed with errors")
        
        return success
        
    except Exception as ex:
        logger.error(f"Error running task {task_id}", ex)
        return False

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler function
    
    Event structure:
    {
        "action": "run_all" | "run_task",
        "task_id": "task_id_here",  # Required for run_task action
        "context": {...}  # Optional context for task execution
    }
    """
    global logger, cronjob_client
    
    try:
        # Initialize services if not already done
        if not cronjob_client:
            initialize_services()
        
        # Parse event
        action = event.get('action', 'run_all')
        task_id = event.get('task_id')
        task_context = event.get('context', {})
        
        logger.info(f"Lambda invoked with action: {action}")
        
        # Execute based on action
        if action == 'run_all':
            # Run all scheduled tasks
            result = asyncio.run(run_cronjob_tasks())
            
        elif action == 'run_task':
            # Run specific task
            if not task_id:
                raise ValueError("task_id is required for run_task action")
            
            result = asyncio.run(run_specific_task(task_id, task_context))
            
        elif action == 'get_stats':
            # Get task statistics
            if task_id:
                stats = cronjob_client.get_task_stats(task_id)
                result = stats is not None
            else:
                stats = cronjob_client.get_all_stats()
                result = len(stats) > 0
            
        elif action == 'enable_task':
            # Enable a task
            if not task_id:
                raise ValueError("task_id is required for enable_task action")
            
            cronjob_client.enable_task(task_id)
            result = True
            
        elif action == 'disable_task':
            # Disable a task
            if not task_id:
                raise ValueError("task_id is required for disable_task action")
            
            cronjob_client.disable_task(task_id)
            result = True
            
        else:
            raise ValueError(f"Unknown action: {action}")
        
        # Return success response
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': result,
                'action': action,
                'task_id': task_id,
                'message': f'Action {action} completed successfully' if result else f'Action {action} failed'
            })
        }
        
    except Exception as ex:
        error_message = f"Lambda execution failed: {str(ex)}"
        print(error_message)
        
        if logger:
            logger.error("Lambda execution failed", ex)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': error_message,
                'action': event.get('action', 'unknown')
            })
        }

# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        "action": "run_all"
    }
    
    # Mock context
    class MockContext:
        def __init__(self):
            self.function_name = "cronjob-client"
            self.function_version = "1.0"
            self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:cronjob-client"
            self.memory_limit_in_mb = 512
            self.remaining_time_in_millis = 300000
    
    context = MockContext()
    
    # Run the handler
    result = lambda_handler(test_event, context)
    print(json.dumps(result, indent=2))
