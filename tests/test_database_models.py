"""
Unit tests for database models.

This module contains tests for the SQLAlchemy models including
validation, relationships, and serialization.
"""

import pytest
import uuid
from datetime import datetime
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from shared.models.database import AnalysisJob, AnalysisResult, JobStatus, Base
from shared.utils.database import db_manager, db_session_scope


class TestJobStatus:
    """Test the JobStatus enum."""
    
    def test_job_status_values(self):
        """Test that all expected job status values exist."""
        expected_values = {
            "uploaded", "segmenting", "converting", 
            "enhancing", "completed", "failed"
        }
        actual_values = {status.value for status in JobStatus}
        assert actual_values == expected_values
    
    def test_job_status_default(self):
        """Test that UPLOADED is accessible as default."""
        assert JobStatus.UPLOADED.value == "uploaded"


class TestAnalysisJob:
    """Test the AnalysisJob model."""
    
    def test_analysis_job_creation(self):
        """Test creating an AnalysisJob instance."""
        job = AnalysisJob(
            user_id="test_user_123",
            original_image_key="s3://bucket/images/test.nii",
            status=JobStatus.UPLOADED
        )
        
        assert job.user_id == "test_user_123"
        assert job.original_image_key == "s3://bucket/images/test.nii"
        assert job.status == JobStatus.UPLOADED
        assert job.error_message is None
        assert job.job_id is not None  # Should be auto-generated
    
    def test_analysis_job_default_status(self):
        """Test that default status is UPLOADED."""
        job = AnalysisJob(
            user_id="test_user",
            original_image_key="s3://bucket/test.nii"
        )
        assert job.status == JobStatus.UPLOADED
    
    def test_analysis_job_repr(self):
        """Test the string representation of AnalysisJob."""
        job_id = uuid.uuid4()
        job = AnalysisJob(
            job_id=job_id,
            user_id="test_user",
            original_image_key="s3://bucket/test.nii",
            status=JobStatus.SEGMENTING
        )
        
        expected = f"<AnalysisJob(job_id={job_id}, status=segmenting, user_id=test_user)>"
        assert repr(job) == expected
    
    def test_analysis_job_to_dict(self):
        """Test converting AnalysisJob to dictionary."""
        job_id = uuid.uuid4()
        created_at = datetime.now()
        updated_at = datetime.now()
        
        job = AnalysisJob(
            job_id=job_id,
            user_id="test_user",
            original_image_key="s3://bucket/test.nii",
            status=JobStatus.COMPLETED,
            created_at=created_at,
            updated_at=updated_at,
            error_message="Test error"
        )
        
        result = job.to_dict()
        
        assert result["job_id"] == str(job_id)
        assert result["user_id"] == "test_user"
        assert result["original_image_key"] == "s3://bucket/test.nii"
        assert result["status"] == "completed"
        assert result["created_at"] == created_at.isoformat()
        assert result["updated_at"] == updated_at.isoformat()
        assert result["error_message"] == "Test error"
    
    def test_analysis_job_to_dict_none_timestamps(self):
        """Test to_dict with None timestamps."""
        job = AnalysisJob(
            user_id="test_user",
            original_image_key="s3://bucket/test.nii"
        )
        
        result = job.to_dict()
        
        assert result["created_at"] is None
        assert result["updated_at"] is None


