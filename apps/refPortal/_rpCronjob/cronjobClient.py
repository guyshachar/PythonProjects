import sys
import asyncio
import schedule
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional
from abc import ABC, abstractmethod
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.db import CacheService
from shared.messaging import MessagingService
from shared.logger import Logger
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from rpCronjob.iOrganizationService import IOrganizationService
from rpCronjob.ifaService import IFAService
from shared.appContainer import AppContainer

class CronjobTask(ABC):
    """Abstract base class for cronjob tasks"""
    
    def __init__(self, task_id: str, name: str, description: str = ""):
        self.task_id = task_id
        self.name = name
        self.description = description
        self.last_run = None
        self.next_run = None
        self.run_count = 0
        self.success_count = 0
        self.error_count = 0
        self.enabled = True
    
    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> bool:
        """Execute the cronjob task. Return True if successful, False otherwise."""
        pass
    
    def get_stats(self) -> Dict[str, Any]:
        """Get task statistics"""
        return {
            'task_id': self.task_id,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'last_run': self.last_run,
            'next_run': self.next_run,
            'run_count': self.run_count,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'success_rate': (self.success_count / self.run_count * 100) if self.run_count > 0 else 0
        }

class CronjobScheduler:
    """Scheduler for managing cronjob tasks"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase):
        self.logger = logger
        self.db_client = db_client
        self.tasks: Dict[str, CronjobTask] = {}
        self.running = False
        self.scheduler_thread = None
    
    def register_task(self, task: CronjobTask):
        """Register a cronjob task"""
        self.tasks[task.task_id] = task
        self.logger.info(f'Registered cronjob task: {task.task_id} - {task.name}')
    
    def unregister_task(self, task_id: str):
        """Unregister a cronjob task"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.logger.info(f'Unregistered cronjob task: {task_id}')
    
    def enable_task(self, task_id: str):
        """Enable a cronjob task"""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = True
            self.logger.info(f'Enabled cronjob task: {task_id}')
    
    def disable_task(self, task_id: str):
        """Disable a cronjob task"""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = False
            self.logger.info(f'Disabled cronjob task: {task_id}')
    
    async def run_task(self, task_id: str, context: Dict[str, Any] = None) -> bool:
        """Run a specific task"""
        if task_id not in self.tasks:
            self.logger.error(f'Task not found: {task_id}')
            return False
        
        task = self.tasks[task_id]
        if not task.enabled:
            self.logger.warning(f'Task is disabled: {task_id}')
            return False
        
        try:
            self.logger.info(f'Running cronjob task: {task_id} - {task.name}')
            task.last_run = datetime.now()
            task.run_count += 1
            
            # Execute the task
            success = await task.execute(context or {})
            
            if success:
                task.success_count += 1
                self.logger.info(f'Task completed successfully: {task_id}')
            else:
                task.error_count += 1
                self.logger.warning(f'Task completed with errors: {task_id}')
            
            # Save task stats to database
            await self._save_task_stats(task)
            
            return success
            
        except Exception as ex:
            task.error_count += 1
            self.logger.error(f'Task failed with exception: {task_id}', ex)
            await self._save_task_stats(task)
            return False
    
    async def _save_task_stats(self, task: CronjobTask):
        """Save task statistics to database"""
        try:
            stats = task.get_stats()
            self.db_client.setRefereeProperties(
                mobileNo='system',
                value=stats,
                propertyName=f'cronjob_stats_{task.task_id}'
            )
        except Exception as ex:
            self.logger.error(f'Failed to save task stats for {task.task_id}', ex)
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all tasks"""
        return {task_id: task.get_stats() for task_id, task in self.tasks.items()}
    
    def get_task_stats(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific task"""
        if task_id in self.tasks:
            return self.tasks[task_id].get_stats()
        return None

