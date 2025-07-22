"""
Analysis job model - convenience import from database models.

This module provides direct access to the AnalysisJob and JobStatus
classes for easier importing in Lambda functions.
"""

from .database import AnalysisJob, JobStatus

__all__ = ['AnalysisJob', 'JobStatus']