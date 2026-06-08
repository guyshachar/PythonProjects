"""
RefPortal Cronjob Service for EC2
Runs continuously and executes scheduled tasks
"""

import asyncio
import signal
import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Add shared modules to path
sys.path.append('/shared')
sys.path.append('/newServiceArchitecture')

from shared.logger import Logger
from shared.db import CacheService
from shared.messaging import MessagingService
from rpCronjob.cronjobClient import CronjobClient
from shared.appContainer import AppContainer
import shared.configurationDI as configDI

class CronjobService:
    """Main cronjob service for EC2 deployment"""
    
    def __init__(self):
        self.logger: Optional[Logger] = None
        self.cronjob_client: Optional[CronjobClient] = None
        self.app_container: Optional[AppContainer] = None
        self.running = False
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    async def initialize(self):
        """Initialize the cronjob service"""
        try:
            self.logger.info("Initializing RefPortal Cronjob Service...")
            
            # Initialize dependency injection container
            self.app_container = AppContainer()
            appContainer = AppContainer()
            appContainer.config.from_dict(configDI.configDI)
            appContainer.init_resources()
            handleRefereeData=appContainer.handle_referee_data()
            handleRefereeData.loadActiveRefereeDetails()
            
            # Get services from container
            self.logger = self.app_container.logger()
            db_client = self.app_container.db_client()
            messaging_service = self.app_container.messaging_service()
            
            # Initialize cronjob client
            self.cronjob_client = CronjobClient(self.logger, db_client, messaging_service)
            
            self.logger.info("Cronjob service initialized successfully")
            return True
            
        except Exception as ex:
            print(f"Failed to initialize cronjob service:", ex)
            if self.logger:
                self.logger.error("Failed to initialize cronjob service", ex)
            return False
    
    async def start(self):
        """Start the cronjob service"""
        if not await self.initialize():
            return False
        
        self.running = True
        self.logger.info("Starting cronjob service...")
        
        try:
            # Start the cronjob client with continuous scheduling
            await self.cronjob_client.start(interval_minutes=1)
            
        except Exception as ex:
            self.logger.error("Error in cronjob service", ex)
            return False
        
        return True
    
    async def run_once(self, task_id: str = None, context: Dict[str, Any] = None):
        """Run tasks once (for testing or manual execution)"""
        if not await self.initialize():
            return False
        
        try:
            if task_id:
                # Run specific task
                self.logger.info(f"Running specific task: {task_id}")
                success = await self.cronjob_client.run_task_immediately(task_id, context or {})
                if success:
                    self.logger.info(f"Task {task_id} completed successfully")
                else:
                    self.logger.warning(f"Task {task_id} completed with errors")
                return success
            else:
                # Run all enabled tasks
                self.logger.info("Running all enabled tasks")
                all_stats = self.cronjob_client.get_all_stats()
                
                for task_id, stats in all_stats.items():
                    if stats.get('enabled', True):
                        self.logger.info(f"Running task: {task_id}")
                        success = await self.cronjob_client.run_task_immediately(task_id)
                        if success:
                            self.logger.info(f"Task {task_id} completed successfully")
                        else:
                            self.logger.warning(f"Task {task_id} completed with errors")
                
                return True
                
        except Exception as ex:
            self.logger.error("Error running tasks", ex)
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        if not self.cronjob_client:
            return {"error": "Service not initialized"}
        
        return self.cronjob_client.get_all_stats()
    
    def stop(self):
        """Stop the cronjob service"""
        self.logger.info("Stopping cronjob service...")
        self.running = False
        if self.cronjob_client:
            self.cronjob_client.stop()

async def main():
    """Main entry point"""
    service = CronjobService()
    
    # Check command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "run-once":
            # Run tasks once and exit
            task_id = sys.argv[2] if len(sys.argv) > 2 else None
            context = {}
            if len(sys.argv) > 3:
                # Parse context from command line (simple key=value format)
                for arg in sys.argv[3:]:
                    if '=' in arg:
                        key, value = arg.split('=', 1)
                        context[key] = value
            
            success = await service.run_once(task_id, context)
            sys.exit(0 if success else 1)
        
        elif command == "stats":
            # Show statistics and exit
            await service.initialize()
            stats = service.get_stats()
            print("Cronjob Service Statistics:")
            for task_id, task_stats in stats.items():
                print(f"\nTask: {task_id}")
                for key, value in task_stats.items():
                    print(f"  {key}: {value}")
            sys.exit(0)
        
        elif command == "help":
            print("RefPortal Cronjob Service")
            print("Usage:")
            print("  python cronjob_service.py                    # Run continuously")
            print("  python cronjob_service.py run-once          # Run all tasks once")
            print("  python cronjob_service.py run-once <task_id> # Run specific task once")
            print("  python cronjob_service.py stats             # Show statistics")
            print("  python cronjob_service.py help              # Show this help")
            sys.exit(0)
    
    # Run continuously
    try:
        success = await service.start()
        if not success:
            print("Failed to start cronjob service")
            sys.exit(1)
        
        # Keep running until signal received
        while service.running:
            await asyncio.sleep(1)
        
    except KeyboardInterrupt:
        print("Received keyboard interrupt")
    except Exception as ex:
        print(f"Unexpected error:", ex)
        sys.exit(1)
    finally:
        service.stop()
        print("Cronjob service stopped")

if __name__ == "__main__":
    # Set up logging for standalone execution
    if not os.path.exists('/var/log/cronjob'):
        os.makedirs('/var/log/cronjob')
    
    asyncio.run(main())
