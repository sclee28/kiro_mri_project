"""
Lambda function for handling S3 events and triggering the MRI analysis pipeline.
"""
import json
import logging
import os
from typing import Dict, Any, List
import boto3
from botocore.exceptions import ClientError, BotoCoreError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import shared utilities
import sys
sys.path.append('/opt/python')  # Lambda layer path
sys.path.append('/var/task')    # Lambda function path

try:
    from src.shared.utils.sqs_handler import SQSMessageHandler, S3EventMessage
    from src.shared.utils.database import db_manager, db_session_scope
    from src.shared.utils.error_handler import (
        ErrorHandler, ErrorContext, RetryableError, PermanentError,
        retry_with_backoff, safe_s3_operation, handle_lambda_errors
    )
    from src.shared.models.analysis_job import AnalysisJob, JobStatus
except ImportError as e:
    logger.error(f"Failed to import shared utilities: {e}")
    # Fallback for local testing
    pass

# Environment variables
STEP_FUNCTIONS_ARN = os.environ.get('STEP_FUNCTIONS_ARN')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# AWS clients
stepfunctions_client = boto3.client('stepfunctions', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)


@retry_with_backoff()
def validate_image_file(bucket_name: str, object_key: str) -> Dict[str, Any]:
    """
    Validate the uploaded image file
    
    Args:
        bucket_name: S3 bucket name
        object_key: S3 object key
        
    Returns:
        Dictionary with validation results
    """
    try:
        # Get object metadata using safe S3 operation
        response = safe_s3_operation(
            s3_client.head_object,
            Bucket=bucket_name,
            Key=object_key
        )
        
        file_size = response['ContentLength']
        content_type = response.get('ContentType', '')
        
        # Validate file size (max 500MB for MRI images)
        max_size = 500 * 1024 * 1024  # 500MB
        if file_size > max_size:
            raise PermanentError(
                f'File size {file_size} exceeds maximum allowed size {max_size}'
            )
        
        # Validate file extension
        valid_extensions = ['.nii', '.nii.gz', '.dcm']
        if not any(object_key.lower().endswith(ext) for ext in valid_extensions):
            raise PermanentError(
                f'Invalid file extension. Supported formats: {valid_extensions}'
            )
        
        # Check if file is empty
        if file_size == 0:
            raise PermanentError('File is empty')
        
        return {
            'valid': True,
            'file_size': file_size,
            'content_type': content_type
        }
        
    except (PermanentError, RetryableError):
        raise
    except ClientError as e:
        logger.error(f"Failed to validate file {object_key}: {e}")
        raise RetryableError(f'Failed to access file: {e}') from e
    except Exception as e:
        logger.error(f"Unexpected error validating file {object_key}: {e}")
        raise PermanentError(f'Validation error: {e}') from e


def create_analysis_job(s3_event: S3EventMessage, user_id: str = 'system') -> str:
    """
    Create a new analysis job in the database
    
    Args:
        s3_event: S3 event message
        user_id: User ID (default: 'system' for automated uploads)
        
    Returns:
        Job ID of the created job
    """
    try:
        with db_session_scope() as session:
            job = AnalysisJob(
                user_id=user_id,
                original_image_key=s3_event.object_key,
                status=JobStatus.UPLOADED
            )
            session.add(job)
            session.commit()
            
            logger.info(f"Created analysis job {job.job_id} for image {s3_event.object_key}")
            return str(job.job_id)
            
    except Exception as e:
        logger.error(f"Failed to create analysis job: {e}")
        raise


def trigger_step_functions(job_id: str, s3_event: S3EventMessage) -> str:
    """
    Trigger Step Functions workflow for image processing
    
    Args:
        job_id: Analysis job ID
        s3_event: S3 event message
        
    Returns:
        Step Functions execution ARN
    """
    try:
        # Prepare input for Step Functions
        step_input = {
            'job_id': job_id,
            'bucket_name': s3_event.bucket_name,
            'object_key': s3_event.object_key,
            'event_time': s3_event.event_time.isoformat(),
            'object_size': s3_event.object_size,
            'etag': s3_event.etag
        }
        
        # Start Step Functions execution
        response = stepfunctions_client.start_execution(
            stateMachineArn=STEP_FUNCTIONS_ARN,
            name=f"mri-analysis-{job_id}",
            input=json.dumps(step_input)
        )
        
        execution_arn = response['executionArn']
        logger.info(f"Started Step Functions execution: {execution_arn}")
        
        return execution_arn
        
    except ClientError as e:
        logger.error(f"Failed to trigger Step Functions: {e}")
        raise


