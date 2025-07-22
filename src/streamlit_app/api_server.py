"""
API server for the Streamlit application.

This module provides a FastAPI server for handling API requests from the
Streamlit application. It can be run alongside the Streamlit app to provide
backend services.
"""

import os
import uuid
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, Query, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session
import jwt
from datetime import datetime, timedelta

# Import database models and utilities
import sys
import os

# Add parent directory to path to import shared modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.utils.database import get_db_session, db_session_scope
from shared.models.database import AnalysisJob, AnalysisResult, JobStatus

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Healthcare Image Analysis API",
    description="API for the Healthcare Image Analysis system",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication configuration
API_KEY_NAME = "X-API-Key"
API_KEY_HEADER = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
OAUTH2_SCHEME = OAuth2PasswordBearer(tokenUrl="api/token")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "development_secret_key")  # Change in production
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60 * 24  # 24 hours

# Demo users (in a real application, this would be stored in a database)
# Same as in auth.py for consistency
DEMO_USERS = {
    "demo": {
        "password_hash": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",  # password
        "name": "Demo User",
        "role": "healthcare_professional"
    },
    "admin": {
        "password_hash": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",  # admin
        "name": "Admin User",
        "role": "administrator"
    }
}


# Pydantic models for API requests and responses
class JobCreate(BaseModel):
    """Model for creating a new analysis job."""
    user_id: str
    image_key: str


class JobResponse(BaseModel):
    """Model for job response."""
    job_id: str
    user_id: str
    original_image_key: str
    status: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


class ResultResponse(BaseModel):
    """Model for result response."""
    result_id: str
    job_id: str
    segmentation_result_key: Optional[str] = None
    image_description: Optional[str] = None
    enhanced_report: Optional[str] = None
    confidence_scores: Optional[Dict[str, float]] = None
    processing_metrics: Optional[Dict[str, Any]] = None
    created_at: str


class JobDetailResponse(JobResponse):
    """Model for detailed job response including results."""
    results: Optional[ResultResponse] = None


class Token(BaseModel):
    """Model for token response."""
    access_token: str
    token_type: str
    expires_in: int
    user_id: str
    name: str
    role: str


class TokenData(BaseModel):
    """Model for token data."""
    username: str
    role: str
    exp: datetime


class UserCredentials(BaseModel):
    """Model for user credentials."""
    username: str
    password: str


# Authentication functions
def hash_password(password: str) -> str:
    """
    Hash a password using SHA-256.
    
    Args:
        password: The password to hash
        
    Returns:
        str: The hashed password
    """
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


def authenticate_user(username: str, password: str) -> bool:
    """
    Authenticate a user with username and password.
    
    Args:
        username: The username
        password: The password
        
    Returns:
        bool: True if authentication is successful, False otherwise
    """
    import hmac
    
    if username in DEMO_USERS:
        stored_hash = DEMO_USERS[username]["password_hash"]
        provided_hash = hash_password(password)
        
        if hmac.compare_digest(stored_hash, provided_hash):
            logger.info(f"User {username} authenticated successfully")
            return True
    
    logger.warning(f"Failed authentication attempt for user {username}")
    return False


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: The data to encode in the token
        expires_delta: Token expiration time (optional)
        
    Returns:
        str: The encoded JWT token
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRATION_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    return encoded_jwt


async def get_current_user(token: str = Depends(OAUTH2_SCHEME)) -> dict:
    """
    Get the current user from a JWT token.
    
    Args:
        token: The JWT token
        
    Returns:
        dict: User information
        
    Raises:
        HTTPException: If the token is invalid
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode the token
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        
        if username is None:
            raise credentials_exception
        
        # Check if user exists
        if username not in DEMO_USERS:
            raise credentials_exception
        
        return {
            "username": username,
            "name": DEMO_USERS[username]["name"],
            "role": DEMO_USERS[username]["role"]
        }
    
    except jwt.PyJWTError:
        raise credentials_exception


async def get_api_key(api_key_header: str = Security(API_KEY_HEADER)) -> str:
    """
    Validate API key.
    
    Args:
        api_key_header: The API key from the header
        
    Returns:
        str: The validated API key
        
    Raises:
        HTTPException: If the API key is invalid
    """
    # In production, validate against a secure store
    # For this implementation, we'll use a simple environment variable
    valid_api_key = os.getenv("API_KEY", "dev-api-key-for-testing")
    
    if not api_key_header or api_key_header != valid_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return api_key_header


# Authentication endpoints
@app.post("/api/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Get an access token using username and password.
    
    Args:
        form_data: The form data with username and password
        
    Returns:
        Token: The access token
        
    Raises:
        HTTPException: If authentication fails
    """
    # Authenticate user
    if not authenticate_user(form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    expires_delta = timedelta(minutes=JWT_EXPIRATION_MINUTES)
    access_token = create_access_token(
        data={"sub": form_data.username, "role": DEMO_USERS[form_data.username]["role"]},
        expires_delta=expires_delta
    )
    
    # Return token response
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=JWT_EXPIRATION_MINUTES * 60,  # Convert to seconds
        user_id=form_data.username,
        name=DEMO_USERS[form_data.username]["name"],
        role=DEMO_USERS[form_data.username]["role"]
    )


# API endpoints
@app.post("/api/jobs", response_model=JobResponse)
def create_job(job: JobCreate, db: Session = Depends(get_db_session), current_user: dict = Depends(get_current_user)):
    """
    Create a new analysis job.
    
    Args:
        job: Job creation request
        db: Database session
        
    Returns:
        JobResponse: The created job
    """
    try:
        # Create new job
        new_job = AnalysisJob(
            user_id=job.user_id,
            original_image_key=job.image_key,
            status=JobStatus.UPLOADED
        )
        
        # Save to database
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        
        # Return response
        return JobResponse(
            job_id=str(new_job.job_id),
            user_id=new_job.user_id,
            original_image_key=new_job.original_image_key,
            status=new_job.status.value,
            created_at=new_job.created_at.isoformat(),
            updated_at=new_job.updated_at.isoformat(),
            error_message=new_job.error_message
        )
    
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")


