"""
API client for interacting with the backend services.

This module provides a client for making API calls to the backend services
for job creation, status tracking, and result retrieval.
"""

import os
import json
import logging
import uuid
from typing import Dict, List, Any, Optional
import time

import requests
from requests.exceptions import RequestException
import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)


class APIClient:
    """
    Client for interacting with the backend API.
    
    In a production environment, this would make HTTP requests to the API endpoints.
    For this implementation, we're simulating the API calls with direct AWS service calls.
    """
    
    def __init__(self, base_url=None):
        """
        Initialize the API client.
        
        Args:
            base_url: The base URL for the API (optional for simulated mode)
        """
        self.base_url = base_url
        self.simulated_mode = base_url is None or base_url == "simulated"
        
        # Initialize AWS clients if in simulated mode
        if self.simulated_mode:
            self.s3_client = boto3.client('s3')
            self.dynamodb_client = boto3.client('dynamodb')
            self.sqs_client = boto3.client('sqs')
            
            # Mock database for simulated mode
            self.mock_db = {
                "jobs": {},
                "results": {}
            }
            
            # Load mock data
            self._load_mock_data()
    
    def _load_mock_data(self):
        """Load mock data for simulated mode."""
        # Create some sample jobs
        sample_job_id = str(uuid.uuid4())
        completed_job_id = str(uuid.uuid4())
        
        # Sample job (in progress)
        self.mock_db["jobs"][sample_job_id] = {
            "job_id": sample_job_id,
            "user_id": "demo",
            "original_image_key": "uploads/demo/sample_mri.jpg",
            "status": "SEGMENTING",
            "created_at": "2025-07-20T14:30:00Z",
            "updated_at": "2025-07-20T14:30:05Z",
            "error_message": None
        }
        
        # Completed job with results
        self.mock_db["jobs"][completed_job_id] = {
            "job_id": completed_job_id,
            "user_id": "demo",
            "original_image_key": "uploads/demo/completed_mri.jpg",
            "status": "COMPLETED",
            "created_at": "2025-07-19T10:15:00Z",
            "updated_at": "2025-07-19T10:25:30Z",
            "error_message": None
        }
        
        # Results for completed job
        self.mock_db["results"][completed_job_id] = {
            "result_id": str(uuid.uuid4()),
            "job_id": completed_job_id,
            "segmentation_result_key": "results/demo/segmentation_result.jpg",
            "image_description": "The MRI scan shows a cross-sectional view of the brain with visible contrast between gray and white matter. There appears to be normal ventricular size and no evidence of mass effect or midline shift. The cortical sulci and gyri demonstrate normal appearance without signs of atrophy.",
            "enhanced_report": """
# Medical Analysis Report

## Key Findings
- Normal brain parenchyma with appropriate gray-white matter differentiation
- Ventricles are of normal size and configuration
- No evidence of intracranial hemorrhage, mass effect, or midline shift
- No signs of acute infarction or ischemic changes
- Normal appearance of the basal ganglia and thalami

## Clinical Significance
The MRI demonstrates normal brain anatomy without evidence of pathological findings. The ventricular system is symmetric and of normal size, suggesting normal cerebrospinal fluid dynamics. There are no signs of increased intracranial pressure.

## Recommended Follow-up
- No immediate follow-up imaging is indicated based on these findings
- Correlate with clinical symptoms if present
- Standard follow-up with referring physician is advised

## Confidence Assessment
This analysis has high confidence (92%) in the assessment of normal brain anatomy. The image quality is excellent with good contrast resolution, allowing for detailed evaluation of brain structures.
            """,
            "confidence_scores": {
                "segmentation_model": 0.94,
                "vlm_model": 0.89,
                "llm_enhancement": 0.92
            },
            "processing_metrics": {
                "segmentation_time_ms": 2450,
                "vlm_processing_time_ms": 1830,
                "llm_enhancement_time_ms": 3200,
                "total_processing_time_ms": 7480
            },
            "created_at": "2025-07-19T10:25:30Z"
        }
    
    def _simulate_api_delay(self):
        """Simulate API latency."""
        time.sleep(0.5)
    
    def create_job(self, user_id: str, image_key: str) -> Dict[str, Any]:
        """
        Create a new analysis job.
        
        Args:
            user_id: The ID of the user creating the job
            image_key: The S3 key of the uploaded image
            
        Returns:
            Dict: The created job information
        """
        if self.simulated_mode:
            self._simulate_api_delay()
            
            # Create a new job in mock database
            job_id = str(uuid.uuid4())
            created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            job = {
                "job_id": job_id,
                "user_id": user_id,
                "original_image_key": image_key,
                "status": "UPLOADED",
                "created_at": created_at,
                "updated_at": created_at,
                "error_message": None
            }
            
            self.mock_db["jobs"][job_id] = job
            return job
        else:
            try:
                response = requests.post(
                    f"{self.base_url}/api/jobs",
                    json={
                        "user_id": user_id,
                        "image_key": image_key
                    }
                )
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                logger.error(f"API error creating job: {e}")
                raise
    
    def get_user_jobs(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all jobs for a user.
        
        Args:
            user_id: The ID of the user
            
        Returns:
            List[Dict]: List of job dictionaries
        """
        if self.simulated_mode:
            self._simulate_api_delay()
            
            # Filter jobs by user_id
            user_jobs = [
                job for job in self.mock_db["jobs"].values()
                if job["user_id"] == user_id
            ]
            
            # Simulate job progression
            for job in user_jobs:
                if job["status"] == "UPLOADED":
                    job["status"] = "SEGMENTING"
                elif job["status"] == "SEGMENTING":
                    job["status"] = "CONVERTING"
                elif job["status"] == "CONVERTING":
                    job["status"] = "ENHANCING"
                elif job["status"] == "ENHANCING":
                    # 50% chance to complete the job
                    if uuid.uuid4().int % 2 == 0:
                        job["status"] = "COMPLETED"
                
                job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            return user_jobs
        else:
            try:
                response = requests.get(
                    f"{self.base_url}/api/jobs",
                    params={"user_id": user_id}
                )
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                logger.error(f"API error getting user jobs: {e}")
                raise
    
    def get_job_details(self, job_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a job.
        
        Args:
            job_id: The ID of the job
            
        Returns:
            Dict: Job details including results if available
        """
        if self.simulated_mode:
            self._simulate_api_delay()
            
            # Get job from mock database
            job = self.mock_db["jobs"].get(job_id)
            if not job:
                raise ValueError(f"Job not found: {job_id}")
            
            # Get results if job is completed
            if job["status"] == "COMPLETED":
                results = self.mock_db["results"].get(job_id)
                if results:
                    job["results"] = results
            
            return job
        else:
            try:
                response = requests.get(f"{self.base_url}/api/jobs/{job_id}")
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                logger.error(f"API error getting job details: {e}")
                raise