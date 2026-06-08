"""
Dead Letter Queue (DLQ) Usage Examples for RefPortal
Shows how to implement and use DLQ functionality with SQS
"""

import asyncio
from shared.logger import Logger
from shared.sqsClient import SqsClient
from shared.db import DynamodbClient
from newArchitecture.messageReceiver import MessageReceiver, RefPortalMessageProcessors

async def example_dlq_setup_and_usage():
    """Complete example of DLQ setup and usage"""
    
    # Initialize dependencies
    logger = Logger()
    db_client = DynamodbClient(env='local', logger=logger, awsRegion='us-east-1')
    
    # Queue URLs
    main_queue_url = 'https://sqs.us-east-1.amazonaws.com/123456789/refportal-main-queue'
    dlq_url = 'https://sqs.us-east-1.amazonaws.com/123456789/refportal-dlq'
    
    # Create SQS client with DLQ support
    sqs_client = SqsClient(logger, main_queue_url, dlq_url)
    
    # Setup DLQ redrive policy (run once to configure AWS)
    try:
        sqs_client.setup_dlq_redrive_policy(max_receive_count=3)
        logger.info("DLQ redrive policy configured successfully")
    except Exception as ex:
        logger.warning(f"Could not setup DLQ redrive policy:", ex)
    
    # Example 1: Basic message processing with DLQ
    await example_basic_dlq_processing(sqs_client, logger)
    
    # Example 2: Custom DLQ processor
    await example_custom_dlq_processor(sqs_client, logger)
    
    # Example 3: DLQ message reprocessing
    await example_dlq_reprocessing(sqs_client, logger)
    
    # Example 4: Using MessageReceiver with DLQ
    await example_message_receiver_with_dlq(logger, db_client, sqs_client)

async def example_basic_dlq_processing(sqs_client: SqsClient, logger: Logger):
    """Example of basic message processing with automatic DLQ handling"""
    
    async def failing_message_processor(message):
        """A processor that will fail to demonstrate DLQ functionality"""
        message_body = message.get('ParsedBody', {})
        
        # Simulate different types of failures
        if 'fail_immediately' in message_body:
            raise ValueError("Immediate failure for testing")
        elif 'fail_after_retry' in message_body:
            # This will fail after retries and go to DLQ
            raise ConnectionError("Connection failed after retries")
        else:
            logger.info(f"Successfully processed message: {message_body}")
    
    logger.info("Starting basic DLQ processing example...")
    
    # Start polling with DLQ enabled
    # Messages that fail will automatically be sent to DLQ after max_retries
    await sqs_client.poll_messages(
        message_processor=failing_message_processor,
        max_messages=5,
        wait_time_seconds=20,
        max_retries=3,
        dlq_enabled=True
    )

async def example_custom_dlq_processor(sqs_client: SqsClient, logger: Logger):
    """Example of custom DLQ message processing"""
    
    async def custom_dlq_processor(dlq_message: dict, message: dict):
        """Custom processor for DLQ messages"""
        original_message = dlq_message.get('originalMessage', {})
        error_info = dlq_message.get('error', {})
        
        logger.error(f"DLQ Alert: Message failed processing")
        logger.error(f"  Original: {original_message.get('Body', '')}")
        logger.error(f"  Error: {error_info.get('type')} - {error_info.get('message')}")
        
        # Custom logic for different error types
        error_type = error_info.get('type', '')
        
        if error_type == 'ValueError':
            # Handle validation errors
            logger.info("Attempting to fix validation error...")
            # Add your fix logic here
            
        elif error_type == 'ConnectionError':
            # Handle connection errors
            logger.info("Connection error detected - may need manual intervention")
            # Send alert to administrators
            
        elif error_type == 'TimeoutError':
            # Handle timeout errors
            logger.info("Timeout error - message may need reprocessing")
            # Could automatically reprocess with longer timeout
    
    logger.info("Processing DLQ messages with custom processor...")
    
    # Process DLQ messages
    await sqs_client.process_dlq_messages(
        dlq_processor=custom_dlq_processor,
        max_messages=10
    )

