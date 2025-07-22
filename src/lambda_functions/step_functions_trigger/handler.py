"""
Lambda function for triggering Step Functions workflow for MRI image analysis.

This function is responsible for starting the Step Functions state machine
execution for processing MRI images through the analysis pipeline.
"""
import json
import logging
import os
from typing import Dict, Any
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
    from src.shared.utils.error_handler import (
        ErrorHandler, ErrorContext, RetryableError, PermanentError,
        retry_with_backoff, handle_lambda_errors
    )
    from src.shared.models.analysis_job import AnalysisJob, JobStatus
    from src.shared.utils.database import db_session_scope
except ImportError as e:
    logger.error(f"Failed to import shared utilities: {e}")
    # Fallback for local testing
    pass

# Environment variables
STEP_FUNCTIONS_ARN = os.environ.get('STEP_FUNCTIONS_ARN')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# AWS clients
stepfunctions_client = boto3.client('stepfunctions', region_name=AWS_REGION)


@retry_with_backoff()
def start_step_functions_execution(job_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start a Step Functions state machine execution
    
    Args:
        job_id: Analysis job ID
        input_data: Input data for the state machine
        
    Returns:
        Dictionary with execution details
    """
    try:
        if not STEP_FUNCTIONS_ARN:
            raise PermanentError("STEP_FUNCTIONS_ARN environment variable not set")
        
        # Start Step Functions execution
        response = stepfunctions_client.start_execution(
            stateMachineArn=STEP_FUNCTIONS_ARN,
            name=f"mri-analysis-{job_id}",
            input=json.dumps(input_data)
        )
        
        execution_arn = response['executionArn']
        start_date = response['startDate']
        
        logger.info(f"Started Step Functions execution: {execution_arn}")
        
        return {
            'execution_arn': execution_arn,
            'start_date': start_date.isoformat(),
            'job_id': job_id
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        
        if error_code in ['ExecutionLimitExceeded', 'ExecutionAlreadyExists']:
            logger.error(f"Step Functions execution error: {e}")
            raise PermanentError(f"Step Functions execution error: {e}")
        else:
            logger.error(f"Failed to start Step Functions execution: {e}")
            raise RetryableError(f"Failed to start Step Functions execution: {e}")
    
    except Exception as e:
        logger.error(f"Unexpected error starting Step Functions execution: {e}")
        raise


def update_job_status(job_id: str, status: JobStatus, error_message: str = None) -> None:
    """
    Update the status of an analysis job in the database
    
    Args:
        job_id: Analysis job ID
        status: New job status
        error_message: Optional error message
    """
    try:
        with db_session_scope() as session:
            job = session.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
            
            if not job:
                logger.error(f"Job {job_id} not found in database")
                return
            
            job.status = status
            if error_message:
                job.error_message = error_message
            
            session.commit()
            logger.info(f"Updated job {job_id} status to {status.value}")
            
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
        raise


@handle_lambda_errors(ErrorContext(
    function_name="step_functions_trigger",
    operation="lambda_handler"
))
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for triggering Step Functions workflow
    
    Args:
        event: Lambda event containing job details
        context: Lambda context
        
    Returns:
        Processing results
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract job details from event
        job_id = event.get('job_id')
        bucket_name = event.get('bucket_name')
        object_key = event.get('object_key')
        
        if not all([job_id, bucket_name, object_key]):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing required parameters',
                    'required': ['job_id', 'bucket_name', 'object_key']
                })
            }
        
        # Update job status to processing
        update_job_status(job_id, JobStatus.SEGMENTING)
        
        # Prepare input for Step Functions
        step_input = {
            'job_id': job_id,
            'bucket_name': bucket_name,
            'object_key': object_key,
            'event_time': event.get('event_time'),
            'object_size': event.get('object_size'),
            'etag': event.get('etag'),
            'execution_id': f"mri-analysis-{job_id}"
        }
        
        # Start Step Functions execution
        execution_result = start_step_functions_execution(job_id, step_input)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Step Functions workflow triggered successfully',
                'execution_arn': execution_result['execution_arn'],
                'job_id': job_id
            })
        }
        
    except PermanentError as e:
        logger.error(f"Permanent error: {e}")
        if 'job_id' in event:
            update_job_status(event['job_id'], JobStatus.FAILED, str(e))
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'error_type': 'permanent'
            })
        }
        
    except RetryableError as e:
        logger.error(f"Retryable error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'error_type': 'retryable'
            })
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if 'job_id' in event:
            update_job_status(event['job_id'], JobStatus.FAILED, str(e))
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'error_type': 'unexpected'
            })
        }


# For local testing
if __name__ == "__main__":
    # Sample test event
    test_event = {
        "job_id": "12345678-1234-5678-abcd-1234567890ab",
        "bucket_name": "healthcare-mri-images-123456789012",
        "object_key": "uploads/test-mri.nii",
        "event_time": "2024-01-01T12:00:00.000Z",
        "object_size": 1024000,
        "etag": "test-etag"
    }
    
    # Mock context
    class MockContext:
        def __init__(self):
            self.function_name = "test-function"
            self.memory_limit_in_mb = 128
            self.invoked_function_arn = "test-arn"
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))