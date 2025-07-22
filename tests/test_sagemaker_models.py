"""
Unit tests for SageMaker model deployment and monitoring.
"""

import unittest
from unittest.mock import patch, MagicMock, ANY
import json
import os
import sys
import boto3
from botocore.exceptions import ClientError

# Add the scripts directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))

# Import the modules to test
from scripts.monitor_sagemaker_endpoints import SageMakerEndpointMonitor
from scripts.validate_models import ModelValidator


class TestSageMakerModels(unittest.TestCase):
    """Test cases for SageMaker model deployment and monitoring."""
    
    @patch('boto3.client')
    def test_endpoint_monitor_get_endpoints(self, mock_boto3_client):
        """Test getting SageMaker endpoints."""
        # Mock the SageMaker client
        mock_sagemaker = MagicMock()
        mock_boto3_client.return_value = mock_sagemaker
        
        # Mock the list_endpoints response
        mock_sagemaker.list_endpoints.return_value = {
            'Endpoints': [
                {
                    'EndpointName': 'mri-segmentation-endpoint',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789012:endpoint/mri-segmentation-endpoint',
                    'EndpointStatus': 'InService',
                    'CreationTime': '2023-01-01T00:00:00Z',
                    'LastModifiedTime': '2023-01-01T00:00:00Z'
                },
                {
                    'EndpointName': 'huggingface-vlm-endpoint',
                    'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789012:endpoint/huggingface-vlm-endpoint',
                    'EndpointStatus': 'InService',
                    'CreationTime': '2023-01-01T00:00:00Z',
                    'LastModifiedTime': '2023-01-01T00:00:00Z'
                }
            ]
        }
        
        # Create the monitor and get endpoints
        monitor = SageMakerEndpointMonitor(region='us-east-1')
        endpoints = monitor.get_endpoints()
        
        # Verify the endpoints
        self.assertEqual(len(endpoints), 2)
        self.assertEqual(endpoints[0]['EndpointName'], 'mri-segmentation-endpoint')
        self.assertEqual(endpoints[1]['EndpointName'], 'huggingface-vlm-endpoint')
        
        # Verify that list_endpoints was called
        mock_sagemaker.list_endpoints.assert_called_once()
    
    @patch('boto3.client')
    def test_endpoint_monitor_check_endpoint_status(self, mock_boto3_client):
        """Test checking SageMaker endpoint status."""
        # Mock the SageMaker client
        mock_sagemaker = MagicMock()
        mock_boto3_client.return_value = mock_sagemaker
        
        # Mock the describe_endpoint response
        mock_sagemaker.describe_endpoint.return_value = {
            'EndpointName': 'mri-segmentation-endpoint',
            'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789012:endpoint/mri-segmentation-endpoint',
            'EndpointStatus': 'InService',
            'CreationTime': '2023-01-01T00:00:00Z',
            'LastModifiedTime': '2023-01-01T00:00:00Z'
        }
        
        # Create the monitor and check endpoint status
        monitor = SageMakerEndpointMonitor(region='us-east-1')
        status = monitor.check_endpoint_status('mri-segmentation-endpoint')
        
        # Verify the status
        self.assertEqual(status['endpoint_name'], 'mri-segmentation-endpoint')
        self.assertEqual(status['status'], 'InService')
        self.assertTrue(status['healthy'])
        
        # Verify that describe_endpoint was called
        mock_sagemaker.describe_endpoint.assert_called_once_with(
            EndpointName='mri-segmentation-endpoint'
        )
    
    @patch('boto3.client')
    def test_endpoint_monitor_get_endpoint_metrics(self, mock_boto3_client):
        """Test getting SageMaker endpoint metrics."""
        # Mock the CloudWatch client
        mock_cloudwatch = MagicMock()
        mock_boto3_client.return_value = mock_cloudwatch
        
        # Mock the get_metric_statistics response
        mock_cloudwatch.get_metric_statistics.return_value = {
            'Datapoints': [
                {
                    'Timestamp': '2023-01-01T00:00:00Z',
                    'Average': 100.0,
                    'Maximum': 200.0,
                    'Sum': 1000.0
                }
            ]
        }
        
        # Create the monitor and get endpoint metrics
        monitor = SageMakerEndpointMonitor(region='us-east-1')
        metrics = monitor.get_endpoint_metrics('mri-segmentation-endpoint', hours=1)
        
        # Verify that get_metric_statistics was called for each metric
        self.assertEqual(mock_cloudwatch.get_metric_statistics.call_count, 11)
        
        # Verify that the metrics were parsed correctly
        for metric_name in metrics:
            if 'error' not in metrics[metric_name]:
                self.assertEqual(metrics[metric_name]['average'], 100.0)
                self.assertEqual(metrics[metric_name]['maximum'], 200.0)
                self.assertEqual(metrics[metric_name]['sum'], 1000.0)
    
    @patch('boto3.client')
    def test_model_validator_validate_segmentation_model(self, mock_boto3_client):
        """Test validating the segmentation model."""
        # Mock the S3 client
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            'Body': MagicMock()
        }
        mock_s3.get_object.return_value['Body'].read.return_value = b'test_image_data'
        
        # Mock the SageMaker runtime client
        mock_sagemaker_runtime = MagicMock()
        mock_sagemaker_runtime.invoke_endpoint.return_value = {
            'Body': MagicMock()
        }
        mock_sagemaker_runtime.invoke_endpoint.return_value['Body'].read.return_value = json.dumps({
            'segmentation_data': 'base64_encoded_data',
            'confidence_score': 0.95
        }).encode('utf-8')
        
        # Set up the mock boto3.client to return our mocks
        def mock_client(service_name, **kwargs):
            if service_name == 's3':
                return mock_s3
            elif service_name == 'sagemaker-runtime':
                return mock_sagemaker_runtime
            return MagicMock()
        
        mock_boto3_client.side_effect = mock_client
        
        # Create the validator and validate the segmentation model
        validator = ModelValidator(region='us-east-1')
        success, results = validator.validate_segmentation_model('test_image.nii.gz')
        
        # Verify the results
        self.assertTrue(success)
        self.assertTrue(results['success'])
        self.assertEqual(results['confidence_score'], 0.95)
        
        # Verify that the S3 client was called
        mock_s3.get_object.assert_called_once()
        
        # Verify that the SageMaker runtime client was called
        mock_sagemaker_runtime.invoke_endpoint.assert_called_once_with(
            EndpointName=ANY,
            ContentType='application/octet-stream',
            Body=b'test_image_data',
            Accept='application/json'
        )
    
    @patch('boto3.client')
    def test_model_validator_validate_vlm_model(self, mock_boto3_client):
        """Test validating the VLM model."""
        # Mock the S3 client
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            'Body': MagicMock()
        }
        mock_s3.get_object.return_value['Body'].read.return_value = b'test_image_data'
        
        # Mock the SageMaker runtime client
        mock_sagemaker_runtime = MagicMock()
        mock_sagemaker_runtime.invoke_endpoint.return_value = {
            'Body': MagicMock()
        }
        mock_sagemaker_runtime.invoke_endpoint.return_value['Body'].read.return_value = json.dumps({
            'text_description': 'This is a test description of the medical image.',
            'confidence_score': 0.85
        }).encode('utf-8')
        
        # Set up the mock boto3.client to return our mocks
        def mock_client(service_name, **kwargs):
            if service_name == 's3':
                return mock_s3
            elif service_name == 'sagemaker-runtime':
                return mock_sagemaker_runtime
            return MagicMock()
        
        mock_boto3_client.side_effect = mock_client
        
        # Create the validator and validate the VLM model
        validator = ModelValidator(region='us-east-1')
        success, results = validator.validate_vlm_model('test_image.nii.gz')
        
        # Verify the results
        self.assertTrue(success)
        self.assertTrue(results['success'])
        self.assertEqual(results['confidence_score'], 0.85)
        self.assertEqual(results['text_description'], 'This is a test description of the medical image.')
        
        # Verify that the S3 client was called
        mock_s3.get_object.assert_called_once()
        
        # Verify that the SageMaker runtime client was called
        mock_sagemaker_runtime.invoke_endpoint.assert_called_once()


if __name__ == '__main__':
    unittest.main()