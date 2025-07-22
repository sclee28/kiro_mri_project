"""
Results Storage and Notification Lambda Function.

This Lambda function stores final analysis results in RDS, updates job status,
sends completion notifications, and performs data validation and integrity checks.
"""

import os
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import boto3
from botocore.exceptions import ClientError

from src.shared.models.database import AnalysisJob, JobStatus, AnalysisResult
from src.shared.utils.database import db_session_scope
from src.shared.utils.error_handler import (
    ErrorContext, handle_lambda_errors, retry_with_backoff, RetryConfig,
    RetryableError, PermanentError, ErrorType, safe_rds_operation
)

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize AWS clients
sns_client = boto3.client('sns')
s3_client = boto3.client('s3')

# Environment variables
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "healthcare-processed-results")
NOTIFICATION_TOPIC_ARN = os.environ.get("NOTIFICATION_TOPIC_ARN", "")
ENABLE_NOTIFICATIONS = os.environ.get("ENABLE_NOTIFICATIONS", "true").lower() == "true"


class ResultsStorageError(Exception):
    """Exception raised for errors in the results storage process."""
    pass


class DataValidationError(Exception):
    """Exception raised for data validation errors."""
    pass


def validate_input_data(event: Dict[str, Any]) -> None:
    """
    Validate the input data from the Step Functions event.
    
    Args:
        event: Step Functions event data
        
    Raises:
        DataValidationError: If validation fails
    """
    required_fields = ["job_id", "segmentation_result", "vlm_result", "llm_result"]
    
    for field in required_fields:
        if field not in event:
            raise DataValidationError(f"Missing required field: {field}")
    
    # Validate job_id
    job_id = event.get("job_id")
    if not job_id or not isinstance(job_id, str):
        raise DataValidationError("Invalid job_id format")
    
    # Validate segmentation result
    segmentation_result = event.get("segmentation_result", {})
    if not isinstance(segmentation_result, dict) or "segmentation_result_key" not in segmentation_result:
        raise DataValidationError("Invalid segmentation_result format")
    
    # Validate VLM result
    vlm_result = event.get("vlm_result", {})
    if not isinstance(vlm_result, dict) or "image_description" not in vlm_result:
        raise DataValidationError("Invalid vlm_result format")
    
    # Validate LLM result
    llm_result = event.get("llm_result", {})
    if not isinstance(llm_result, dict) or "enhanced_report" not in llm_result:
        raise DataValidationError("Invalid llm_result format")


@retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
def update_job_status(job_id: str, status: JobStatus, error_message: Optional[str] = None) -> None:
    """
    Update the status of an analysis job in the database.
    
    Args:
        job_id: Job ID for the analysis job
        status: New status for the job
        error_message: Optional error message if the job failed
    
    Raises:
        RetryableError: For transient database errors
        PermanentError: For permanent database errors
    """
    try:
        with db_session_scope() as session:
            job = session.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
            
            if not job:
                logger.error(f"Job not found in database: {job_id}")
                raise PermanentError(f"Job not found: {job_id}", ErrorType.PERMANENT)
            
            job.status = status
            if error_message:
                job.error_message = error_message
            
            logger.info(f"Updated job {job_id} status to {status.value}")
            
    except Exception as e:
        logger.error(f"Failed to update job status in database: {e}")
        raise RetryableError(f"Database error: {e}", ErrorType.TRANSIENT)