async def example_dlq_reprocessing(sqs_client: SqsClient, logger: Logger):
    """Example of reprocessing messages from DLQ"""
    
    async def reprocess_processor(dlq_message: dict, message: dict):
        """Processor that reprocesses DLQ messages"""
        original_message = dlq_message.get('originalMessage', {})
        error_info = dlq_message.get('error', {})
        
        logger.info(f"Reprocessing DLQ message: {message['MessageId']}")
        
        # Check if this is a recoverable error
        error_type = error_info.get('type', '')
        if error_type in ['ConnectionError', 'TimeoutError']:
            # These errors might be temporary, try reprocessing
            logger.info(f"Attempting to reprocess message after {error_type}")
            
            # Reprocess the original message
            success = await sqs_client.reprocess_dlq_message(dlq_message)
            if success:
                logger.info("Message successfully reprocessed")
            else:
                logger.error("Failed to reprocess message")
        else:
            # Non-recoverable errors - just log for investigation
            logger.error(f"Non-recoverable error: {error_type}")
    
    logger.info("Reprocessing DLQ messages...")
    
    # Process DLQ messages with reprocessing
    await sqs_client.process_dlq_messages(
        dlq_processor=reprocess_processor,
        max_messages=10,
        auto_reprocess=False  # We handle reprocessing manually
    )

async def example_message_receiver_with_dlq(logger: Logger, db_client, sqs_client: SqsClient):
    """Example using MessageReceiver with DLQ support"""
    
    # Create message receiver
    receiver = MessageReceiver(logger, db_client, sqs_client)
    
    # Create processors
    processors = RefPortalMessageProcessors(logger, db_client)
    
    # Register processors
    receiver.register_processor('tournament', processors.process_tournament_update)
    receiver.register_processor('referee', processors.process_referee_assignment)
    receiver.register_processor('notification', processors.process_game_notification)
    
    # Custom DLQ processor for RefPortal
    async def refportal_dlq_processor(dlq_message: dict, message: dict):
        """RefPortal-specific DLQ processor"""
        original_message = dlq_message.get('originalMessage', {})
        error_info = dlq_message.get('error', {})
        
        logger.error(f"RefPortal DLQ Alert:")
        logger.error(f"  Message Type: {original_message.get('ParsedBody', {}).get('action', 'unknown')}")
        logger.error(f"  Error: {error_info.get('type')} - {error_info.get('message')}")
        
        # Store in database for investigation
        try:
            db_client.setRefereeProperties(
                refId='system',
                value={
                    'dlqMessage': dlq_message,
                    'timestamp': asyncio.get_event_loop().time()
                },
                propertyName='dlqInvestigation'
            )
        except Exception as ex:
            logger.error(f"Failed to store DLQ message in database:", ex)
    
    logger.info("Starting MessageReceiver with DLQ support...")
    
    # Start main message processing with DLQ
    await receiver.start_sqs_polling(
        dlq_url=sqs_client.dlq_url,
        max_messages=10,
        wait_time_seconds=20,
        max_retries=3,
        dlq_enabled=True
    )
    
    # In a separate task, process DLQ messages
    asyncio.create_task(
        receiver.start_dlq_processing(
            dlq_processor=refportal_dlq_processor,
            max_messages=5
        )
    )

