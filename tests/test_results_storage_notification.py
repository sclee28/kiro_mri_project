"""
Unit tests for the results storage and notification Lambda function.
"""

import json
import os
import unittest
from unittest.mock import patch, MagicMock, ANY

import boto3
import pytest
from moto import mock_sns, mock_s3

from src.lambda_functions.results_storage_notification.handler import (
    handler, validate_input_data, update_job_status, store_final_results,
    send_completion_notification, perform_data_integrity_checks,
    DataValidationError, ResultsStorageError
)
from src.shared.models.database import JobStatus


@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    with patch('src.lambda_functions.results_storage_notification.handler.db_session_scope') as mock_session:
        mock_context = MagicMock()
        mock_session_instance = MagicMock()
        mock_context.__enter__.return_value = mock_session_instance
        mock_session.return_value = mock_context
        yield mock_session_instance


@pytest.fixture
def valid_event():
    """Create a valid event for testing."""
    return {
        "job_id": "123e4567-e89b-12d3-a456-426614174000",
        "execution_id": "execution-123",
        "segmentation_result": {
            "segmentation_result_key": "segmentation/123e4567-e89b-12d3-a456-426614174000/result.nii.gz",
            "confidence_scores": {"overall": 0.92},
            "processing_metrics": {"duration_seconds": 45.2}
        },
        "vlm_result": {
            "image_description": "The MRI shows a small lesion in the left temporal lobe...",
            "confidence_scores": {"overall": 0.85},
            "processing_metrics": {"duration_seconds": 12.5}
        },
        "llm_result": {
            "enhanced_report": "Medical Report: The MRI analysis reveals a small lesion...",
            "confidence_scores": {"overall": 0.88, "findings": 0.9, "diagnosis": 0.85},
            "source_references": [{"title": "Medical Journal", "relevance_score": 0.95}],
            "processing_metrics": {"duration_seconds": 8.3}
        }
    }


@pytest.fixture
def invalid_event():
    """Create an invalid event for testing."""
    return {
        "job_id": "123e4567-e89b-12d3-a456-426614174000",
        # Missing required fields
    }


class TestDataValidation:
    """Test data validation functions."""
    
    def test_validate_input_data_valid(self, valid_event):
        """Test validation with valid data."""
        # Should not raise an exception
        validate_input_data(valid_event)
    
    def test_validate_input_data_invalid(self, invalid_event):
        """Test validation with invalid data."""
        with pytest.raises(DataValidationError):
            validate_input_data(invalid_event)
    
    def test_perform_data_integrity_checks_valid(self, valid_event):
        """Test data integrity checks with valid data."""
        result = perform_data_integrity_checks(
            valid_event["job_id"],
            valid_event["segmentation_result"],
            valid_event["vlm_result"],
            valid_event["llm_result"]
        )
        assert result["passed"] is True
        assert len(result["errors"]) == 0
    
    def test_perform_data_integrity_checks_invalid(self):
        """Test data integrity checks with invalid data."""
        invalid_data = {
            "segmentation_result": {"segmentation_result_key": 123},  # Invalid type
            "vlm_result": {"image_description": ""},  # Empty
            "llm_result": {"enhanced_report": None}  # None
        }
        
        with pytest.raises(DataValidationError):
            perform_data_integrity_checks(
                "test-job-id",
                invalid_data["segmentation_result"],
                invalid_data["vlm_result"],
                invalid_data["llm_result"]
            )


class TestDatabaseOperations:
    """Test database operations."""
    
    def test_update_job_status(self, mock_db_session):
        """Test updating job status."""
        mock_job = MagicMock()
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_job
        
        update_job_status("test-job-id", JobStatus.COMPLETED)
        
        assert mock_job.status == JobStatus.COMPLETED
        assert mock_job.error_message is None
    
    def test_update_job_status_with_error(self, mock_db_session):
        """Test updating job status with error message."""
        mock_job = MagicMock()
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_job
        
        update_job_status("test-job-id", JobStatus.FAILED, "Test error message")
        
        assert mock_job.status == JobStatus.FAILED
        assert mock_job.error_message == "Test error message"
    
    def test_update_job_status_not_found(self, mock_db_session):
        """Test updating job status when job not found."""
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(Exception):
            update_job_status("test-job-id", JobStatus.COMPLETED)
    
    def test_store_final_results_new(self, mock_db_session):
        """Test storing final results for a new record."""
        # Mock query to return None (no existing result)
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        # Mock the new result
        mock_new_result = MagicMock()
        mock_new_result.result_id = "new-result-id"
        
        # Mock the add method
        mock_db_session.add = MagicMock()
        
        # Mock the flush method
        mock_db_session.flush = MagicMock()
        
        with patch('src.lambda_functions.results_storage_notification.handler.AnalysisResult') as mock_result_class:
            mock_result_class.return_value = mock_new_result
            
            result_id = store_final_results(
                "test-job-id",
                {"segmentation_result_key": "test-key"},
                {"image_description": "test description"},
                {"enhanced_report": "test report"}
            )
            
            assert result_id == "new-result-id"
            mock_db_session.add.assert_called_once_with(mock_new_result)
            mock_db_session.flush.assert_called_once()
    
    def test_store_final_results_existing(self, mock_db_session):
        """Test storing final results for an existing record."""
        # Mock existing result
        mock_existing_result = MagicMock()
        mock_existing_result.result_id = "existing-result-id"
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_existing_result
        
        result_id = store_final_results(
            "test-job-id",
            {"segmentation_result_key": "test-key"},
            {"image_description": "test description"},
            {"enhanced_report": "test report"}
        )
        
        assert result_id == "existing-result-id"
        assert mock_existing_result.segmentation_result_key == "test-key"
        assert mock_existing_result.image_description == "test description"
        assert mock_existing_result.enhanced_report == "test report"


