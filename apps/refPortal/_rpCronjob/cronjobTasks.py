"""
RefPortal-specific cronjob tasks
Contains all the business logic tasks that run on schedule
"""

import asyncio
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any
import sys
import uuid
import os
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
# Import the dependency injection container
from shared.appContainer import AppContainer
import shared.helpers as helpers
from shared.logger import Logger
from shared.db import CacheService
from shared.messaging import MessagingService
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from newServiceArchitecture.cronjobClient import CronjobTask
from newServiceArchitecture.tournamentProcessesService import TournamentProcessesService
from newServiceArchitecture.collectorService import CollectorService
from shared.fileWatcher import watchFileChange
from newServiceArchitecture.iOrganizationService import IOrganizationService

class TournamentProcessingTask(CronjobTask):
    """Task for processing tournament data"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService, handle_users: HandleUsers, handle_tournaments: HandleTournaments, handle_referee_data: HandleRefereeData, organization_service: IOrganizationService):
        super().__init__(f'tournament_processing_{organization_service.name}', f'Tournament Processing {organization_service.name} ', f'Process tournament games and updates {organization_service.name}')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
        self.handle_users = handle_users
        self.handle_tournaments = handle_tournaments
        self.handle_referee_data = handle_referee_data
        self.organization_service = organization_service

    async def execute(self, context: Dict[str, Any]) -> bool:
        try:
            await self.organization_service.processTournaments()
            return True
        except Exception as ex:
            self.logger.error('Tournament processing task failed', ex)
            return False
        
class RefereeDataCollectionTask(CronjobTask):
    """Task for collecting referee data"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService, handle_users: HandleUsers, handle_tournaments: HandleTournaments, handle_referee_data: HandleRefereeData, organization_service: IOrganizationService):
        super().__init__(f'referee_data_collection_{organization_service.name}', f'Referee Data Collection {organization_service.name} ', 'Collect and update referee data')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
        self.handle_users = handle_users
        self.handle_tournaments = self.handle_tournaments
        self.handle_referee_data = self.handle_referee_data

        self.organization_service = organization_service

        # Configuration from environment
        self.env = os.getenv('app_env')
        self.generate_reports = eval(os.getenv('generateReports', 'False'))
        self.main_instance = eval(os.getenv('mainInstance', 'False'))
        self.load_interval = int(os.getenv('loadInterval') or '10000')
        self.sw_level = os.getenv('swLevel') or 'debug'
        self.referees_per_run = int(os.getenv('refereesPerRun') or '10')

    async def execute(self, context: Dict[str, Any]) -> bool:
        try:
            """
            Start the service with dependency injection.
            """
            self.logger.debug('Start RefPortalServiceDI')
            self.messaging_service.mqttClient.publish(
                topic=self.messaging_service.mqttTopic, 
                title="RefPortalServiceDI Starts...", 
                payload=self.open_text
            )

            try:
                helpers.stopwatchStart('Interval processing')
                while True:
                    try:
                        self.load_metadata()

                        referees = list(self.handle_referee_data.activeRefereeDetails.items())
                        any_change = False
                        helpers.stopwatchStart(f'Loop time')
                        
                        for i in range(0, len(referees), self.referees_per_run):
                            batch_referees = dict(referees[i : i + self.referees_per_run])
                            referee_ids = list(batch_referees.keys())
                            self.logger.info(f'Processing {len(referee_ids)} referees...')
                            
                            invocation_id = str(uuid.uuid4())
                            payload = { 'invocationId': invocation_id, 'refereeIds': referee_ids }
                            
                            # Use the injected referee process service
                            any_change = await self.organization_service.startProcessByRefIds(refIds=referee_ids)
                            
                            self.db_client.setInvocation(invocation_id, payload)
                        
                        if self.generate_reports and self.main_instance and any_change:
                            await self.handle_referee_data.collectGamesSummary()

                        helpers.stopwatchStop(f'Loop time', level='info')
                        self.logger.info(f'#referees={len(referees)}')

                    except Exception as ex:
                        self.logger.error('Start', ex)
                    finally:
                        if self.load_interval <= 0:
                            break
                        await asyncio.sleep(self.load_interval)

            except Exception as ex:
                self.logger.error(f'start', ex)
            
            finally:
                helpers.stopwatchStop('Interval processing', level='info')
                self.logger.debug(f'close')
                
                if self.referee_file_watch_observer:
                    self.referee_file_watch_observer.stop()
                
                # Shutdown container resources
                self.shutdown_resources()

            return True
        except Exception as ex:
            self.logger.error('Referee data collection task failed', ex)
            return False

    def load_metadata(self, initial=False):
        """
        Load metadata using injected dependencies.
        """
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FOLDER", "/run/data/")}referees/details/referees.json'

            if initial:
                self.referee_file_watch_observer = watchFileChange(referee_file_path, self.should_load_referees_file)

            self.handle_referee_data.loadActiveRefereeDetails(referee_file_path, None, initial)
            self.referees_file_changed = False

        except Exception as ex:
            self.logger.error(f'load_metadata', ex)

    async def _collect_referee_data(self, referee_id: str, referee_data: Dict[str, Any]):
        """Collect data for a specific referee"""
        try:
            # Get referee's upcoming games
            upcoming_games = await self.db_client.getRefereeGames(referee_id, upcoming_only=True)
            
            # Get referee's recent reviews
            recent_reviews = await self.db_client.getRefereeReviews(referee_id, days=30)
            
            # Update referee statistics
            await self._update_referee_stats(referee_id, upcoming_games, recent_reviews)
            
        except Exception as ex:
            self.logger.error(f'Error collecting data for referee {referee_id}', ex)
    
    async def _update_referee_stats(self, referee_id: str, games: list, reviews: list):
        """Update referee statistics"""
        try:
            stats = {
                'upcoming_games': len(games),
                'recent_reviews': len(reviews),
                'last_updated': datetime.now().isoformat()
            }
            
            self.db_client.setRefereeProperties(
                refId=referee_id,
                value=stats,
                propertyName='referee_stats'
            )
            
        except Exception as ex:
            self.logger.error(f'Error updating stats for referee {referee_id}', ex)