async def example_dlq_monitoring(sqs_client: SqsClient, logger: Logger):
    """Example of monitoring DLQ health"""
    
    def check_dlq_health():
        """Check DLQ health and alert if needed"""
        try:
            # Get main queue attributes
            main_attrs = sqs_client.get_queue_attributes()
            main_messages = int(main_attrs.get('ApproximateNumberOfMessages', 0))
            
            # Get DLQ attributes
            dlq_attrs = sqs_client.get_dlq_attributes()
            dlq_messages = int(dlq_attrs.get('ApproximateNumberOfMessages', 0))
            
            logger.info(f"Queue Health Check:")
            logger.info(f"  Main Queue Messages: {main_messages}")
            logger.info(f"  DLQ Messages: {dlq_messages}")
            
            # Alert if DLQ has messages
            if dlq_messages > 0:
                logger.warning(f"DLQ has {dlq_messages} messages - investigation needed!")
                
                # You could send alerts here:
                # - Email notifications
                # - Slack messages
                # - CloudWatch alarms
                # - etc.
            
            # Alert if main queue is backing up
            if main_messages > 100:
                logger.warning(f"Main queue has {main_messages} messages - may need scaling!")
                
        except Exception as ex:
            logger.error(f"Error checking queue health:", ex)
    
    # Run health check
    check_dlq_health()

# Example of how to integrate DLQ into your existing services
class RefPortalServiceWithDLQ:
    """Example service class showing DLQ integration"""
    
    def __init__(self, logger: Logger, db_client, messaging_service):
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
        
        # Setup SQS with DLQ
        self.main_queue_url = 'https://sqs.us-east-1.amazonaws.com/123456789/refportal-main'
        self.dlq_url = 'https://sqs.us-east-1.amazonaws.com/123456789/refportal-dlq'
        self.sqs_client = SqsClient(logger, self.main_queue_url, self.dlq_url)
        
        # Setup message receiver
        self.message_receiver = MessageReceiver(logger, db_client, self.sqs_client)
        self._setup_processors()
    
    def _setup_processors(self):
        """Setup message processors"""
        processors = RefPortalMessageProcessors(self.logger, self.db_client, self.messaging_service)
        
        self.message_receiver.register_processor('tournament', processors.process_tournament_update)
        self.message_receiver.register_processor('referee', processors.process_referee_assignment)
        self.message_receiver.register_processor('twilio', processors.process_messaging_webhook)
        self.message_receiver.register_processor('meta', processors.process_messaging_webhook)
        self.message_receiver.register_processor('notification', processors.process_game_notification)
    
    async def start(self):
        """Start the service with DLQ support"""
        self.logger.info("Starting RefPortal service with DLQ support...")
        
        # Start main message processing
        main_task = asyncio.create_task(
            self.message_receiver.start_sqs_polling(
                dlq_url=self.dlq_url,
                max_messages=10,
                wait_time_seconds=20,
                max_retries=3,
                dlq_enabled=True
            )
        )
        
        # Start DLQ processing
        dlq_task = asyncio.create_task(
            self.message_receiver.start_dlq_processing(
                max_messages=5
            )
        )
        
        # Start monitoring
        monitoring_task = asyncio.create_task(self._monitor_queues())
        
        # Wait for tasks
        await asyncio.gather(main_task, dlq_task, monitoring_task)
    
    async def _monitor_queues(self):
        """Monitor queue health"""
        while True:
            try:
                # Check DLQ health every 5 minutes
                await asyncio.sleep(300)
                
                dlq_attrs = self.sqs_client.get_dlq_attributes()
                dlq_messages = int(dlq_attrs.get('ApproximateNumberOfMessages', 0))
                
                if dlq_messages > 0:
                    self.logger.warning(f"DLQ has {dlq_messages} messages - investigation needed!")
                    
                    # Send alert to administrators
                    await self._send_dlq_alert(dlq_messages)
                    
            except Exception as ex:
                self.logger.error(f"Error in queue monitoring:", ex)
    
    async def _send_dlq_alert(self, dlq_count: int):
        """Send alert about DLQ messages"""
        try:
            alert_message = f"RefPortal DLQ Alert: {dlq_count} messages in DLQ require investigation"
            
            # Send via your messaging service
            if self.messaging_service:
                # You could send to admin mobile, Slack, etc.
                self.logger.warning(alert_message)
                
        except Exception as ex:
            self.logger.error(f"Failed to send DLQ alert:", ex)

if __name__ == "__main__":
    # Run the examples
    asyncio.run(example_dlq_setup_and_usage())

