"""
Tests for the Streamlit application.

This module contains tests for the Streamlit application components.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import json

# Add the parent directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import modules to test
from streamlit_app.auth import authenticate_user, hash_password
from streamlit_app.api_client import APIClient
from streamlit_app.file_utils import validate_file, get_presigned_url
from streamlit_app.config import load_config


class TestAuth(unittest.TestCase):
    """Tests for the authentication module."""
    
    def test_hash_password(self):
        """Test password hashing."""
        password = "password"
        hashed = hash_password(password)
        self.assertEqual(
            hashed,
            "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
        )
    
    def test_authenticate_user_valid(self):
        """Test authentication with valid credentials."""
        result = authenticate_user("demo", "password")
        self.assertTrue(result)
    
    def test_authenticate_user_invalid(self):
        """Test authentication with invalid credentials."""
        result = authenticate_user("demo", "wrong_password")
        self.assertFalse(result)
        
        result = authenticate_user("nonexistent_user", "password")
        self.assertFalse(result)


class TestAPIClient(unittest.TestCase):
    """Tests for the API client."""
    
    def setUp(self):
        """Set up test environment."""
        self.api_client = APIClient(base_url="simulated")
    
    def test_create_job(self):
        """Test job creation."""
        result = self.api_client.create_job(
            user_id="test_user",
            image_key="test_image.jpg"
        )
        
        self.assertIn("job_id", result)
        self.assertEqual(result["user_id"], "test_user")
        self.assertEqual(result["original_image_key"], "test_image.jpg")
        self.assertEqual(result["status"], "UPLOADED")
    
    def test_get_user_jobs(self):
        """Test getting user jobs."""
        # Create a job first
        self.api_client.create_job(
            user_id="test_user",
            image_key="test_image.jpg"
        )
        
        # Get jobs
        jobs = self.api_client.get_user_jobs(user_id="test_user")
        
        self.assertTrue(len(jobs) > 0)
        self.assertEqual(jobs[0]["user_id"], "test_user")


class TestFileUtils(unittest.TestCase):
    """Tests for the file utilities."""
    
    def test_validate_file_size(self):
        """Test file size validation."""
        # Mock file object
        mock_file = MagicMock()
        mock_file.getvalue.return_value = b"x" * (11 * 1024 * 1024)  # 11MB
        
        result, message = validate_file(mock_file, max_size_mb=10)
        self.assertFalse(result)
        self.assertIn("exceeds maximum allowed size", message)
    
    def test_validate_file_extension(self):
        """Test file extension validation."""
        # Mock file object
        mock_file = MagicMock()
        mock_file.getvalue.return_value = b"test"
        mock_file.name = "test.txt"
        
        result, message = validate_file(
            mock_file,
            allowed_extensions=[".jpg", ".png"]
        )
        self.assertFalse(result)
        self.assertIn("File type not allowed", message)
    
    @patch("boto3.client")
    def test_get_presigned_url(self, mock_boto_client):
        """Test generating presigned URL."""
        # Mock S3 client
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://example.com/presigned-url"
        mock_boto_client.return_value = mock_s3
        
        # Test function
        from streamlit_app.file_utils import get_presigned_url
        url = get_presigned_url("test-bucket", "test-key.jpg")
        
        self.assertEqual(url, "https://example.com/presigned-url")
        mock_s3.generate_presigned_url.assert_called_once()


class TestConfig(unittest.TestCase):
    """Tests for the configuration module."""
    
    def test_load_config(self):
        """Test loading configuration."""
        config = load_config()
        
        self.assertEqual(config.api_base_url, "simulated")
        self.assertEqual(config.aws_region, "us-east-1")
        self.assertEqual(config.s3_bucket_name, "healthcare-mri-images")


if __name__ == "__main__":
    unittest.main()