"""
Cronjob Usage Examples for RefPortal
Shows how to use the cronjob functionality in different scenarios
"""

import asyncio
from shared.logger import Logger
from shared.db import DynamodbClient
from shared.messaging import MessagingService
from shared.cronjobClient import CronjobClient
from newArchitecture.cronjobTasks import (
    TournamentProcessingTask,
    RefereeDataCollectionTask,
    NotificationProcessingTask,
    SystemHealthCheckTask,
    DataCleanupTask,
    GameReminderTask
)

async def example_basic_cronjob_usage():
    """Basic example of using the cronjob client"""
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    messaging_service = MessagingService(logger, db_client, {})
    
    # Create cronjob client
    cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    # Start the cronjob scheduler
    logger.info("Starting cronjob scheduler...")
    
    # Run for a short time to demonstrate
    try:
        await asyncio.wait_for(cronjob_client.start(), timeout=60)
    except asyncio.TimeoutError:
        logger.info("Cronjob demo completed")
    finally:
        cronjob_client.stop()

async def example_custom_task():
    """Example of creating and using a custom cronjob task"""
    
    from shared.cronjobClient import CronjobTask
    
    class CustomRefPortalTask(CronjobTask):
        """Custom task for RefPortal-specific operations"""
        
        def __init__(self, logger, db_client, messaging_service):
            super().__init__(
                'custom_refportal_task',
                'Custom RefPortal Task',
                'Custom task for RefPortal operations'
            )
            self.logger = logger
            self.db_client = db_client
            self.messaging_service = messaging_service
        
        async def execute(self, context):
            """Execute the custom task"""
            try:
                self.logger.info("Running custom RefPortal task...")
                
                # Your custom logic here
                # For example: process specific data, send notifications, etc.
                
                # Simulate some work
                await asyncio.sleep(2)
                
                self.logger.info("Custom task completed successfully")
                return True
                
            except Exception as ex:
                self.logger.error("Custom task failed", ex)
                return False
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    messaging_service = MessagingService(logger, db_client, {})
    
    # Create cronjob client
    cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    # Register custom task
    custom_task = CustomRefPortalTask(logger, db_client, messaging_service)
    cronjob_client.scheduler.register_task(custom_task)
    
    # Run the custom task immediately
    success = await cronjob_client.run_task_immediately('custom_refportal_task')
    logger.info(f"Custom task result: {success}")
    
    # Get task statistics
    stats = cronjob_client.get_task_stats('custom_refportal_task')
    logger.info(f"Task statistics: {stats}")

async def example_task_management():
    """Example of managing cronjob tasks"""
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    messaging_service = MessagingService(logger, db_client, {})
    
    # Create cronjob client
    cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    # Get all task statistics
    all_stats = cronjob_client.get_all_stats()
    logger.info(f"All task statistics: {all_stats}")
    
    # Disable a specific task
    cronjob_client.disable_task('tournament_processing')
    logger.info("Tournament processing task disabled")
    
    # Enable a specific task
    cronjob_client.enable_task('tournament_processing')
    logger.info("Tournament processing task enabled")
    
    # Run a specific task immediately
    success = await cronjob_client.run_task_immediately('system_health_check')
    logger.info(f"Health check result: {success}")
    
    # Get statistics for a specific task
    health_stats = cronjob_client.get_task_stats('system_health_check')
    logger.info(f"Health check statistics: {health_stats}")

async def example_integration_with_existing_services():
    """Example of integrating cronjob with existing RefPortal services"""
    
    from newArchitecture.tournamentProcessesService import TournamentProcessesService
    from newArchitecture.NotificationService import NotificationService
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    messaging_service = MessagingService(logger, db_client, {})
    
    # Create existing services
    tournament_service = TournamentProcessesService(logger, db_client, messaging_service)
    notification_service = NotificationService(logger, db_client, messaging_service)
    
    # Create cronjob client
    cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    # Create custom task that uses existing services
    class IntegratedTask(CronjobTask):
        def __init__(self, logger, db_client, messaging_service, tournament_service, notification_service):
            super().__init__(
                'integrated_task',
                'Integrated RefPortal Task',
                'Task that integrates with existing services'
            )
            self.logger = logger
            self.db_client = db_client
            self.messaging_service = messaging_service
            self.tournament_service = tournament_service
            self.notification_service = notification_service
        
        async def execute(self, context):
            try:
                self.logger.info("Running integrated task...")
                
                # Use tournament service
                tournaments = await self.tournament_service.getActiveTournaments()
                self.logger.info(f"Found {len(tournaments)} active tournaments")
                
                # Use notification service
                pending_notifications = await self.notification_service.getPendingNotifications()
                self.logger.info(f"Found {len(pending_notifications)} pending notifications")
                
                # Process notifications
                for notification in pending_notifications:
                    await self.notification_service.processNotification(notification)
                
                return True
                
            except Exception as ex:
                self.logger.error("Integrated task failed", ex)
                return False
    
    # Register integrated task
    integrated_task = IntegratedTask(
        logger, db_client, messaging_service, 
        tournament_service, notification_service
    )
    cronjob_client.scheduler.register_task(integrated_task)
    
    # Run the integrated task
    success = await cronjob_client.run_task_immediately('integrated_task')
    logger.info(f"Integrated task result: {success}")

