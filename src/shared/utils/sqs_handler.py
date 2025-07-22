"""
SQS message handling utilities for healthcare image analysis system.
"""
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import boto3
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)


@dataclass
class S3EventMessage:
    """Represents an S3 event message from SQS"""
    bucket_name: str
    object_key: str
    event_name: str
    event_time: datetime
    object_size: int
    etag: str
    
    @classmethod
    def from_sqs_record(cls, record: Dict[str, Any]) -> 'S3EventMessage':
        """Create S3EventMessage from SQS record"""
        try:
            # Parse the S3 event from SQS message body
            message_body = json.loads(record['body'])
            
            # Handle both direct S3 events and SNS-wrapped events
            if 'Records' in message_body:
                s3_record = message_body['Records'][0]
            else:
                # If it's an SNS message, extract the S3 event
                sns_message = json.loads(message_body['Message'])
                s3_record = sns_message['Records'][0]
            
            s3_info = s3_record['s3']
            
            return cls(
                bucket_name=s3_info['bucket']['name'],
                object_key=s3_info['object']['key'],
                event_name=s3_record['eventName'],
                event_time=datetime.fromisoformat(
                    s3_record['eventTime'].replace('Z', '+00:00')
                ),
                object_size=s3_info['object']['size'],
                etag=s3_info['object']['eTag']
            )
        except (KeyError, json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse S3 event from SQS record: {e}")
            raise ValueError(f"Invalid S3 event message format: {e}")


class SQSMessageHandler:
    """Handles SQS message processing for S3 events"""
    
    def __init__(self, queue_url: str, region_name: str = 'us-east-1'):
        """
        Initialize SQS message handler
        
        Args:
            queue_url: SQS queue URL
            region_name: AWS region name
        """
        self.queue_url = queue_url
        self.region_name = region_name
        self.sqs_client = boto3.client('sqs', region_name=region_name)
        
    def receive_messages(self, max_messages: int = 10, wait_time: int = 20) -> List[Dict[str, Any]]:
        """
        Receive messages from SQS queue
        
        Args:
            max_messages: Maximum number of messages to receive (1-10)
            wait_time: Long polling wait time in seconds (0-20)
            
        Returns:
            List of SQS message records
        """
        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=min(wait_time, 20),
                MessageAttributeNames=['All'],
                AttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            logger.info(f"Received {len(messages)} messages from SQS queue")
            return messages
            
        except ClientError as e:
            logger.error(f"Failed to receive messages from SQS: {e}")
            raise
        except BotoCoreError as e:
            logger.error(f"AWS service error while receiving messages: {e}")
            raise
    
    def delete_message(self, receipt_handle: str) -> bool:
        """
        Delete a message from the SQS queue
        
        Args:
            receipt_handle: Receipt handle of the message to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.debug("Successfully deleted message from SQS queue")
            return True
            
        except ClientError as e:
            logger.error(f"Failed to delete message from SQS: {e}")
            return False
        except BotoCoreError as e:
            logger.error(f"AWS service error while deleting message: {e}")
            return False
    
    def delete_messages_batch(self, receipt_handles: List[str]) -> Dict[str, List[str]]:
        """
        Delete multiple messages from SQS queue in batch
        
        Args:
            receipt_handles: List of receipt handles to delete
            
        Returns:
            Dictionary with 'successful' and 'failed' lists of receipt handles
        """
        if not receipt_handles:
            return {'successful': [], 'failed': []}
        
        # SQS batch delete supports max 10 messages
        batch_size = 10
        successful = []
        failed = []
        
        for i in range(0, len(receipt_handles), batch_size):
            batch = receipt_handles[i:i + batch_size]
            
            try:
                entries = [
                    {'Id': str(idx), 'ReceiptHandle': handle}
                    for idx, handle in enumerate(batch)
                ]
                
                response = self.sqs_client.delete_message_batch(
                    QueueUrl=self.queue_url,
                    Entries=entries
                )
                
                # Track successful deletions
                for success in response.get('Successful', []):
                    idx = int(success['Id'])
                    successful.append(batch[idx])
                
                # Track failed deletions
                for failure in response.get('Failed', []):
                    idx = int(failure['Id'])
                    failed.append(batch[idx])
                    logger.error(f"Failed to delete message: {failure}")
                    
            except (ClientError, BotoCoreError) as e:
                logger.error(f"Batch delete failed for batch: {e}")
                failed.extend(batch)
        
        logger.info(f"Batch delete completed: {len(successful)} successful, {len(failed)} failed")
        return {'successful': successful, 'failed': failed}
    
    def send_message(self, message_body: str, message_attributes: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Send a message to the SQS queue
        
        Args:
            message_body: Message content as string
            message_attributes: Optional message attributes
            
        Returns:
            Message ID if successful, None otherwise
        """
        try:
            params = {
                'QueueUrl': self.queue_url,
                'MessageBody': message_body
            }
            
            if message_attributes:
                params['MessageAttributes'] = message_attributes
            
            response = self.sqs_client.send_message(**params)
            message_id = response['MessageId']
            logger.debug(f"Successfully sent message to SQS: {message_id}")
            return message_id
            
        except ClientError as e:
            logger.error(f"Failed to send message to SQS: {e}")
            return None
        except BotoCoreError as e:
            logger.error(f"AWS service error while sending message: {e}")
            return None
    
    def parse_s3_events(self, messages: List[Dict[str, Any]]) -> List[S3EventMessage]:
        """
        Parse S3 events from SQS messages
        
        Args:
            messages: List of SQS message records
            
        Returns:
            List of parsed S3EventMessage objects
        """
        s3_events = []
        
        for message in messages:
            try:
                s3_event = S3EventMessage.from_sqs_record(message)
                s3_events.append(s3_event)
            except ValueError as e:
                logger.warning(f"Skipping invalid S3 event message: {e}")
                continue
        
        return s3_events
    
    def validate_message_format(self, message: Dict[str, Any]) -> bool:
        """
        Validate SQS message format for S3 events
        
        Args:
            message: SQS message record
            
        Returns:
            True if valid, False otherwise
        """
        try:
            required_fields = ['Body', 'ReceiptHandle', 'MessageId']
            
            for field in required_fields:
                if field not in message:
                    logger.error(f"Missing required field in SQS message: {field}")
                    return False
            
            # Try to parse the message body
            S3EventMessage.from_sqs_record(message)
            return True
            
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"Invalid message format: {e}")
            return False


def create_sqs_handler(queue_url: str, region_name: str = 'us-east-1') -> SQSMessageHandler:
    """
    Factory function to create SQS message handler
    
    Args:
        queue_url: SQS queue URL
        region_name: AWS region name
        
    Returns:
        Configured SQSMessageHandler instance
    """
    return SQSMessageHandler(queue_url, region_name)