def process_s3_event(s3_event: S3EventMessage) -> Dict[str, Any]:
    """
    Process a single S3 event
    
    Args:
        s3_event: S3 event message
        
    Returns:
        Processing result dictionary
    """
    error_context = ErrorContext(
        function_name="s3_event_handler",
        operation="process_s3_event",
        resource_id=s3_event.object_key,
        additional_context={
            'bucket_name': s3_event.bucket_name,
            'event_name': s3_event.event_name,
            'object_size': s3_event.object_size
        }
    )
    error_handler = ErrorHandler(error_context)
    
    try:
        logger.info(f"Processing S3 event for object: {s3_event.object_key}")
        
        # Validate the uploaded file
        validation_result = validate_image_file(s3_event.bucket_name, s3_event.object_key)
        logger.info(f"File validation successful for {s3_event.object_key}")
        
        # Create analysis job in database
        job_id = create_analysis_job(s3_event)
        logger.info(f"Created analysis job {job_id} for {s3_event.object_key}")
        
        # Trigger Step Functions workflow
        execution_arn = trigger_step_functions(job_id, s3_event)
        logger.info(f"Triggered Step Functions execution: {execution_arn}")
        
        return {
            'success': True,
            'job_id': job_id,
            'execution_arn': execution_arn,
            'object_key': s3_event.object_key,
            'file_size': validation_result['file_size']
        }
        
    except PermanentError as e:
        error_info = error_handler.handle_error(e)
        return {
            'success': False,
            'error': str(e),
            'error_type': 'permanent',
            'object_key': s3_event.object_key
        }
        
    except RetryableError as e:
        error_info = error_handler.handle_error(e)
        return {
            'success': False,
            'error': str(e),
            'error_type': 'retryable',
            'object_key': s3_event.object_key
        }
        
    except Exception as e:
        error_info = error_handler.handle_error(e)
        return {
            'success': False,
            'error': str(e),
            'error_type': 'unexpected',
            'object_key': s3_event.object_key
        }


@handle_lambda_errors(ErrorContext(
    function_name="s3_event_handler",
    operation="lambda_handler"
))
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for S3 event processing
    
    Args:
        event: Lambda event containing SQS messages
        context: Lambda context
        
    Returns:
        Processing results
    """
    logger.info(f"Received event with {len(event.get('Records', []))} records")
    
    if not STEP_FUNCTIONS_ARN:
        logger.error("STEP_FUNCTIONS_ARN environment variable not set")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Step Functions ARN not configured'})
        }
    
    results = []
    successful_count = 0
    failed_count = 0
    
    try:
        # Initialize SQS handler if needed
        sqs_handler = None
        if SQS_QUEUE_URL:
            sqs_handler = SQSMessageHandler(SQS_QUEUE_URL, AWS_REGION)
        
        # Process each SQS record
        for record in event.get('Records', []):
            try:
                # Parse S3 event from SQS message
                s3_event = S3EventMessage.from_sqs_record(record)
                
                # Process the S3 event
                result = process_s3_event(s3_event)
                results.append(result)
                
                if result['success']:
                    successful_count += 1
                    logger.info(f"Successfully processed {s3_event.object_key}")
                else:
                    failed_count += 1
                    logger.error(f"Failed to process {s3_event.object_key}: {result['error']}")
                
            except ValueError as e:
                logger.error(f"Invalid SQS message format: {e}")
                failed_count += 1
                results.append({
                    'success': False,
                    'error': f'Invalid message format: {e}',
                    'object_key': 'unknown'
                })
            except Exception as e:
                logger.error(f"Unexpected error processing record: {e}")
                failed_count += 1
                results.append({
                    'success': False,
                    'error': f'Unexpected error: {e}',
                    'object_key': 'unknown'
                })
        
        # Log summary
        logger.info(f"Processing completed: {successful_count} successful, {failed_count} failed")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Processed {len(results)} events',
                'successful': successful_count,
                'failed': failed_count,
                'results': results
            })
        }
        
    except Exception as e:
        logger.error(f"Lambda handler failed: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Lambda handler failed: {e}',
                'successful': successful_count,
                'failed': failed_count
            })
        }


# For local testing
if __name__ == "__main__":
    # Sample test event
    test_event = {
        "Records": [
            {
                "messageId": "test-message-id",
                "receiptHandle": "test-receipt-handle",
                "body": json.dumps({
                    "Records": [
                        {
                            "eventVersion": "2.1",
                            "eventSource": "aws:s3",
                            "eventTime": "2024-01-01T12:00:00.000Z",
                            "eventName": "ObjectCreated:Put",
                            "s3": {
                                "bucket": {"name": "test-bucket"},
                                "object": {
                                    "key": "uploads/test-mri.nii",
                                    "size": 1024000,
                                    "eTag": "test-etag"
                                }
                            }
                        }
                    ]
                })
            }
        ]
    }
    
    # Mock context
    class MockContext:
        def __init__(self):
            self.function_name = "test-function"
            self.memory_limit_in_mb = 128
            self.invoked_function_arn = "test-arn"
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))