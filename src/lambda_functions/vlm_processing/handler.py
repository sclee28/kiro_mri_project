"""
VLM Image-to-Text Processing Lambda Function.

This Lambda function invokes a HuggingFace VLM model on SageMaker to convert
segmented MRI images to descriptive text, updates the job status in the database,
and handles errors appropriately.
"""

import os
import json
import logging
import time
import uuid
import base64
from datetime import datetime
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

from src.shared.models.analysis_job import AnalysisJob, JobStatus
from src.shared.models.analysis_result import AnalysisResult
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
SAGEMAKER_VLM_ENDPOINT = os.environ.get("SAGEMAKER_VLM_ENDPOINT", "huggingface-vlm-endpoint")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "healthcare-processed-results")
MODEL_TIMEOUT_SECONDS = int(os.environ.get("MODEL_TIMEOUT_SECONDS", "300"))  # 5 minutes timeout
DEFAULT_PROMPT = os.environ.get("DEFAULT_VLM_PROMPT", "Describe the medical findings in this MRI image in detail.")


class VLMProcessingError(Exception):
    """Exception raised for errors in the VLM processing."""
    pass


@retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
def invoke_vlm_endpoint(image_data: bytes, prompt: str = DEFAULT_PROMPT) -> Dict[str, Any]:
    """
    Invoke the SageMaker endpoint for VLM image-to-text processing.
    
    Args:
        image_data: Binary data of the segmented MRI image
        prompt: Text prompt to guide the VLM model
        
    Returns:
        Dictionary containing the VLM processing results
        
    Raises:
        RetryableError: For transient errors that can be retried
        PermanentError: For permanent errors that should not be retried
    """
    try:
        # Prepare the payload with image and prompt
        payload = {
            "image": base64.b64encode(image_data).decode('utf-8'),
            "prompt": prompt
        }
        
        start_time = time.time()
        
        # Invoke the SageMaker endpoint
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_VLM_ENDPOINT,
            ContentType="application/json",
            Body=json.dumps(payload),
            Accept="application/json"
        )
        
        processing_time = time.time() - start_time
        logger.info(f"VLM endpoint invocation completed in {processing_time:.2f} seconds")
        
        # Parse the response body
        response_body = json.loads(response['Body'].read().decode('utf-8'))
        
        # Add processing metrics
        response_body['processing_metrics'] = {
            'invocation_time_seconds': processing_time,
            'model_name': SAGEMAKER_VLM_ENDPOINT
        }
        
        return response_body
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = e.response.get('Error', {}).get('Message', '')
        
        if error_code in ['ModelError', 'InternalServerError', 'ServiceUnavailable']:
            logger.warning(f"Transient SageMaker error: {error_code} - {error_message}")
            raise RetryableError(f"VLM endpoint error: {error_message}", ErrorType.TRANSIENT)
        elif error_code == 'ValidationError':
            logger.error(f"Validation error when invoking VLM endpoint: {error_message}")
            raise PermanentError(f"Invalid input for VLM model: {error_message}", ErrorType.VALIDATION)
        else:
            logger.error(f"VLM endpoint error: {error_code} - {error_message}")
            raise PermanentError(f"Failed to invoke VLM endpoint: {error_message}", ErrorType.PERMANENT)


