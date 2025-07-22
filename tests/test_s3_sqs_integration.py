"""
Tests for S3 event handling and SQS integration
"""

import json
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.shared.utils.sqs_handler import SQSMessageHandler, S3EventMessage
from src.shared.utils.error_handler import ErrorHandler, ErrorContext, RetryableError, PermanentError


class TestS3EventMessage:
    """Test S3EventMessage parsing"""
    
    def test_from_sqs_record_valid(self):
        """Test parsing valid S3 event from SQS record"""
        sqs_record = {
            'body': json.dumps({
                'Records': [{
                    'eventVersion': '2.1',
                    'eventSource': 'aws:s3',
                    'eventTime': '2024-01-01T12:00:00.000Z',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {
                            'key': 'uploads/test-mri.nii',
                            'size': 1024000,
                            'eTag': 'test-etag'
                        }
                    }
                }]
            })
        }
        
        s3_event = S3EventMessage.from_sqs_record(sqs_record)
        
        assert s3_event.bucket_name == 'test-bucket'
        assert s3_event.object_key == 'uploads/test-mri.nii'
        assert s3_event.event_name == 'ObjectCreated:Put'
        assert s3_event.object_size == 1024000
        assert s3_event.etag == 'test-etag'
        assert isinstance(s3_event.event_time, datetime)
    
    def test_from_sqs_record_invalid(self):
        """Test parsing invalid S3 event from SQS record"""
        sqs_record = {
            'body': json.dumps({
                'invalid': 'format'
            })
        }
        
        with pytest.raises(ValueError):
            S3EventMessage.from_sqs_record(sqs_record)


class TestSQSMessageHandler:
    """Test SQS message handler"""
    
    @patch('boto3.client')
    def test_init(self, mock_boto_client):
        """Test SQS handler initialization"""
        handler = SQSMessageHandler('test-queue-url', 'us-east-1')
        
        assert handler.queue_url == 'test-queue-url'
        assert handler.region_name == 'us-east-1'
        mock_boto_client.assert_called_with('sqs', region_name='us-east-1')
    
    @patch('boto3.client')
    def test_receive_messages_success(self, mock_boto_client):
        """Test successful message receiving"""
        mock_sqs = Mock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.receive_message.return_value = {
            'Messages': [
                {'MessageId': '1', 'Body': 'test1'},
                {'MessageId': '2', 'Body': 'test2'}
            ]
        }
        
        handler = SQSMessageHandler('test-queue-url')
        messages = handler.receive_messages(max_messages=5, wait_time=10)
        
        assert len(messages) == 2
        mock_sqs.receive_message.assert_called_once_with(
            QueueUrl='test-queue-url',
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10,
            MessageAttributeNames=['All'],
            AttributeNames=['All']
        )
    
    @patch('boto3.client')
    def test_delete_message_success(self, mock_boto_client):
        """Test successful message deletion"""
        mock_sqs = Mock()
        mock_boto_client.return_value = mock_sqs
        
        handler = SQSMessageHandler('test-queue-url')
        result = handler.delete_message('test-receipt-handle')
        
        assert result is True
        mock_sqs.delete_message.assert_called_once_with(
            QueueUrl='test-queue-url',
            ReceiptHandle='test-receipt-handle'
        )
    
    @patch('boto3.client')
    def test_parse_s3_events(self, mock_boto_client):
        """Test parsing S3 events from SQS messages"""
        handler = SQSMessageHandler('test-queue-url')
        
        messages = [
            {
                'body': json.dumps({
                    'Records': [{
                        'eventVersion': '2.1',
                        'eventSource': 'aws:s3',
                        'eventTime': '2024-01-01T12:00:00.000Z',
                        'eventName': 'ObjectCreated:Put',
                        's3': {
                            'bucket': {'name': 'test-bucket'},
                            'object': {
                                'key': 'uploads/test1.nii',
                                'size': 1024000,
                                'eTag': 'etag1'
                            }
                        }
                    }]
                })
            },
            {
                'body': json.dumps({
                    'Records': [{
                        'eventVersion': '2.1',
                        'eventSource': 'aws:s3',
                        'eventTime': '2024-01-01T12:05:00.000Z',
                        'eventName': 'ObjectCreated:Put',
                        's3': {
                            'bucket': {'name': 'test-bucket'},
                            'object': {
                                'key': 'uploads/test2.nii.gz',
                                'size': 2048000,
                                'eTag': 'etag2'
                            }
                        }
                    }]
                })
            }
        ]
        
        s3_events = handler.parse_s3_events(messages)
        
        assert len(s3_events) == 2
        assert s3_events[0].object_key == 'uploads/test1.nii'
        assert s3_events[1].object_key == 'uploads/test2.nii.gz'


class TestErrorHandler:
    """Test error handling utilities"""
    
    def test_error_context_creation(self):
        """Test error context creation"""
        context = ErrorContext(
            function_name="test_function",
            operation="test_operation",
            resource_id="test_resource",
            user_id="test_user"
        )
        
        assert context.function_name == "test_function"
        assert context.operation == "test_operation"
        assert context.resource_id == "test_resource"
        assert context.user_id == "test_user"
    
    def test_error_handler_creation(self):
        """Test error handler creation"""
        context = ErrorContext(
            function_name="test_function",
            operation="test_operation"
        )
        
        handler = ErrorHandler(context)
        assert handler.context == context
    
    def test_handle_error(self):
        """Test error handling"""
        context = ErrorContext(
            function_name="test_function",
            operation="test_operation",
            resource_id="test_resource"
        )
        
        handler = ErrorHandler(context)
        error = ValueError("Test error")
        
        error_info = handler.handle_error(error)
        
        assert error_info['error_type'] == 'ValueError'
        assert error_info['error_message'] == 'Test error'
        assert error_info['function_name'] == 'test_function'
        assert error_info['operation'] == 'test_operation'
        assert error_info['resource_id'] == 'test_resource'
    
    def test_create_lambda_response(self):
        """Test Lambda response creation"""
        context = ErrorContext(
            function_name="test_function",
            operation="test_operation"
        )
        
        handler = ErrorHandler(context)
        error = ValueError("Test error")
        
        response = handler.create_lambda_response(error, 400)
        
        assert response['statusCode'] == 400
        assert response['headers']['Content-Type'] == 'application/json'
        assert response['headers']['X-Error-Type'] == 'ValueError'
        assert response['body']['error'] == 'Test error'


if __name__ == "__main__":
    pytest.main([__file__])