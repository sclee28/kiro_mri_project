"""
MRI Segmentation Lambda Function.

This Lambda function invokes a SageMaker endpoint to perform MRI image segmentation,
updates the job status in the database, and handles errors appropriately.
"""

import os
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

from src.shared.models.analysis_job import AnalysisJob, JobStatus
from src.shared.utils.database import db_session_scope
from src.shared.utils.error_handler import (
    ErrorContext, handle_lambda_errors, retry_with_backoff, RetryConfig,
    RetryableError, PermanentError, ErrorType
)

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize AWS clients
s3_client = boto3.client('s3')
sagemaker_runtime = boto3.client('sagemaker-runtime')

# Environment variables
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "mri-segmentation-endpoint")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "healthcare-processed-results")
MODEL_TIMEOUT_SECONDS = int(os.environ.get("MODEL_TIMEOUT_SECONDS", "300"))  # 5 minutes timeout


class SegmentationError(Exception):
    """Exception raised for errors in the segmentation process."""
    pass


@retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
def invoke_sagemaker_endpoint(payload: bytes, content_type: str = "application/octet-stream") -> Dict[str, Any]:
    """
    Invoke the SageMaker endpoint for MRI segmentation.
    
    Args:
        payload: Binary data of the MRI image
        content_type: Content type of the payload
        
    Returns:
        Dictionary containing the segmentation results
        
    Raises:
        RetryableError: For transient errors that can be retried
        PermanentError: For permanent errors that should not be retried
    """
    try:
        start_time = time.time()
        
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType=content_type,
            Body=payload,
            Accept="application/json"
        )
        
        processing_time = time.time() - start_time
        logger.info(f"SageMaker endpoint invocation completed in {processing_time:.2f} seconds")
        
        # Parse the response body
        response_body = json.loads(response['Body'].read().decode('utf-8'))
        
        # Add processing metrics
        response_body['processing_metrics'] = {
            'invocation_time_seconds': processing_time,
            'model_name': SAGEMAKER_ENDPOINT_NAME
        }
        
        return response_body
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = e.response.get('Error', {}).get('Message', '')
        
        if error_code in ['ModelError', 'InternalServerError', 'ServiceUnavailable']:
            logger.warning(f"Transient SageMaker error: {error_code} - {error_message}")
            raise RetryableError(f"SageMaker endpoint error: {error_message}", ErrorType.TRANSIENT)
        elif error_code == 'ValidationError':
            logger.error(f"Validation error when invoking SageMaker endpoint: {error_message}")
            raise PermanentError(f"Invalid input for segmentation model: {error_message}", ErrorType.VALIDATION)
        else:
            logger.error(f"SageMaker endpoint error: {error_code} - {error_message}")
            raise PermanentError(f"Failed to invoke SageMaker endpoint: {error_message}", ErrorType.PERMANENT)


def download_image_from_s3(bucket: str, key: str) -> bytes:
    """
    Download an MRI image from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Binary data of the image
        
    Raises:
        RetryableError: For transient errors that can be retried
        PermanentError: For permanent errors that should not be retried
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        
        if error_code in ['NoSuchKey', 'NoSuchBucket']:
            logger.error(f"S3 object not found: {bucket}/{key}")
            raise PermanentError(f"Image not found in S3: {bucket}/{key}", ErrorType.PERMANENT)
        elif error_code in ['SlowDown', 'InternalError', 'ServiceUnavailable']:
            logger.warning(f"Transient S3 error: {error_code}")
            raise RetryableError(f"Transient S3 error: {error_code}", ErrorType.TRANSIENT)
        else:
            logger.error(f"S3 error when downloading image: {error_code}")
            raise PermanentError(f"Failed to download image from S3: {error_code}", ErrorType.PERMANENT)


def upload_result_to_s3(result_data: bytes, job_id: str) -> str:
    """
    Upload segmentation result to S3.
    
    Args:
        result_data: Binary data of the segmentation result
        job_id: Job ID for the analysis job
        
    Returns:
        S3 key of the uploaded result
        
    Raises:
        RetryableError: For transient errors that can be retried
        PermanentError: For permanent errors that should not be retried
    """
    # Generate a unique key for the segmentation result
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_key = f"segmentation-results/{job_id}/{timestamp}-segmentation.nii.gz"
    
    try:
        s3_client.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=result_key,
            Body=result_data,
            ContentType="application/octet-stream",
            Metadata={
                'job_id': job_id,
                'processing_type': 'segmentation',
                'timestamp': timestamp
            }
        )
        
        logger.info(f"Segmentation result uploaded to S3: {OUTPUT_BUCKET}/{result_key}")
        return result_key
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        
        if error_code in ['SlowDown', 'InternalError', 'ServiceUnavailable']:
            logger.warning(f"Transient S3 error during upload: {error_code}")
            raise RetryableError(f"Transient S3 error during upload: {error_code}", ErrorType.TRANSIENT)
        else:
            logger.error(f"S3 error when uploading result: {error_code}")
            raise PermanentError(f"Failed to upload segmentation result to S3: {error_code}", ErrorType.PERMANENT)


def update_job_status(job_id: str, status: JobStatus, error_message: Optional[str] = None) -> None:
    """
    Update the status of an analysis job in the database.
    
    Args:
        job_id: Job ID for the analysis job
        status: New status for the job
        error_message: Optional error message if the job failed
    
    Raises:
        Exception: If the database update fails
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
        raise