class CronjobClient:
    """Main cronjob client for RefPortal"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService, handle_users: HandleUsers, handle_tournaments: HandleTournaments, handle_referee_data: HandleRefereeData):
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
        self.handle_users = handle_users
        self.handle_tournaments = handle_tournaments
        self.handle_referee_data = handle_referee_data
        
        self.ifa_service:IOrganizationService = IFAService(logger=self.logger, dbClient=self.db_client, messagingService=self.messaging_service, handleTournaments=self.handle_tournaments, handleRefereeData=self.handle_referee_data, handleUsers=self.handle_users)
        self.scheduler = CronjobScheduler(logger, db_client)
        self.running = False
        
        # Register default RefPortal tasks
        self._register_default_tasks()
    
    def _register_default_tasks(self):
        """Register default RefPortal cronjob tasks"""
        try:
            from newServiceArchitecture.cronjobTasks import (
                RefereeDataCollectionTask,
                TournamentProcessingTask,
                #NotificationProcessingTask,
                SystemHealthCheckTask,
                #DataCleanupTask,
                #GameReminderTask
            )
                        
            # Referee data collection task
            referee_task = RefereeDataCollectionTask(
                logger=self.logger, 
                db_client=self.db_client, 
                messaging_service=self.messaging_service, 
                handle_users=self.handle_users, 
                handle_tournaments=self.handle_tournaments, 
                handle_referee_data=self.handle_referee_data,
                organization_service=self.ifa_service
            )
            self.scheduler.register_task(task=referee_task)

            # Register more organization services

            # Tournament processing task
            tournament_task = TournamentProcessingTask(
                logger=self.logger, 
                db_client=self.db_client, 
                messaging_service=self.messaging_service, 
                handle_users=self.handle_users, 
                handle_tournaments=self.handle_tournaments, 
                handle_referee_data=self.handle_referee_data,
                organization_service=self.ifa_service
            )
            self.scheduler.register_task(task=tournament_task)

            # System health check task
            health_task = SystemHealthCheckTask(
                self.logger, self.db_client, self.messaging_service
            )
            self.scheduler.register_task(task=health_task)
            
        except ImportError as ex:
            self.logger.error(f'Failed to import cronjob tasks:', ex)
        except Exception as ex:
            self.logger.error(f'Error registering default tasks:', ex)
    
    async def start(self, interval_minutes: int = 5):
        """Start the cronjob scheduler"""
        self.logger.info(f'Starting cronjob scheduler with {interval_minutes} minute interval')
        self.running = True
        
        # Schedule tasks using the schedule library
        self._setup_schedules(interval_minutes)
        
        # Start the scheduler loop
        await self._scheduler_loop()
    
    def _setup_schedules(self, interval_minutes: int):
        """Setup task schedules"""
        # Referee data collection - every 10 minutes
        schedule.every(10).minutes.do(self._run_scheduled_task, 'referee_data_collection')

        # Tournament processing - every 5 minutes
        schedule.every(5).minutes.do(self._run_scheduled_task, 'tournament_processing')
                
        # System health check - every 15 minutes
        schedule.every(15).minutes.do(self._run_scheduled_task, 'system_health_check')
                
        self.logger.info('Cronjob schedules configured')
    
    async def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.running:
            try:
                schedule.run_pending()
                await asyncio.sleep(1)
            except Exception as ex:
                self.logger.error('Error in scheduler loop', ex)
                await asyncio.sleep(5)
    
    def _run_scheduled_task(self, task_id: str):
        """Run a scheduled task (wrapper for schedule library)"""
        asyncio.create_task(self.scheduler.run_task(task_id))
    
    async def run_task_immediately(self, task_id: str, context: Dict[str, Any] = None) -> bool:
        """Run a task immediately"""
        return await self.scheduler.run_task(task_id, context)
    
    def stop(self):
        """Stop the cronjob scheduler"""
        self.logger.info('Stopping cronjob scheduler')
        self.running = False
        schedule.clear()
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all tasks"""
        return self.scheduler.get_all_stats()
    
    def get_task_stats(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific task"""
        return self.scheduler.get_task_stats(task_id)
    
    def enable_task(self, task_id: str):
        """Enable a task"""
        self.scheduler.enable_task(task_id)
    
    def disable_task(self, task_id: str):
        """Disable a task"""
        self.scheduler.disable_task(task_id)

if __name__ == "__main__":
    app = None
    appContainer = AppContainer()
    app = CronjobClient(logger=appContainer.logger, db_client=appContainer.db_client, messaging_service=appContainer.messaging_service, handle_users=appContainer.handle_users, handle_tournaments=appContainer.handle_tournaments, handle_referee_data=appContainer.handle_referee_data)
    app.start()