async def example_monitoring_and_alerting():
    """Example of monitoring cronjob tasks and setting up alerts"""
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    messaging_service = MessagingService(logger, db_client, {})
    
    # Create cronjob client
    cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    # Monitor task health
    async def monitor_tasks():
        """Monitor task health and send alerts if needed"""
        while True:
            try:
                all_stats = cronjob_client.get_all_stats()
                
                for task_id, stats in all_stats.items():
                    # Check if task has high error rate
                    if stats['run_count'] > 0:
                        error_rate = (stats['error_count'] / stats['run_count']) * 100
                        
                        if error_rate > 50:  # More than 50% error rate
                            alert_message = f"High error rate for task {task_id}: {error_rate:.1f}%"
                            logger.warning(alert_message)
                            
                            # Send alert via messaging service
                            if messaging_service:
                                await messaging_service.sendAdminAlert(alert_message)
                    
                    # Check if task hasn't run recently
                    if stats['last_run']:
                        last_run = stats['last_run']
                        time_since_last_run = (datetime.now() - last_run).total_seconds()
                        
                        if time_since_last_run > 3600:  # More than 1 hour
                            alert_message = f"Task {task_id} hasn't run for {time_since_last_run/60:.1f} minutes"
                            logger.warning(alert_message)
                            
                            # Send alert via messaging service
                            if messaging_service:
                                await messaging_service.sendAdminAlert(alert_message)
                
                # Wait 5 minutes before next check
                await asyncio.sleep(300)
                
            except Exception as ex:
                logger.error("Error in task monitoring", ex)
                await asyncio.sleep(60)
    
    # Start monitoring
    monitoring_task = asyncio.create_task(monitor_tasks())
    
    # Start cronjob scheduler
    cronjob_task = asyncio.create_task(cronjob_client.start())
    
    try:
        # Run for demonstration
        await asyncio.wait_for(asyncio.gather(monitoring_task, cronjob_task), timeout=120)
    except asyncio.TimeoutError:
        logger.info("Monitoring demo completed")
    finally:
        cronjob_client.stop()
        monitoring_task.cancel()

async def example_error_handling_and_recovery():
    """Example of error handling and recovery in cronjob tasks"""
    
    from shared.cronjobClient import CronjobTask
    
    class RobustTask(CronjobTask):
        """Task with robust error handling and recovery"""
        
        def __init__(self, logger, db_client, messaging_service):
            super().__init__(
                'robust_task',
                'Robust Task',
                'Task with error handling and recovery'
            )
            self.logger = logger
            self.db_client = db_client
            self.messaging_service = messaging_service
            self.retry_count = 0
            self.max_retries = 3
        
        async def execute(self, context):
            try:
                self.logger.info(f"Running robust task (attempt {self.retry_count + 1})")
                
                # Simulate some work that might fail
                await self._do_work()
                
                # Reset retry count on success
                self.retry_count = 0
                return True
                
            except Exception as ex:
                self.retry_count += 1
                self.logger.error(f"Task failed (attempt {self.retry_count}):", ex)
                
                if self.retry_count < self.max_retries:
                    # Wait before retry with exponential backoff
                    wait_time = 2 ** self.retry_count
                    self.logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    
                    # Retry the task
                    return await self.execute(context)
                else:
                    # Max retries reached, send alert
                    alert_message = f"Task {self.task_id} failed after {self.max_retries} attempts"
                    self.logger.error(alert_message)
                    
                    if self.messaging_service:
                        await self.messaging_service.sendAdminAlert(alert_message)
                    
                    return False
        
        async def _do_work(self):
            """Simulate work that might fail"""
            import random
            
            # Simulate random failures
            if random.random() < 0.3:  # 30% chance of failure
                raise Exception("Simulated random failure")
            
            # Simulate some work
            await asyncio.sleep(1)
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    messaging_service = MessagingService(logger, db_client, {})
    
    # Create cronjob client
    cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    # Register robust task
    robust_task = RobustTask(logger, db_client, messaging_service)
    cronjob_client.scheduler.register_task(robust_task)
    
    # Run the robust task multiple times to see error handling
    for i in range(5):
        success = await cronjob_client.run_task_immediately('robust_task')
        logger.info(f"Task run {i+1} result: {success}")
        await asyncio.sleep(1)

# Example of how to integrate cronjob into your main service
class RefPortalServiceWithCronjob:
    """Example service class showing cronjob integration"""
    
    def __init__(self, logger: Logger, db_client, messaging_service):
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
        
        # Setup cronjob client
        self.cronjob_client = CronjobClient(logger, db_client, messaging_service)
    
    async def start(self):
        """Start the service with cronjob support"""
        self.logger.info("Starting RefPortal service with cronjob support...")
        
        # Start cronjob scheduler
        cronjob_task = asyncio.create_task(self.cronjob_client.start())
        
        # Start other services
        # ... your other service initialization here ...
        
        try:
            # Wait for all tasks
            await asyncio.gather(cronjob_task)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            self.cronjob_client.stop()
    
    def get_cronjob_stats(self):
        """Get cronjob statistics"""
        return self.cronjob_client.get_all_stats()
    
    async def run_task_immediately(self, task_id: str):
        """Run a specific task immediately"""
        return await self.cronjob_client.run_task_immediately(task_id)

if __name__ == "__main__":
    # Run examples
    print("Running cronjob examples...")
    
    # Basic usage
    asyncio.run(example_basic_cronjob_usage())
    
    # Custom task
    asyncio.run(example_custom_task())
    
    # Task management
    asyncio.run(example_task_management())
    
    # Integration
    asyncio.run(example_integration_with_existing_services())
    
    # Monitoring
    asyncio.run(example_monitoring_and_alerting())
    
    # Error handling
    asyncio.run(example_error_handling_and_recovery())
    
    print("All examples completed!")

