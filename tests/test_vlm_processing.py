"""
Unit tests for the VLM image-to-text processing Lambda function.
"""

import json
import unittest
from unittest.mock import patch, MagicMock, ANY

import boto3
from botocore.exceptions import ClientError

from src.lambda_functions.vlm_processing.handler import (
    handler, invoke_vlm_endpoint, download_image_from_s3,
    update_job_status, update_analysis_result, VLMProcessingError,
    preprocess_image
)
from src.shared.models.database import JobStatus