@app.get("/api/jobs", response_model=List[JobResponse])
def get_jobs(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user)
):
    """
    Get jobs with optional filtering.
    
    Args:
        user_id: Filter by user ID (optional)
        status: Filter by status (optional)
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip
        db: Database session
        
    Returns:
        List[JobResponse]: List of jobs
    """
    try:
        # Build query
        query = db.query(AnalysisJob)
        
        # Apply filters
        if user_id:
            query = query.filter(AnalysisJob.user_id == user_id)
        
        if status:
            try:
                job_status = JobStatus[status.upper()]
                query = query.filter(AnalysisJob.status == job_status)
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        
        # Apply pagination
        query = query.order_by(AnalysisJob.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        # Execute query
        jobs = query.all()
        
        # Convert to response models
        return [
            JobResponse(
                job_id=str(job.job_id),
                user_id=job.user_id,
                original_image_key=job.original_image_key,
                status=job.status.value,
                created_at=job.created_at.isoformat(),
                updated_at=job.updated_at.isoformat(),
                error_message=job.error_message
            )
            for job in jobs
        ]
    
    except Exception as e:
        logger.error(f"Error getting jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get jobs: {str(e)}")


@app.get("/api/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, db: Session = Depends(get_db_session), current_user: dict = Depends(get_current_user)):
    """
    Get detailed information about a job.
    
    Args:
        job_id: The job ID
        db: Database session
        
    Returns:
        JobDetailResponse: Detailed job information including results
    """
    try:
        # Get job
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        
        # Get results if available
        result = db.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).first()
        
        # Create response
        response = JobDetailResponse(
            job_id=str(job.job_id),
            user_id=job.user_id,
            original_image_key=job.original_image_key,
            status=job.status.value,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
            error_message=job.error_message
        )
        
        # Add results if available
        if result:
            response.results = ResultResponse(
                result_id=str(result.result_id),
                job_id=str(result.job_id),
                segmentation_result_key=result.segmentation_result_key,
                image_description=result.image_description,
                enhanced_report=result.enhanced_report,
                confidence_scores=result.confidence_scores,
                processing_metrics=result.processing_metrics,
                created_at=result.created_at.isoformat()
            )
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get job: {str(e)}")


@app.post("/api/upload", response_model=Dict[str, str])
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a file to S3.
    
    Args:
        file: The file to upload
        user_id: The user ID
        
    Returns:
        Dict[str, str]: Upload result with S3 key
    """
    try:
        # Read file content
        file_content = await file.read()
        
        # Generate S3 key
        file_extension = os.path.splitext(file.filename)[1]
        s3_key = f"uploads/{user_id}/{uuid.uuid4()}{file_extension}"
        
        # Get S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        
        # Upload to S3
        s3_client.put_object(
            Bucket=os.getenv("S3_BUCKET_NAME", "healthcare-mri-images"),
            Key=s3_key,
            Body=file_content,
            ContentType=f"image/{file_extension[1:]}"  # Remove the dot from extension
        )
        
        return {"s3_key": s3_key}
    
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


@app.post("/api/presigned-url", response_model=Dict[str, str])
async def generate_presigned_url(
    filename: str = Form(...),
    user_id: str = Form(...),
    content_type: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a presigned URL for direct S3 upload.
    
    Args:
        filename: The name of the file to upload
        user_id: The user ID
        content_type: The content type of the file
        
    Returns:
        Dict[str, str]: Presigned URL and S3 key
    """
    try:
        # Generate S3 key
        file_extension = os.path.splitext(filename)[1]
        s3_key = f"uploads/{user_id}/{uuid.uuid4()}{file_extension}"
        
        # Get S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        
        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': os.getenv("S3_BUCKET_NAME", "healthcare-mri-images"),
                'Key': s3_key,
                'ContentType': content_type
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )
        
        return {
            "presigned_url": presigned_url,
            "s3_key": s3_key
        }
    
    except Exception as e:
        logger.error(f"Error generating presigned URL: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URL: {str(e)}")


# WebSocket integration
from websocket_server import setup_websocket_routes, broadcast_job_update

# Set up WebSocket routes
setup_websocket_routes(app)


# Add endpoint to broadcast job updates
@app.post("/api/jobs/{job_id}/update", response_model=Dict[str, str])
async def update_job_status(
    job_id: str,
    status: str = Form(...),
    progress: float = Form(None),
    message: str = Form(None),
    api_key: str = Depends(get_api_key)
):
    """
    Update job status and broadcast to WebSocket clients.
    
    Args:
        job_id: The job ID
        status: The new status
        progress: The progress percentage (optional)
        message: Additional message (optional)
        api_key: API key for authentication
        
    Returns:
        Dict[str, str]: Update result
    """
    try:
        # Prepare update data
        data = {
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if progress is not None:
            data["progress"] = progress
        
        if message is not None:
            data["message"] = message
        
        # Broadcast update
        await broadcast_job_update(job_id, data)
        
        return {"status": "success", "message": f"Update broadcast for job {job_id}"}
    
    except Exception as e:
        logger.error(f"Error broadcasting job update: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to broadcast job update: {str(e)}")


def start_server():
    """Start the API server."""
    uvicorn.run(
        "api_server:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("API_RELOAD", "false").lower() == "true"
    )


if __name__ == "__main__":
    start_server()