@mock_sns
class TestNotifications:
    """Test notification functions."""
    
    def setup_method(self):
        """Set up SNS topic for testing."""
        self.sns_client = boto3.client('sns', region_name='us-east-1')
        self.topic_arn = self.sns_client.create_topic(Name='test-topic')['TopicArn']
        os.environ['NOTIFICATION_TOPIC_ARN'] = self.topic_arn
        os.environ['ENABLE_NOTIFICATIONS'] = 'true'
    
    def teardown_method(self):
        """Clean up after tests."""
        os.environ.pop('NOTIFICATION_TOPIC_ARN', None)
        os.environ.pop('ENABLE_NOTIFICATIONS', None)
    
    def test_send_completion_notification(self):
        """Test sending completion notification."""
        with patch('src.lambda_functions.results_storage_notification.handler.sns_client', self.sns_client):
            send_completion_notification(
                "test-job-id",
                "test-result-id",
                "test-user-id"
            )
            
            # No exception means success
            # With moto, we can't easily check if the message was actually sent
    
    def test_send_completion_notification_disabled(self):
        """Test sending notification when disabled."""
        os.environ['ENABLE_NOTIFICATIONS'] = 'false'
        
        with patch('src.lambda_functions.results_storage_notification.handler.sns_client') as mock_sns:
            send_completion_notification(
                "test-job-id",
                "test-result-id",
                "test-user-id"
            )
            
            mock_sns.publish.assert_not_called()


class TestLambdaHandler:
    """Test the Lambda handler function."""
    
    @patch('src.lambda_functions.results_storage_notification.handler.validate_input_data')
    @patch('src.lambda_functions.results_storage_notification.handler.perform_data_integrity_checks')
    @patch('src.lambda_functions.results_storage_notification.handler.store_final_results')
    @patch('src.lambda_functions.results_storage_notification.handler.update_job_status')
    @patch('src.lambda_functions.results_storage_notification.handler.get_user_id_for_job')
    @patch('src.lambda_functions.results_storage_notification.handler.send_completion_notification')
    def test_handler_success(
        self, mock_send_notification, mock_get_user, mock_update_status,
        mock_store_results, mock_integrity_checks, mock_validate, valid_event
    ):
        """Test successful handler execution."""
        # Set up mocks
        mock_integrity_checks.return_value = {"passed": True, "warnings": [], "errors": []}
        mock_store_results.return_value = "test-result-id"
        mock_get_user.return_value = "test-user-id"
        
        # Call handler
        result = handler(valid_event, {})
        
        # Verify calls
        mock_validate.assert_called_once_with(valid_event)
        mock_integrity_checks.assert_called_once()
        mock_store_results.assert_called_once()
        
        # Verify status updates
        assert mock_update_status.call_count == 2
        mock_update_status.assert_any_call(valid_event["job_id"], JobStatus.ENHANCING)
        mock_update_status.assert_any_call(valid_event["job_id"], JobStatus.COMPLETED)
        
        # Verify notification
        mock_get_user.assert_called_once_with(valid_event["job_id"])
        mock_send_notification.assert_called_once_with(
            valid_event["job_id"], "test-result-id", "test-user-id"
        )
        
        # Verify response
        assert result["statusCode"] == 200
        assert result["job_id"] == valid_event["job_id"]
        assert result["result_id"] == "test-result-id"
    
    @patch('src.lambda_functions.results_storage_notification.handler.validate_input_data')
    @patch('src.lambda_functions.results_storage_notification.handler.update_job_status')
    def test_handler_validation_error(self, mock_update_status, mock_validate, valid_event):
        """Test handler with validation error."""
        # Set up mock to raise exception
        mock_validate.side_effect = DataValidationError("Test validation error")
        
        # Call handler and expect exception
        with pytest.raises(DataValidationError):
            handler(valid_event, {})
        
        # Verify status update to FAILED
        mock_update_status.assert_called_once_with(
            valid_event["job_id"], JobStatus.FAILED, "Test validation error"
        )
    
    @patch('src.lambda_functions.results_storage_notification.handler.validate_input_data')
    @patch('src.lambda_functions.results_storage_notification.handler.perform_data_integrity_checks')
    @patch('src.lambda_functions.results_storage_notification.handler.update_job_status')
    def test_handler_integrity_error(
        self, mock_update_status, mock_integrity_checks, mock_validate, valid_event
    ):
        """Test handler with integrity check error."""
        # Set up mock to raise exception
        mock_integrity_checks.side_effect = DataValidationError("Test integrity error")
        
        # Call handler and expect exception
        with pytest.raises(DataValidationError):
            handler(valid_event, {})
        
        # Verify status update to FAILED
        mock_update_status.assert_any_call(valid_event["job_id"], JobStatus.ENHANCING)
        mock_update_status.assert_any_call(
            valid_event["job_id"], JobStatus.FAILED, "Test integrity error"
        )


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])