class TestAnalysisResult:
    """Test the AnalysisResult model."""
    
    def test_analysis_result_creation(self):
        """Test creating an AnalysisResult instance."""
        job_id = uuid.uuid4()
        result = AnalysisResult(
            job_id=job_id,
            segmentation_result_key="s3://bucket/results/seg.nii",
            image_description="MRI shows normal brain structure",
            enhanced_report="Detailed medical analysis...",
            confidence_scores={"segmentation": 0.95, "description": 0.88},
            processing_metrics={"segmentation_time": 120, "total_time": 300}
        )
        
        assert result.job_id == job_id
        assert result.segmentation_result_key == "s3://bucket/results/seg.nii"
        assert result.image_description == "MRI shows normal brain structure"
        assert result.enhanced_report == "Detailed medical analysis..."
        assert result.confidence_scores == {"segmentation": 0.95, "description": 0.88}
        assert result.processing_metrics == {"segmentation_time": 120, "total_time": 300}
        assert result.result_id is not None  # Should be auto-generated
    
    def test_analysis_result_repr(self):
        """Test the string representation of AnalysisResult."""
        result_id = uuid.uuid4()
        job_id = uuid.uuid4()
        result = AnalysisResult(
            result_id=result_id,
            job_id=job_id
        )
        
        expected = f"<AnalysisResult(result_id={result_id}, job_id={job_id})>"
        assert repr(result) == expected
    
    def test_analysis_result_to_dict(self):
        """Test converting AnalysisResult to dictionary."""
        result_id = uuid.uuid4()
        job_id = uuid.uuid4()
        created_at = datetime.now()
        
        result = AnalysisResult(
            result_id=result_id,
            job_id=job_id,
            segmentation_result_key="s3://bucket/seg.nii",
            image_description="Test description",
            enhanced_report="Test report",
            confidence_scores={"test": 0.9},
            processing_metrics={"time": 100},
            created_at=created_at
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["result_id"] == str(result_id)
        assert result_dict["job_id"] == str(job_id)
        assert result_dict["segmentation_result_key"] == "s3://bucket/seg.nii"
        assert result_dict["image_description"] == "Test description"
        assert result_dict["enhanced_report"] == "Test report"
        assert result_dict["confidence_scores"] == {"test": 0.9}
        assert result_dict["processing_metrics"] == {"time": 100}
        assert result_dict["created_at"] == created_at.isoformat()
    
    def test_analysis_result_to_dict_none_timestamp(self):
        """Test to_dict with None timestamp."""
        result = AnalysisResult(job_id=uuid.uuid4())
        result_dict = result.to_dict()
        assert result_dict["created_at"] is None


class TestModelRelationships:
    """Test relationships between models."""
    
    def test_job_results_relationship(self):
        """Test the relationship between AnalysisJob and AnalysisResult."""
        job = AnalysisJob(
            user_id="test_user",
            original_image_key="s3://bucket/test.nii"
        )
        
        result1 = AnalysisResult(
            job=job,
            image_description="First result"
        )
        
        result2 = AnalysisResult(
            job=job,
            image_description="Second result"
        )
        
        # Test forward relationship
        assert len(job.results) == 2
        assert result1 in job.results
        assert result2 in job.results
        
        # Test backward relationship
        assert result1.job == job
        assert result2.job == job


# Integration tests that require database connection
@pytest.mark.integration
class TestDatabaseIntegration:
    """Integration tests for database operations."""
    
    @pytest.fixture(autouse=True)
    def setup_test_db(self):
        """Set up test database before each test."""
        # Use test database configuration
        with patch.dict('os.environ', {
            'DB_NAME': 'test_healthcare_analysis',
            'DB_HOST': 'localhost',
            'DB_USERNAME': 'test_user',
            'DB_PASSWORD': 'test_password'
        }):
            # Create tables for testing
            try:
                db_manager.create_tables()
                yield
            finally:
                # Clean up after tests
                try:
                    db_manager.drop_tables()
                except:
                    pass  # Ignore cleanup errors
    
    def test_create_and_retrieve_job(self):
        """Test creating and retrieving an analysis job from database."""
        with db_session_scope() as session:
            # Create a job
            job = AnalysisJob(
                user_id="test_user_123",
                original_image_key="s3://bucket/test.nii",
                status=JobStatus.UPLOADED
            )
            session.add(job)
            session.flush()  # Get the ID without committing
            
            job_id = job.job_id
            
            # Retrieve the job
            retrieved_job = session.query(AnalysisJob).filter_by(job_id=job_id).first()
            
            assert retrieved_job is not None
            assert retrieved_job.user_id == "test_user_123"
            assert retrieved_job.original_image_key == "s3://bucket/test.nii"
            assert retrieved_job.status == JobStatus.UPLOADED
    
    def test_create_job_with_result(self):
        """Test creating a job with associated results."""
        with db_session_scope() as session:
            # Create job
            job = AnalysisJob(
                user_id="test_user",
                original_image_key="s3://bucket/test.nii"
            )
            session.add(job)
            session.flush()
            
            # Create result
            result = AnalysisResult(
                job_id=job.job_id,
                image_description="Test description",
                confidence_scores={"test": 0.95}
            )
            session.add(result)
            session.flush()
            
            # Verify relationship
            assert len(job.results) == 1
            assert job.results[0].image_description == "Test description"
            assert result.job == job
    
    def test_job_status_update(self):
        """Test updating job status."""
        with db_session_scope() as session:
            # Create job
            job = AnalysisJob(
                user_id="test_user",
                original_image_key="s3://bucket/test.nii",
                status=JobStatus.UPLOADED
            )
            session.add(job)
            session.flush()
            
            # Update status
            job.status = JobStatus.SEGMENTING
            session.flush()
            
            # Verify update
            updated_job = session.query(AnalysisJob).filter_by(job_id=job.job_id).first()
            assert updated_job.status == JobStatus.SEGMENTING
    
    def test_cascade_delete(self):
        """Test that deleting a job cascades to delete results."""
        with db_session_scope() as session:
            # Create job with result
            job = AnalysisJob(
                user_id="test_user",
                original_image_key="s3://bucket/test.nii"
            )
            session.add(job)
            session.flush()
            
            result = AnalysisResult(
                job_id=job.job_id,
                image_description="Test description"
            )
            session.add(result)
            session.flush()
            
            result_id = result.result_id
            
            # Delete job
            session.delete(job)
            session.flush()
            
            # Verify result was also deleted
            remaining_result = session.query(AnalysisResult).filter_by(result_id=result_id).first()
            assert remaining_result is None