def download_image_from_s3(bucket: str, key: str) -> bytes:
    """
    Download a segmented MRI image from S3.
    
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


def preprocess_image(image_data: bytes) -> bytes:
    """
    Preprocess the image for VLM processing.
    
    Args:
        image_data: Binary data of the segmented MRI image
        
    Returns:
        Preprocessed image data
        
    Note:
        This is a placeholder for any preprocessing that might be needed.
        For now, it just returns the original image data.
    """
    # In a real implementation, this would include resizing, normalization,
    # or other preprocessing steps specific to the VLM model requirements.
    # For now, we'll just return the original image data.
    return image_data


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


def update_analysis_result(job_id: str, image_description: str, confidence_score: float, 
                          processing_metrics: Dict[str, Any]) -> None:
    """
    Update or create an analysis result with VLM processing output.
    
    Args:
        job_id: Job ID for the analysis job
        image_description: Text description generated by the VLM
        confidence_score: Confidence score from the VLM model
        processing_metrics: Processing metrics from the VLM invocation
    
    Raises:
        Exception: If the database update fails
    """
    try:
        with db_session_scope() as session:
            # Check if a result already exists for this job
            result = session.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).first()
            
            if result:
                # Update existing result
                result.image_description = image_description
                
                # Update confidence scores
                if not result.confidence_scores:
                    result.confidence_scores = {}
                result.confidence_scores['vlm_confidence'] = confidence_score
                
                # Update processing metrics
                if not result.processing_metrics:
                    result.processing_metrics = {}
                result.processing_metrics['vlm_processing'] = processing_metrics
            else:
                # Create new result
                result = AnalysisResult(
                    job_id=job_id,
                    image_description=image_description,
                    confidence_scores={'vlm_confidence': confidence_score},
                    processing_metrics={'vlm_processing': processing_metrics}
                )
                session.add(result)
            
            logger.info(f"Updated analysis result for job {job_id}")
            
    except Exception as e:
        logger.error(f"Failed to update analysis result in database: {e}")
        raise


@handle_lambda_errors(ErrorContext(
    function_name="vlm_processing",
    operation="image_to_text_conversion"
))
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function handler for VLM image-to-text processing.
    
    Args:
        event: Lambda event containing job_id, bucket_name, and segmentation_result_key
        context: Lambda context
        
    Returns:
        Dictionary containing the VLM processing results
    """
    logger.info(f"Received VLM processing request: {json.dumps(event)}")
    
    # Extract parameters from the event
    job_id = event.get('job_id')
    bucket_name = event.get('bucket_name', OUTPUT_BUCKET)
    segmentation_result_key = event.get('segmentation_result_key')
    execution_id = event.get('execution_id', str(uuid.uuid4()))
    custom_prompt = event.get('prompt', DEFAULT_PROMPT)
    
    # Validate input parameters
    if not all([job_id, segmentation_result_key]):
        error_msg = "Missing required parameters: job_id or segmentation_result_key"
        logger.error(error_msg)
        return {
            'statusCode': 400,
            'error': error_msg
        }
    
    try:
        # Update job status to CONVERTING
        update_job_status(job_id, JobStatus.CONVERTING)
        
        # Download the segmented image from S3
        logger.info(f"Downloading segmented image from S3: {bucket_name}/{segmentation_result_key}")
        image_data = download_image_from_s3(bucket_name, segmentation_result_key)
        
        # Preprocess the image
        preprocessed_image = preprocess_image(image_data)
        
        # Invoke VLM endpoint for image-to-text conversion
        logger.info(f"Invoking VLM endpoint: {SAGEMAKER_VLM_ENDPOINT}")
        start_time = time.time()
        vlm_result = invoke_vlm_endpoint(preprocessed_image, custom_prompt)
        
        # Check if processing time exceeds the timeout
        processing_time = time.time() - start_time
        if processing_time > MODEL_TIMEOUT_SECONDS:
            logger.warning(f"VLM processing time ({processing_time:.2f}s) exceeded timeout ({MODEL_TIMEOUT_SECONDS}s)")
        
        # Extract text description from the model response
        image_description = vlm_result.get('text_description')
        if not image_description:
            raise VLMProcessingError("VLM model did not return valid text description")
        
        # Extract confidence score
        confidence_score = vlm_result.get('confidence_score', 0.0)
        
        # Update the analysis result in the database
        update_analysis_result(
            job_id=job_id,
            image_description=image_description,
            confidence_score=confidence_score,
            processing_metrics=vlm_result.get('processing_metrics', {})
        )
        
        # Prepare the response
        response = {
            'statusCode': 200,
            'job_id': job_id,
            'image_description': image_description,
            'confidence_score': confidence_score,
            'processing_time_seconds': processing_time,
            'execution_id': execution_id
        }
        
        logger.info(f"VLM processing completed successfully for job {job_id}")
        return response
        
    except VLMProcessingError as e:
        logger.error(f"VLM processing error for job {job_id}: {str(e)}")
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