@handle_lambda_errors(ErrorContext(
    function_name="segmentation_trigger",
    operation="mri_segmentation"
))
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function handler for MRI segmentation.
    
    Args:
        event: Lambda event containing job_id, bucket_name, and object_key
        context: Lambda context
        
    Returns:
        Dictionary containing the segmentation results and S3 key
    """
    logger.info(f"Received segmentation request: {json.dumps(event)}")
    
    # Extract parameters from the event
    job_id = event.get('job_id')
    bucket_name = event.get('bucket_name')
    object_key = event.get('object_key')
    execution_id = event.get('execution_id', str(uuid.uuid4()))
    
    # Validate input parameters
    if not all([job_id, bucket_name, object_key]):
        error_msg = "Missing required parameters: job_id, bucket_name, or object_key"
        logger.error(error_msg)
        return {
            'statusCode': 400,
            'error': error_msg
        }
    
    try:
        # Update job status to SEGMENTING
        update_job_status(job_id, JobStatus.SEGMENTING)
        
        # Download the MRI image from S3
        logger.info(f"Downloading MRI image from S3: {bucket_name}/{object_key}")
        image_data = download_image_from_s3(bucket_name, object_key)
        
        # Invoke SageMaker endpoint for segmentation
        logger.info(f"Invoking SageMaker endpoint: {SAGEMAKER_ENDPOINT_NAME}")
        start_time = time.time()
        segmentation_result = invoke_sagemaker_endpoint(image_data)
        
        # Check if processing time exceeds the timeout
        processing_time = time.time() - start_time
        if processing_time > MODEL_TIMEOUT_SECONDS:
            logger.warning(f"Segmentation processing time ({processing_time:.2f}s) exceeded timeout ({MODEL_TIMEOUT_SECONDS}s)")
        
        # Extract binary segmentation result from the model response
        segmentation_data = segmentation_result.get('segmentation_data')
        if not segmentation_data:
            raise SegmentationError("Segmentation model did not return valid segmentation data")
        
        # Convert base64 string to binary if necessary
        import base64
        if isinstance(segmentation_data, str):
            segmentation_binary = base64.b64decode(segmentation_data)
        else:
            segmentation_binary = segmentation_data
        
        # Upload segmentation result to S3
        result_key = upload_result_to_s3(segmentation_binary, job_id)
        
        # Prepare the response
        response = {
            'statusCode': 200,
            'job_id': job_id,
            'segmentation_result_key': result_key,
            'confidence_score': segmentation_result.get('confidence_score', 0.0),
            'processing_time_seconds': processing_time,
            'execution_id': execution_id
        }
        
        logger.info(f"Segmentation completed successfully for job {job_id}")
        return response
        
    except SegmentationError as e:
        logger.error(f"Segmentation error for job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise
        
    except (RetryableError, PermanentError) as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error for job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, f"Unexpected error: {str(e)}")
        raise