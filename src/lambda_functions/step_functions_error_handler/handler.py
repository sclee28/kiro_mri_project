"""
Lambda function for handling errors in the Step Functions state machine.

This function is responsible for handling errors that occur during the
execution of the MRI image analysis pipeline and updating job status accordingly.
"""
import json
import logging
import os
from typing import Dict, Any
from datetime import datetime
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
        ErrorHandler, ErrorContext, handle_lambda_errors
    )
    from src.shared.models.analysis_job import AnalysisJob, JobStatus
    from src.shared.utils.database import db_session_scope
except ImportError as e:
    logger.error(f"Failed to import shared utilities: {e}")
    # Fallback for local testing
    pass

# Environment variables
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
CLOUDWATCH_LOG_GROUP = os.environ.get('CLOUDWATCH_LOG_GROUP', '/aws/lambda/mri-analysis')

# AWS clients
logs_client = boto3.client('logs', region_name=AWS_REGION)


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


def log_error_to_cloudwatch(execution_id: str, stage: str, error_details: Dict[str, Any]) -> None:
    """
    Log error details to CloudWatch Logs
    
    Args:
        execution_id: Step Functions execution ID
        stage: Processing stage where the error occurred
        error_details: Error details to log
    """
    try:
        log_stream_name = f"step-functions-error-{execution_id}"
        
        # Create log stream if it doesn't exist
        try:
            logs_client.create_log_stream(
                logGroupName=CLOUDWATCH_LOG_GROUP,
                logStreamName=log_stream_name
            )
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                logger.error(f"Failed to create log stream: {e}")
                raise
        
        # Log error details
        logs_client.put_log_events(
            logGroupName=CLOUDWATCH_LOG_GROUP,
            logStreamName=log_stream_name,
            logEvents=[
                {
                    'timestamp': int(datetime.now().timestamp() * 1000),
                    'message': json.dumps({
                        'execution_id': execution_id,
                        'stage': stage,
                        'error': error_details
                    })
                }
            ]
        )
        
        logger.info(f"Logged error details to CloudWatch for execution {execution_id}")
        
    except Exception as e:
        logger.error(f"Failed to log error to CloudWatch: {e}")


@handle_lambda_errors(ErrorContext(
    function_name="step_functions_error_handler",
    operation="lambda_handler"
))
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for handling Step Functions errors
    
    Args:
        event: Lambda event containing error details
        context: Lambda context
        
    Returns:
        Processing results
    """
    logger.info(f"Received error event: {json.dumps(event)}")
    
    try:
        # Extract error details from event
        job_id = event.get('job_id')
        stage = event.get('stage', 'unknown')
        execution_id = event.get('execution_id')
        error = event.get('error', {})
        
        if not job_id:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing job_id parameter'
                })
            }
        
        # Extract error message
        error_message = "Unknown error"
        if isinstance(error, dict):
            if 'Cause' in error:
                try:
                    cause = json.loads(error['Cause'])
                    error_message = cause.get('errorMessage', 'Unknown error')
                except (json.JSONDecodeError, TypeError):
                    error_message = error.get('Cause', 'Unknown error')
            elif 'Error' in error:
                error_message = error['Error']
        
        # Map stage to job status
        status_mapping = {
            'segmentation': JobStatus.SEGMENTING,
            'vlm_processing': JobStatus.CONVERTING,
            'llm_enhancement': JobStatus.ENHANCING,
            'results_storage': JobStatus.FAILED
        }
        
        # Update job status to failed
        update_job_status(job_id, JobStatus.FAILED, error_message)
        
        # Log error details to CloudWatch
        if execution_id:
            log_error_to_cloudwatch(execution_id, stage, error)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Error handled successfully',
                'job_id': job_id,
                'stage': stage,
                'status': JobStatus.FAILED.value
            })
        }
        
    except Exception as e:
        logger.error(f"Failed to handle error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Failed to handle error: {e}'
            })
        }


# For local testing
if __name__ == "__main__":
    # Sample test event
    test_event = {
        "job_id": "12345678-1234-5678-abcd-1234567890ab",
        "stage": "segmentation",
        "execution_id": "mri-analysis-12345678-1234-5678-abcd-1234567890ab",
        "error": {
            "Error": "Lambda.ServiceException",
            "Cause": "{\"errorMessage\": \"Failed to process MRI image\", \"errorType\": \"ProcessingError\"}"
        }
    }
    
    # Mock context
    class MockContext:
        def __init__(self):
            self.function_name = "test-function"
            self.memory_limit_in_mb = 128
            self.invoked_function_arn = "test-arn"
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))