@safe_rds_operation
def store_final_results(
    job_id: str,
    segmentation_result: Dict[str, Any],
    vlm_result: Dict[str, Any],
    llm_result: Dict[str, Any]
) -> str:
    """
    Store the final analysis results in the database.
    
    Args:
        job_id: Job ID for the analysis job
        segmentation_result: Results from the segmentation step
        vlm_result: Results from the VLM processing step
        llm_result: Results from the LLM enhancement step
        
    Returns:
        Result ID of the stored result
        
    Raises:
        RetryableError: For transient database errors
        PermanentError: For permanent database errors
    """
    try:
        with db_session_scope() as session:
            # Check if a result already exists for this job
            result = session.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).first()
            
            # Extract data from the processing steps
            segmentation_result_key = segmentation_result.get("segmentation_result_key")
            image_description = vlm_result.get("image_description")
            enhanced_report = llm_result.get("enhanced_report")
            
            # Combine confidence scores from all steps
            confidence_scores = {
                "segmentation": segmentation_result.get("confidence_scores", {}),
                "vlm": vlm_result.get("confidence_scores", {}),
                "llm": llm_result.get("confidence_scores", {})
            }
            
            # Combine processing metrics from all steps
            processing_metrics = {
                "segmentation": segmentation_result.get("processing_metrics", {}),
                "vlm": vlm_result.get("processing_metrics", {}),
                "llm": llm_result.get("processing_metrics", {}),
                "source_references": llm_result.get("source_references", []),
                "completed_at": datetime.utcnow().isoformat()
            }
            
            if result:
                # Update existing result
                result.segmentation_result_key = segmentation_result_key
                result.image_description = image_description
                result.enhanced_report = enhanced_report
                result.confidence_scores = confidence_scores
                result.processing_metrics = processing_metrics
                
                logger.info(f"Updated existing analysis result for job {job_id}")
                result_id = str(result.result_id)
            else:
                # Create new result
                new_result = AnalysisResult(
                    job_id=job_id,
                    segmentation_result_key=segmentation_result_key,
                    image_description=image_description,
                    enhanced_report=enhanced_report,
                    confidence_scores=confidence_scores,
                    processing_metrics=processing_metrics
                )
                session.add(new_result)
                
                # Need to flush to get the generated result_id
                session.flush()
                result_id = str(new_result.result_id)
                
                logger.info(f"Created new analysis result for job {job_id}")
            
            return result_id
            
    except Exception as e:
        logger.error(f"Failed to store final results in database: {e}")
        raise RetryableError(f"Database error: {e}", ErrorType.TRANSIENT)


@retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
def send_completion_notification(
    job_id: str,
    result_id: str,
    user_id: str,
    status: str = "completed"
) -> None:
    """
    Send a notification about job completion.
    
    Args:
        job_id: Job ID for the analysis job
        result_id: Result ID for the stored results
        user_id: User ID who submitted the job
        status: Job status (completed or failed)
        
    Raises:
        RetryableError: For transient SNS errors
    """
    if not ENABLE_NOTIFICATIONS or not NOTIFICATION_TOPIC_ARN:
        logger.info("Notifications are disabled or SNS topic ARN is not configured")
        return
    
    try:
        message = {
            "job_id": job_id,
            "result_id": result_id,
            "user_id": user_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        response = sns_client.publish(
            TopicArn=NOTIFICATION_TOPIC_ARN,
            Message=json.dumps(message),
            Subject=f"MRI Analysis {status.capitalize()}: Job {job_id}",
            MessageAttributes={
                "job_id": {"DataType": "String", "StringValue": job_id},
                "user_id": {"DataType": "String", "StringValue": user_id},
                "status": {"DataType": "String", "StringValue": status}
            }
        )
        
        logger.info(f"Sent completion notification for job {job_id}, MessageId: {response.get('MessageId')}")
        
    except ClientError as e:
        logger.error(f"Failed to send SNS notification: {e}")
        # Don't raise an exception here, as notification failure shouldn't fail the whole process
        # Just log the error and continue


def perform_data_integrity_checks(
    job_id: str,
    segmentation_result: Dict[str, Any],
    vlm_result: Dict[str, Any],
    llm_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Perform data integrity checks on the results.
    
    Args:
        job_id: Job ID for the analysis job
        segmentation_result: Results from the segmentation step
        vlm_result: Results from the VLM processing step
        llm_result: Results from the LLM enhancement step
        
    Returns:
        Dictionary with integrity check results
        
    Raises:
        DataValidationError: If critical integrity checks fail
    """
    integrity_results = {
        "passed": True,
        "warnings": [],
        "errors": []
    }
    
    # Check segmentation result key exists and is valid
    segmentation_key = segmentation_result.get("segmentation_result_key")
    if not segmentation_key:
        integrity_results["warnings"].append("Missing segmentation result key")
    elif not isinstance(segmentation_key, str):
        integrity_results["errors"].append("Invalid segmentation result key format")
        integrity_results["passed"] = False
    
    # Check image description exists and is not empty
    image_description = vlm_result.get("image_description")
    if not image_description:
        integrity_results["warnings"].append("Missing or empty image description")
    elif not isinstance(image_description, str):
        integrity_results["errors"].append("Invalid image description format")
        integrity_results["passed"] = False
    
    # Check enhanced report exists and is not empty
    enhanced_report = llm_result.get("enhanced_report")
    if not enhanced_report:
        integrity_results["warnings"].append("Missing or empty enhanced report")
    elif not isinstance(enhanced_report, str):
        integrity_results["errors"].append("Invalid enhanced report format")
        integrity_results["passed"] = False
    
    # Check confidence scores
    if not llm_result.get("confidence_scores"):
        integrity_results["warnings"].append("Missing confidence scores")
    
    # Check for critical errors
    if not integrity_results["passed"]:
        error_message = "; ".join(integrity_results["errors"])
        logger.error(f"Data integrity check failed for job {job_id}: {error_message}")
        raise DataValidationError(f"Data integrity check failed: {error_message}")
    
    # Log warnings
    if integrity_results["warnings"]:
        warning_message = "; ".join(integrity_results["warnings"])
        logger.warning(f"Data integrity warnings for job {job_id}: {warning_message}")
    
    return integrity_results


def get_user_id_for_job(job_id: str) -> str:
    """
    Get the user ID associated with a job.
    
    Args:
        job_id: Job ID for the analysis job
        
    Returns:
        User ID string
        
    Raises:
        RetryableError: For transient database errors
    """
    try:
        with db_session_scope() as session:
            job = session.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
            
            if not job:
                logger.error(f"Job not found in database: {job_id}")
                return "unknown"
            
            return job.user_id
            
    except Exception as e:
        logger.error(f"Failed to get user ID from database: {e}")
        return "unknown"


@handle_lambda_errors(ErrorContext(
    function_name="results_storage_notification",
    operation="store_and_notify"
))
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function handler for results storage and notification.
    
    Args:
        event: Lambda event containing job_id and results from all processing steps
        context: Lambda context
        
    Returns:
        Dictionary containing the storage and notification results
    """
    logger.info(f"Received results storage request: {json.dumps(event)}")
    
    # Extract parameters from the event
    job_id = event.get('job_id')
    execution_id = event.get('execution_id', str(uuid.uuid4()))
    
    # Extract results from previous steps
    segmentation_result = event.get('segmentation_result', {})
    vlm_result = event.get('vlm_result', {})
    llm_result = event.get('llm_result', {})
    
    try:
        # Validate input data
        validate_input_data(event)
        
        # Update job status to indicate we're storing results
        update_job_status(job_id, JobStatus.ENHANCING)  # Reuse ENHANCING status as we don't have a STORING status
        
        # Perform data integrity checks
        integrity_results = perform_data_integrity_checks(
            job_id, segmentation_result, vlm_result, llm_result
        )
        
        # Store final results in the database
        result_id = store_final_results(
            job_id, segmentation_result, vlm_result, llm_result
        )
        
        # Update job status to completed
        update_job_status(job_id, JobStatus.COMPLETED)
        
        # Get user ID for notification
        user_id = get_user_id_for_job(job_id)
        
        # Send completion notification
        send_completion_notification(job_id, result_id, user_id)
        
        # Prepare the response
        response = {
            'statusCode': 200,
            'job_id': job_id,
            'result_id': result_id,
            'integrity_check': integrity_results,
            'execution_id': execution_id
        }
        
        logger.info(f"Results storage and notification completed successfully for job {job_id}")
        return response
        
    except DataValidationError as e:
        logger.error(f"Data validation error for job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise
        
    except (RetryableError, PermanentError) as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error for job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise ResultsStorageError(f"Failed to store results: {str(e)}")