class NotificationProcessingTask(CronjobTask):
    """Task for processing notifications"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService):
        super().__init__('notification_processing', 'Notification Processing', 'Process pending notifications')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
    
    async def execute(self, context: Dict[str, Any]) -> bool:
        try:
            # Get pending notifications
            pending_notifications = self.db_client.getPendingNotifications()
            
            self.logger.info(f'Processing {len(pending_notifications)} pending notifications')
            
            processed_notifications = 0
            for notification in pending_notifications:
                try:
                    # Process notification
                    success = await self._process_notification(notification)
                    if success:
                        processed_notifications += 1
                    
                except Exception as ex:
                    self.logger.error(f'Error processing notification {notification.get("id", "unknown")}', ex)
                    continue
            
            self.logger.info(f'Processed {processed_notifications} notifications')
            return True
            
        except Exception as ex:
            self.logger.error('Notification processing task failed', ex)
            return False
    
    async def _process_notification(self, notification: Dict[str, Any]) -> bool:
        """Process a single notification"""
        try:
            notification_type = notification.get('type')
            recipient = notification.get('recipient')
            message = notification.get('message')
            
            if not all([notification_type, recipient, message]):
                self.logger.warning('Invalid notification data')
                return False
            
            # Send notification based on type
            if notification_type == 'whatsapp':
                await self._send_whatsapp_notification(recipient, message)
            elif notification_type == 'email':
                await self._send_email_notification(recipient, message)
            elif notification_type == 'push':
                await self._send_push_notification(recipient, message)
            else:
                self.logger.warning(f'Unknown notification type: {notification_type}')
                return False
            
            # Mark notification as sent
            await self.db_client.markNotificationSent(notification.get('id'))
            return True
            
        except Exception as ex:
            self.logger.error(f'Error processing notification', ex)
            return False
    
    async def _send_whatsapp_notification(self, recipient: str, message: str):
        """Send WhatsApp notification"""
        try:
            # Use your messaging service to send WhatsApp
            if self.messaging_service:
                await self.messaging_service.sendWhatsAppMessage(recipient, message)
        except Exception as ex:
            self.logger.error(f'Error sending WhatsApp notification to {recipient}', ex)
            raise
    
    async def _send_email_notification(self, recipient: str, message: str):
        """Send email notification"""
        try:
            # Add your email sending logic here
            self.logger.info(f'Sending email to {recipient}: {message[:50]}...')
        except Exception as ex:
            self.logger.error(f'Error sending email notification to {recipient}', ex)
            raise
    
    async def _send_push_notification(self, recipient: str, message: str):
        """Send push notification"""
        try:
            # Add your push notification logic here
            self.logger.info(f'Sending push notification to {recipient}: {message[:50]}...')
        except Exception as ex:
            self.logger.error(f'Error sending push notification to {recipient}', ex)
            raise

class SystemHealthCheckTask(CronjobTask):
    """Task for system health monitoring"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService):
        super().__init__('system_health_check', 'System Health Check', 'Monitor system health and performance')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
    
    async def execute(self, context: Dict[str, Any]) -> bool:
        try:
            # Check database connectivity
            db_healthy = await self._check_database_health()
            
            # Check messaging service health
            messaging_healthy = await self._check_messaging_health()
            
            # Check system resources
            system_healthy = await self._check_system_resources()
            
            # Check queue health
            queue_healthy = await self._check_queue_health()
            
            # Log health status
            health_status = {
                'database': db_healthy,
                'messaging': messaging_healthy,
                'system': system_healthy,
                'queues': queue_healthy,
                'timestamp': datetime.now().isoformat()
            }
            
            # Save health status
            self.db_client.setRefereeProperties(
                refId='system',
                value=health_status,
                propertyName='system_health_status'
            )
            
            if all([db_healthy, messaging_healthy, system_healthy, queue_healthy]):
                self.logger.info('System health check passed')
                return True
            else:
                self.logger.warning('System health check failed')
                return False
                
        except Exception as ex:
            self.logger.error('System health check task failed', ex)
            return False
    
    async def _check_database_health(self) -> bool:
        """Check database connectivity"""
        try:
            # Simple database health check
            self.db_client.getRefereeProperties(refId='system', propertyName='health_check')
            return True
        except Exception as ex:
            self.logger.error('Database health check failed', ex)
            return False
    
    async def _check_messaging_health(self) -> bool:
        """Check messaging service health"""
        try:
            # Check if messaging service is available
            if self.messaging_service:
                # Add specific health checks for your messaging services
                return True
            return False
        except Exception as ex:
            self.logger.error('Messaging health check failed', ex)
            return False
    
    async def _check_system_resources(self) -> bool:
        """Check system resources"""
        try:
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                self.logger.warning(f'High CPU usage: {cpu_percent}%')
                return False
            
            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                self.logger.warning(f'High memory usage: {memory.percent}%')
                return False
            
            # Check disk usage
            disk = psutil.disk_usage('/')
            if disk.percent > 90:
                self.logger.warning(f'High disk usage: {disk.percent}%')
                return False
            
            return True
            
        except ImportError:
            self.logger.warning('psutil not available for system resource monitoring')
            return True
        except Exception as ex:
            self.logger.error('System resource check failed', ex)
            return False
    
    async def _check_queue_health(self) -> bool:
        """Check SQS queue health"""
        try:
            # Add your queue health check logic here
            # For example, check if queues are accessible and not backing up
            return True
        except Exception as ex:
            self.logger.error('Queue health check failed', ex)
            return False

