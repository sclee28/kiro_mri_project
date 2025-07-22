#!/usr/bin/env python3
"""
Example usage of database models and utilities.

This script demonstrates how to use the database models
and utilities in the healthcare image analysis system.
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from shared.models.database import AnalysisJob, AnalysisResult, JobStatus
from shared.utils.database import db_session_scope, create_all_tables
from shared.migrations.migration_manager import apply_all_migrations


def example_usage():
    """Demonstrate basic usage of the database models."""
    
    print("Healthcare Image Analysis - Database Usage Example")
    print("=" * 50)
    
    # Example 1: Creating an analysis job
    print("\n1. Creating an Analysis Job:")
    job = AnalysisJob(
        user_id="doctor_smith_123",
        original_image_key="s3://medical-images/patient-001/brain-mri.nii",
        status=JobStatus.UPLOADED
    )
    
    print(f"   Job ID: {job.job_id}")
    print(f"   User: {job.user_id}")
    print(f"   Image: {job.original_image_key}")
    print(f"   Status: {job.status.value}")
    
    # Example 2: Converting to dictionary
    print("\n2. Converting Job to Dictionary:")
    job_dict = job.to_dict()
    for key, value in job_dict.items():
        print(f"   {key}: {value}")
    
    # Example 3: Creating analysis results
    print("\n3. Creating Analysis Results:")
    result = AnalysisResult(
        job_id=job.job_id,
        segmentation_result_key="s3://processed-images/patient-001/segmented.nii",
        image_description="MRI scan shows normal brain structure with no abnormalities detected.",
        enhanced_report="""
        MEDICAL ANALYSIS REPORT
        
        Patient: Anonymous
        Study Date: 2025-01-21
        Modality: MRI Brain
        
        FINDINGS:
        - Normal brain parenchyma
        - No evidence of mass lesions
        - Ventricular system appears normal
        - No signs of hemorrhage or infarction
        
        IMPRESSION:
        Normal brain MRI study.
        """,
        confidence_scores={
            "segmentation_accuracy": 0.96,
            "description_confidence": 0.92,
            "llm_enhancement_score": 0.89
        },
        processing_metrics={
            "segmentation_time_seconds": 145,
            "vlm_processing_time_seconds": 23,
            "llm_enhancement_time_seconds": 8,
            "total_processing_time_seconds": 176
        }
    )
    
    print(f"   Result ID: {result.result_id}")
    print(f"   Job ID: {result.job_id}")
    print(f"   Segmentation Key: {result.segmentation_result_key}")
    print(f"   Description: {result.image_description[:50]}...")
    print(f"   Confidence Scores: {result.confidence_scores}")
    
    # Example 4: Status transitions
    print("\n4. Job Status Transitions:")
    status_flow = [
        JobStatus.UPLOADED,
        JobStatus.SEGMENTING,
        JobStatus.CONVERTING,
        JobStatus.ENHANCING,
        JobStatus.COMPLETED
    ]
    
    for i, status in enumerate(status_flow):
        print(f"   Step {i+1}: {status.value}")
        if i < len(status_flow) - 1:
            print("      ↓")
    
    # Example 5: Error handling
    print("\n5. Error Handling Example:")
    failed_job = AnalysisJob(
        user_id="doctor_jones_456",
        original_image_key="s3://medical-images/patient-002/corrupted.nii",
        status=JobStatus.FAILED,
        error_message="Image file corrupted or unsupported format"
    )
    
    print(f"   Failed Job ID: {failed_job.job_id}")
    print(f"   Status: {failed_job.status.value}")
    print(f"   Error: {failed_job.error_message}")
    
    # Example 6: Database operations (commented out - requires actual DB)
    print("\n6. Database Operations (Example - requires DB connection):")
    print("""
    # Set up database connection
    os.environ['DB_HOST'] = 'your-rds-endpoint.amazonaws.com'
    os.environ['DB_NAME'] = 'healthcare_analysis'
    os.environ['DB_USERNAME'] = 'your_username'
    os.environ['DB_PASSWORD'] = 'your_password'
    
    # Apply migrations
    apply_all_migrations()
    
    # Create tables
    create_all_tables()
    
    # Use database session
    with db_session_scope() as session:
        # Add job to database
        session.add(job)
        session.flush()  # Get the ID
        
        # Add result to database
        result.job_id = job.job_id
        session.add(result)
        
        # Query jobs by status
        active_jobs = session.query(AnalysisJob).filter(
            AnalysisJob.status.in_([
                JobStatus.UPLOADED,
                JobStatus.SEGMENTING,
                JobStatus.CONVERTING,
                JobStatus.ENHANCING
            ])
        ).all()
        
        # Update job status
        job.status = JobStatus.COMPLETED
        
        # The session will automatically commit when exiting the context
    """)
    
    print("\n✅ Example completed successfully!")


if __name__ == "__main__":
    example_usage()