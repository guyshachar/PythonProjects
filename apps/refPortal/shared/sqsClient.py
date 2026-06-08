import boto3
import json
import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class SqsClient:
    def __init__(self, logger: Logger, queue_url: str, dlq_url: str = None):
        self.logger = logger
        self.queue_url = queue_url
        self.dlq_url = dlq_url
        self.sqs = boto3.client('sqs')
        
    def send_message(self, message: str, delay_seconds: int = 0, message_attributes: Dict = None):
        """Send a message to the SQS queue"""
        try:
            params = {
                'QueueUrl': self.queue_url,
                'MessageBody': message
            }
            
            if delay_seconds > 0:
                params['DelaySeconds'] = delay_seconds
                
            if message_attributes:
                params['MessageAttributes'] = message_attributes
                
            response = self.sqs.send_message(**params)
            self.logger.debug(f'Message sent successfully: {response["MessageId"]}')
            return response
        except Exception as ex:
            self.logger.error(f'Error sending message to SQS', ex)
            raise
    
    def receive_message(self, max_messages: int = 1, wait_time_seconds: int = 0, 
                       visibility_timeout: int = 30, message_attribute_names: List[str] = None) -> List[Dict]:
        """Receive messages from the SQS queue"""
        try:
            params = {
                'QueueUrl': self.queue_url,
                'MaxNumberOfMessages': max_messages,
                'VisibilityTimeout': visibility_timeout,
                'WaitTimeSeconds': wait_time_seconds
            }
            
            if message_attribute_names:
                params['MessageAttributeNames'] = message_attribute_names
                
            response = self.sqs.receive_message(**params)
            messages = response.get('Messages', [])
            
            self.logger.debug(f'Received {len(messages)} messages from SQS')
            return messages
            
        except Exception as ex:
            self.logger.error(f'Error receiving messages from SQS', ex)
            raise
    
    def delete_message(self, receipt_handle: str):
        """Delete a message from the SQS queue after processing"""
        try:
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            self.logger.debug(f'Message deleted successfully')
        except Exception as ex:
            self.logger.error(f'Error deleting message from SQS', ex)
            raise
    
    def change_message_visibility(self, receipt_handle: str, visibility_timeout: int):
        """Change the visibility timeout of a message"""
        try:
            self.sqs.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout
            )
            self.logger.debug(f'Message visibility changed to {visibility_timeout} seconds')
        except Exception as ex:
            self.logger.error(f'Error changing message visibility', ex)
            raise
    
    async def poll_messages(
            self, 
            message_processor: Callable[[Dict], Any], 
            max_messages: int = 1, 
            wait_time_seconds: int = 20,
            visibility_timeout: int = 30, 
            auto_delete: bool = True,
            max_retries: int = 3,
            dlq_enabled: bool = True):
        """Continuously poll for messages and process them with DLQ support"""
        self.logger.info(f'Starting SQS polling for queue: {self.queue_url}')
        if dlq_enabled and self.dlq_url:
            self.logger.info(f'DLQ enabled: {self.dlq_url}')
        
        while True:
            try:
                messages = self.receive_message(
                    max_messages=max_messages,
                    wait_time_seconds=wait_time_seconds,
                    visibility_timeout=visibility_timeout
                )
                
                if not messages:
                    continue
                
                for message in messages:
                    try:
                        self.logger.debug(f"Processing message: {message['MessageId']}")
                        
                        # Parse message body if it's JSON
                        message_body = message['Body']
                        try:
                            parsed_body = json.loads(message_body)
                        except json.JSONDecodeError:
                            parsed_body = message_body
                        
                        # Add parsed body to message for easier processing
                        message['ParsedBody'] = parsed_body
                        
                        # Process the message with DLQ support
                        await self._process_message_with_dlq(
                            message, message_processor, max_retries, dlq_enabled
                        )
                        
                        # Delete message after successful processing
                        if auto_delete:
                            self.delete_message(message['ReceiptHandle'])
                            
                    except Exception as ex:
                        self.logger.error(f'Error processing message {message.get("MessageId", "unknown")}', ex)
                        # Don't delete the message so it can be retried
                        continue
                        
            except Exception as ex:
                self.logger.error(f'Error in SQS polling loop', ex)
                await asyncio.sleep(5)  # Wait before retrying
    
    async def _process_message_with_dlq(self, message: Dict, message_processor: Callable, 
                                       max_retries: int, dlq_enabled: bool):
        """Process a message with retry logic and DLQ support"""
        message_id = message.get('MessageId', 'unknown')
        receipt_handle = message.get('ReceiptHandle')
        
        for attempt in range(max_retries):
            try:
                if asyncio.iscoroutinefunction(message_processor):
                    await message_processor(message)
                else:
                    message_processor(message)
                return  # Success
                
            except Exception as ex:
                self.logger.warning(f'Message {message_id} processing attempt {attempt + 1} failed:', ex)
                
                if attempt < max_retries - 1:
                    # Extend visibility timeout to prevent other consumers from picking it up
                    self.change_message_visibility(
                        receipt_handle, 
                        visibility_timeout=30 * (attempt + 2)
                    )
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    # Final attempt failed - send to DLQ if enabled
                    if dlq_enabled and self.dlq_url:
                        await self._send_to_dlq(message, ex)
                    else:
                        self.logger.error(f'Message {message_id} failed all retry attempts and DLQ is disabled')
                    raise ex
    
    async def _send_to_dlq(self, message: Dict, error: Exception):
        """Send a failed message to the Dead Letter Queue"""
        try:
            message_id = message.get('MessageId', 'unknown')
            
            # Create DLQ message with original message and error details
            dlq_message = {
                'originalMessage': message,
                'error': {
                    'type': type(error).__name__,
                    'message': str(error),
                    'timestamp': asyncio.get_event_loop().time()
                },
                'dlqMetadata': {
                    'sourceQueue': self.queue_url,
                    'movedToDlqAt': asyncio.get_event_loop().time(),
                    'originalMessageId': message_id
                }
            }
            
            # Send to DLQ
            dlq_client = SqsClient(self.logger, self.dlq_url)
            dlq_client.send_message(
                message=json.dumps(dlq_message),
                message_attributes={
                    'OriginalMessageId': {
                        'StringValue': message_id,
                        'DataType': 'String'
                    },
                    'SourceQueue': {
                        'StringValue': self.queue_url,
                        'DataType': 'String'
                    },
                    'ErrorType': {
                        'StringValue': type(error).__name__,
                        'DataType': 'String'
                    }
                }
            )
            
            self.logger.warning(f'Message {message_id} sent to DLQ: {self.dlq_url}')
            
            # Delete the original message since it's now in DLQ
            self.delete_message(message['ReceiptHandle'])
            
        except Exception as dlq_ex:
            self.logger.error(f'Failed to send message {message_id} to DLQ: {dlq_ex}')
            # Don't delete the original message if DLQ send failed
            raise dlq_ex
    
    async def _process_message_with_retry(self, message: Dict, message_processor: Callable, max_retries: int):
        """Process a message with retry logic (legacy method for backward compatibility)"""
        await self._process_message_with_dlq(message, message_processor, max_retries, dlq_enabled=False)
    
    def get_queue_attributes(self) -> Dict:
        """Get queue attributes like approximate number of messages"""
        try:
            response = self.sqs.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=['All']
            )
            return response.get('Attributes', {})
        except Exception as ex:
            self.logger.error(f'Error getting queue attributes', ex)
            raise
    
    def purge_queue(self):
        """Purge all messages from the queue (use with caution!)"""
        try:
            self.sqs.purge_queue(QueueUrl=self.queue_url)
            self.logger.warning(f'Queue purged: {self.queue_url}')
        except Exception as ex:
            self.logger.error(f'Error purging queue', ex)
            raise
    
    def get_dlq_attributes(self) -> Dict:
        """Get DLQ attributes if DLQ is configured"""
        if not self.dlq_url:
            return {}
        
        try:
            dlq_client = SqsClient(self.logger, self.dlq_url)
            return dlq_client.get_queue_attributes()
        except Exception as ex:
            self.logger.error(f'Error getting DLQ attributes', ex)
            return {}
    
    async def reprocess_dlq_message(self, dlq_message: Dict, target_queue_url: str = None):
        """Reprocess a message from DLQ by sending it back to the main queue"""
        try:
            original_message = dlq_message.get('originalMessage', {})
            if not original_message:
                raise ValueError("No original message found in DLQ message")
            
            # Use target queue or original queue
            target_queue = target_queue_url or self.queue_url
            
            # Create new SQS client for target queue
            target_client = SqsClient(self.logger, target_queue)
            
            # Send original message back to queue
            target_client.send_message(
                message=original_message.get('Body', ''),
                message_attributes=original_message.get('MessageAttributes', {})
            )
            
            self.logger.info(f'DLQ message reprocessed to queue: {target_queue}')
            return True
            
        except Exception as ex:
            self.logger.error(f'Error reprocessing DLQ message', ex)
            return False
    
    async def process_dlq_messages(self, dlq_processor: Callable[[Dict], Any], 
                                  max_messages: int = 10, auto_reprocess: bool = False):
        """Process messages from DLQ for investigation or reprocessing"""
        if not self.dlq_url:
            self.logger.warning("No DLQ configured")
            return
        
        try:
            dlq_client = SqsClient(self.logger, self.dlq_url)
            messages = dlq_client.receive_message(max_messages=max_messages)
            
            for message in messages:
                try:
                    # Parse DLQ message
                    dlq_body = json.loads(message['Body'])
                    
                    self.logger.info(f"Processing DLQ message: {message['MessageId']}")
                    
                    # Process with custom processor
                    if asyncio.iscoroutinefunction(dlq_processor):
                        await dlq_processor(dlq_body, message)
                    else:
                        dlq_processor(dlq_body, message)
                    
                    # Optionally reprocess the original message
                    if auto_reprocess:
                        await self.reprocess_dlq_message(dlq_body)
                    
                    # Delete from DLQ after processing
                    dlq_client.delete_message(message['ReceiptHandle'])
                    
                except Exception as ex:
                    self.logger.error(f'Error processing DLQ message {message.get("MessageId", "unknown")}', ex)
                    continue
                    
        except Exception as ex:
            self.logger.error(f'Error processing DLQ messages', ex)
    
    def setup_dlq_redrive_policy(self, max_receive_count: int = 3):
        """Setup DLQ redrive policy for the main queue (requires AWS permissions)"""
        try:
            redrive_policy = {
                'deadLetterTargetArn': self._get_queue_arn(self.dlq_url),
                'maxReceiveCount': max_receive_count
            }
            
            self.sqs.set_queue_attributes(
                QueueUrl=self.queue_url,
                Attributes={
                    'RedrivePolicy': json.dumps(redrive_policy)
                }
            )
            
            self.logger.info(f'DLQ redrive policy set: maxReceiveCount={max_receive_count}')
            
        except Exception as ex:
            self.logger.error(f'Error setting up DLQ redrive policy', ex)
            raise
    
    def _get_queue_arn(self, queue_url: str) -> str:
        """Extract queue ARN from queue URL"""
        # Parse queue URL to get account ID and queue name
        # Format: https://sqs.region.amazonaws.com/account-id/queue-name
        parts = queue_url.split('/')
        account_id = parts[-2]
        queue_name = parts[-1]
        region = queue_url.split('.')[1]
        
        return f'arn:aws:sqs:{region}:{account_id}:{queue_name}'