class DataCleanupTask(CronjobTask):
    """Task for cleaning up old data"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService):
        super().__init__('data_cleanup', 'Data Cleanup', 'Clean up old and unnecessary data')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
    
    async def execute(self, context: Dict[str, Any]) -> bool:
        try:
            # Clean up old logs
            await self._cleanup_old_logs()
            
            # Clean up old notifications
            await self._cleanup_old_notifications()
            
            # Clean up old temporary data
            await self._cleanup_temp_data()
            
            # Clean up old statistics
            await self._cleanup_old_statistics()
            
            self.logger.info('Data cleanup completed successfully')
            return True
            
        except Exception as ex:
            self.logger.error('Data cleanup task failed', ex)
            return False
    
    async def _cleanup_old_logs(self):
        """Clean up old log entries"""
        try:
            # Clean up logs older than 30 days
            cutoff_date = datetime.now() - timedelta(days=30)
            
            # Get old log entries
            old_logs = await self.db_client.getOldLogs(cutoff_date)
            
            # Delete old logs
            deleted_count = 0
            for log_entry in old_logs:
                await self.db_client.deleteLogEntry(log_entry.get('id'))
                deleted_count += 1
            
            self.logger.info(f'Cleaned up {deleted_count} old log entries')
            
        except Exception as ex:
            self.logger.error('Error cleaning up old logs', ex)
    
    async def _cleanup_old_notifications(self):
        """Clean up old notifications"""
        try:
            # Clean up notifications older than 7 days
            cutoff_date = datetime.now() - timedelta(days=7)
            
            # Get old notifications
            old_notifications = await self.db_client.getOldNotifications(cutoff_date)
            
            # Delete old notifications
            deleted_count = 0
            for notification in old_notifications:
                await self.db_client.deleteNotification(notification.get('id'))
                deleted_count += 1
            
            self.logger.info(f'Cleaned up {deleted_count} old notifications')
            
        except Exception as ex:
            self.logger.error('Error cleaning up old notifications', ex)
    
    async def _cleanup_temp_data(self):
        """Clean up temporary data"""
        try:
            # Clean up temporary files and data
            temp_data = await self.db_client.getTempData()
            
            deleted_count = 0
            for temp_item in temp_data:
                # Check if temp data is older than 1 day
                created_at = temp_item.get('created_at')
                if created_at and (datetime.now() - created_at).days > 1:
                    await self.db_client.deleteTempData(temp_item.get('id'))
                    deleted_count += 1
            
            self.logger.info(f'Cleaned up {deleted_count} temporary data items')
            
        except Exception as ex:
            self.logger.error('Error cleaning up temporary data', ex)
    
    async def _cleanup_old_statistics(self):
        """Clean up old statistics"""
        try:
            # Clean up statistics older than 90 days
            cutoff_date = datetime.now() - timedelta(days=90)
            
            # Get old statistics
            old_stats = await self.db_client.getOldStatistics(cutoff_date)
            
            # Delete old statistics
            deleted_count = 0
            for stat in old_stats:
                await self.db_client.deleteStatistic(stat.get('id'))
                deleted_count += 1
            
            self.logger.info(f'Cleaned up {deleted_count} old statistics')
            
        except Exception as ex:
            self.logger.error('Error cleaning up old statistics', ex)

class GameReminderTask(CronjobTask):
    """Task for sending game reminders"""
    
    def __init__(self, logger: Logger, db_client: DbClientBase, messaging_service: MessagingService):
        super().__init__('game_reminder', 'Game Reminder', 'Send game reminder notifications')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
    
    async def execute(self, context: Dict[str, Any]) -> bool:
        try:
            # Get games starting in the next hour
            upcoming_games = await self.db_client.getUpcomingGames(hours=1)
            
            self.logger.info(f'Processing {len(upcoming_games)} upcoming games for reminders')
            
            sent_reminders = 0
            for game in upcoming_games:
                try:
                    # Send reminders to referees
                    await self._send_game_reminders(game)
                    sent_reminders += 1
                    
                except Exception as ex:
                    self.logger.error(f'Error sending reminders for game {game.get("gameId", "unknown")}', ex)
                    continue
            
            self.logger.info(f'Sent reminders for {sent_reminders} games')
            return True
            
        except Exception as ex:
            self.logger.error('Game reminder task failed', ex)
            return False
    
    async def _send_game_reminders(self, game: Dict[str, Any]):
        """Send reminders for a specific game"""
        try:
            game_id = game.get('gameId')
            game_time = game.get('date')
            referees = game.get('referees', {})
            
            # Calculate time until game
            time_until_game = (game_time - datetime.now()).total_seconds()
            minutes_until_game = int(time_until_game / 60)
            
            # Send reminder message
            reminder_message = f"תזכורת: יש לך משחק בעוד {minutes_until_game} דקות"
            
            for referee_id, referee_data in referees.items():
                try:
                    # Send reminder via messaging service
                    if self.messaging_service:
                        await self.messaging_service.sendGameReminder(
                            referee_id, 
                            game_id, 
                            reminder_message
                        )
                    
                    self.logger.info(f'Sent reminder to referee {referee_id} for game {game_id}')
                    
                except Exception as ex:
                    self.logger.error(f'Error sending reminder to referee {referee_id}', ex)
                    continue
                    
        except Exception as ex:
            self.logger.error(f'Error sending game reminders', ex)

