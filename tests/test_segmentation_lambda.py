"""
Unit tests for the MRI segmentation Lambda function.
"""

import json
import unittest
from unittest.mock import patch, MagicMock, ANY

import boto3
from botocore.exceptions import ClientError

from src.lambda_functions.segmentation_trigger.handler import (
    handler, invoke_sagemaker_endpoint, download_image_from_s3,
    upload_result_to_s3, update_job_status, SegmentationError
)
from src.shared.models.analysis_job import JobStatus


class TestSegmentationLambda(unittest.TestCase):
    """Test cases for the MRI segmentation Lambda function."""
    
    @patch('src.lambda_functions.segmentation_trigger.handler.update_job_status')
    @patch('src.lambda_functions.segmentation_trigger.handler.download_image_from_s3')
    @patch('src.lambda_functions.segmentation_trigger.handler.invoke_sagemaker_endpoint')
    @patch('src.lambda_functions.segmentation_trigger.handler.upload_result_to_s3')
    def test_handler_success(self, mock_upload, mock_invoke, mock_download, mock_update_status):
        """Test successful execution of the Lambda handler."""
        # Mock the download function to return sample image data
        mock_download.return_value = b'sample_image_data'
        
        # Mock the SageMaker endpoint invocation
        mock_invoke.return_value = {
            'segmentation_data': b'segmented_image_data',
            'confidence_score': 0.95
        }
        
        # Mock the S3 upload function
        mock_upload.return_value = 'segmentation-results/test-job-id/20240721-120000-segmentation.nii.gz'
        
        # Create a test event
        event = {
            'job_id': 'test-job-id',
            'bucket_name': 'test-bucket',
            'object_key': 'test-image.nii.gz',
            'execution_id': 'test-execution-id'
        }
        
        # Call the handler
        response = handler(event, {})
        
        # Verify the response
        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['job_id'], 'test-job-id')
        self.assertEqual(response['execution_id'], 'test-execution-id')
        self.assertIn('segmentation_result_key', response)
        self.assertIn('confidence_score', response)
        self.assertIn('processing_time_seconds', response)
        
        # Verify that the functions were called with the correct arguments
        mock_update_status.assert_any_call('test-job-id', JobStatus.SEGMENTING)
        mock_download.assert_called_once_with('test-bucket', 'test-image.nii.gz')
        mock_invoke.assert_called_once_with(b'sample_image_data')
        mock_upload.assert_called_once_with(b'segmented_image_data', 'test-job-id')
    
    @patch('src.lambda_functions.segmentation_trigger.handler.update_job_status')
    @patch('src.lambda_functions.segmentation_trigger.handler.download_image_from_s3')
    def test_handler_missing_parameters(self, mock_download, mock_update_status):
        """Test handler with missing parameters."""
        # Create a test event with missing parameters
        event = {
            'job_id': 'test-job-id',
            # Missing bucket_name and object_key
        }
        
        # Call the handler
        response = handler(event, {})
        
        # Verify the response
        self.assertEqual(response['statusCode'], 400)
        self.assertIn('error', response)
        
        # Verify that the download function was not called
        mock_download.assert_not_called()
        mock_update_status.assert_not_called()
    
    @patch('src.lambda_functions.segmentation_trigger.handler.update_job_status')
    @patch('src.lambda_functions.segmentation_trigger.handler.download_image_from_s3')
    @patch('src.lambda_functions.segmentation_trigger.handler.invoke_sagemaker_endpoint')
    def test_handler_segmentation_error(self, mock_invoke, mock_download, mock_update_status):
        """Test handler when segmentation fails."""
        # Mock the download function to return sample image data
        mock_download.return_value = b'sample_image_data'
        
        # Mock the SageMaker endpoint invocation to return invalid data
        mock_invoke.return_value = {
            # Missing segmentation_data
            'confidence_score': 0.95
        }
        
        # Create a test event
        event = {
            'job_id': 'test-job-id',
            'bucket_name': 'test-bucket',
            'object_key': 'test-image.nii.gz',
            'execution_id': 'test-execution-id'
        }
        
        # Call the handler and expect an exception
        with self.assertRaises(SegmentationError):
            handler(event, {})
        
        # Verify that the status was updated to FAILED
        mock_update_status.assert_any_call('test-job-id', JobStatus.SEGMENTING)
        mock_update_status.assert_any_call('test-job-id', JobStatus.FAILED, ANY)
    
    @patch('src.lambda_functions.segmentation_trigger.handler.sagemaker_runtime')
    def test_invoke_sagemaker_endpoint_success(self, mock_sagemaker_runtime):
        """Test successful invocation of SageMaker endpoint."""
        # Mock the SageMaker runtime response
        mock_response = {
            'Body': MagicMock()
        }
        mock_response['Body'].read.return_value = json.dumps({
            'segmentation_data': 'base64_encoded_data',
            'confidence_score': 0.95
        }).encode('utf-8')
        mock_sagemaker_runtime.invoke_endpoint.return_value = mock_response
        
        # Call the function
        result = invoke_sagemaker_endpoint(b'test_image_data')
        
        # Verify the result
        self.assertIn('segmentation_data', result)
        self.assertIn('confidence_score', result)
        self.assertIn('processing_metrics', result)
        
        # Verify that the SageMaker runtime was called with the correct arguments
        mock_sagemaker_runtime.invoke_endpoint.assert_called_once_with(
            EndpointName=ANY,
            ContentType='application/octet-stream',
            Body=b'test_image_data',
            Accept='application/json'
        )
    
    @patch('src.lambda_functions.segmentation_trigger.handler.sagemaker_runtime')
    def test_invoke_sagemaker_endpoint_error(self, mock_sagemaker_runtime):
        """Test error handling when invoking SageMaker endpoint."""
        # Mock a ClientError from the SageMaker runtime
        error_response = {
            'Error': {
                'Code': 'ModelError',
                'Message': 'Model error occurred'
            }
        }
        mock_sagemaker_runtime.invoke_endpoint.side_effect = ClientError(
            error_response, 'InvokeEndpoint'
        )
        
        # Call the function and expect a RetryableError
        from src.shared.utils.error_handler import RetryableError
        with self.assertRaises(RetryableError):
            invoke_sagemaker_endpoint(b'test_image_data')
    
    @patch('src.lambda_functions.segmentation_trigger.handler.s3_client')
    def test_download_image_from_s3_success(self, mock_s3_client):
        """Test successful download from S3."""
        # Mock the S3 client response
        mock_response = {
            'Body': MagicMock()
        }
        mock_response['Body'].read.return_value = b'test_image_data'
        mock_s3_client.get_object.return_value = mock_response
        
        # Call the function
        result = download_image_from_s3('test-bucket', 'test-key')
        
        # Verify the result
        self.assertEqual(result, b'test_image_data')
        
        # Verify that the S3 client was called with the correct arguments
        mock_s3_client.get_object.assert_called_once_with(
            Bucket='test-bucket',
            Key='test-key'
        )
    
    @patch('src.lambda_functions.segmentation_trigger.handler.s3_client')
    def test_download_image_from_s3_not_found(self, mock_s3_client):
        """Test error handling when the S3 object is not found."""
        # Mock a NoSuchKey error from the S3 client
        error_response = {
            'Error': {
                'Code': 'NoSuchKey',
                'Message': 'The specified key does not exist.'
            }
        }
        mock_s3_client.get_object.side_effect = ClientError(
            error_response, 'GetObject'
        )
        
        # Call the function and expect a PermanentError
        from src.shared.utils.error_handler import PermanentError
        with self.assertRaises(PermanentError):
            download_image_from_s3('test-bucket', 'test-key')
    
    @patch('src.lambda_functions.segmentation_trigger.handler.s3_client')
    def test_upload_result_to_s3_success(self, mock_s3_client):
        """Test successful upload to S3."""
        # Call the function
        result_key = upload_result_to_s3(b'test_result_data', 'test-job-id')
        
        # Verify that the result key is returned
        self.assertTrue(result_key.startswith('segmentation-results/test-job-id/'))
        self.assertTrue(result_key.endswith('-segmentation.nii.gz'))
        
        # Verify that the S3 client was called with the correct arguments
        mock_s3_client.put_object.assert_called_once_with(
            Bucket=ANY,
            Key=result_key,
            Body=b'test_result_data',
            ContentType='application/octet-stream',
            Metadata={
                'job_id': 'test-job-id',
                'processing_type': 'segmentation',
                'timestamp': ANY
            }
        )
    
    @patch('src.lambda_functions.segmentation_trigger.handler.db_session_scope')
    def test_update_job_status_success(self, mock_db_session_scope):
        """Test successful job status update."""
        # Mock the database session and query
        mock_session = MagicMock()
        mock_job = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_job
        mock_db_session_scope.return_value.__enter__.return_value = mock_session
        
        # Call the function
        update_job_status('test-job-id', JobStatus.SEGMENTING)
        
        # Verify that the job status was updated
        self.assertEqual(mock_job.status, JobStatus.SEGMENTING)
        self.assertIsNone(mock_job.error_message)
    
    @patch('src.lambda_functions.segmentation_trigger.handler.db_session_scope')
    def test_update_job_status_with_error(self, mock_db_session_scope):
        """Test job status update with error message."""
        # Mock the database session and query
        mock_session = MagicMock()
        mock_job = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_job
        mock_db_session_scope.return_value.__enter__.return_value = mock_session
        
        # Call the function
        update_job_status('test-job-id', JobStatus.FAILED, 'Test error message')
        
        # Verify that the job status and error message were updated
        self.assertEqual(mock_job.status, JobStatus.FAILED)
        self.assertEqual(mock_job.error_message, 'Test error message')
    
    @patch('src.lambda_functions.segmentation_trigger.handler.db_session_scope')
    def test_update_job_status_job_not_found(self, mock_db_session_scope):
        """Test error handling when the job is not found."""
        # Mock the database session and query to return None
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_db_session_scope.return_value.__enter__.return_value = mock_session
        
        # Call the function and expect a PermanentError
        from src.shared.utils.error_handler import PermanentError
        with self.assertRaises(PermanentError):
            update_job_status('test-job-id', JobStatus.SEGMENTING)


if __name__ == '__main__':
    unittest.main()