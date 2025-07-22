"""
Utility functions for file operations.

This module provides utility functions for handling file uploads, downloads,
and S3 operations.
"""

import os
import io
import uuid
import logging
from typing import Tuple, Optional, Dict, Any

import boto3
from botocore.exceptions import ClientError
import streamlit as st
from PIL import Image
import requests

# Configure logging
logger = logging.getLogger(__name__)


def validate_file(file, allowed_extensions=None, max_size_mb=10):
    """
    Validate an uploaded file.
    
    Args:
        file: The uploaded file
        allowed_extensions: List of allowed file extensions (optional)
        max_size_mb: Maximum file size in MB (optional)
        
    Returns:
        Tuple[bool, str]: Validation result and message
    """
    if file is None:
        return False, "No file uploaded"
    
    # Check file size
    file_size_mb = len(file.getvalue()) / (1024 * 1024)
    if file_size_mb > max_size_mb:
        return False, f"File size exceeds maximum allowed size of {max_size_mb}MB"
    
    # Check file extension if specified
    if allowed_extensions:
        file_ext = os.path.splitext(file.name)[1].lower()
        if file_ext not in allowed_extensions:
            return False, f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
    
    return True, "File validation successful"


def get_s3_client(aws_access_key_id=None, aws_secret_access_key=None, region_name=None):
    """
    Get an authenticated S3 client.
    
    Args:
        aws_access_key_id: AWS access key ID (optional)
        aws_secret_access_key: AWS secret access key (optional)
        region_name: AWS region name (optional)
        
    Returns:
        boto3.client: S3 client
    """
    # Use environment variables if parameters not provided
    if aws_access_key_id is None:
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    
    if aws_secret_access_key is None:
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    if region_name is None:
        region_name = os.getenv("AWS_REGION", "us-east-1")
    
    # Create S3 client
    return boto3.client(
        's3',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name
    )


def upload_to_s3(file_bytes, file_name, bucket_name, prefix="uploads", user_id=None):
    """
    Upload a file to S3 bucket.
    
    Args:
        file_bytes: The file content as bytes
        file_name: The name of the file
        bucket_name: The name of the S3 bucket
        prefix: The S3 key prefix (optional)
        user_id: The user ID for the file path (optional)
        
    Returns:
        Tuple[bool, str]: Success status and S3 key or error message
    """
    try:
        # Generate a unique key for the file
        file_extension = os.path.splitext(file_name)[1]
        
        # Include user_id in the path if provided
        if user_id:
            s3_key = f"{prefix}/{user_id}/{uuid.uuid4()}{file_extension}"
        else:
            s3_key = f"{prefix}/{uuid.uuid4()}{file_extension}"
        
        # Upload the file
        s3_client = get_s3_client()
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=file_bytes,
            ContentType=f"image/{file_extension[1:]}"  # Remove the dot from extension
        )
        
        return True, s3_key
    
    except ClientError as e:
        logger.error(f"Error uploading file to S3: {e}")
        return False, str(e)


def get_presigned_url(bucket_name, s3_key, expiration=3600):
    """
    Generate a presigned URL for an S3 object.
    
    Args:
        bucket_name: The name of the S3 bucket
        s3_key: The S3 key of the object
        expiration: URL expiration time in seconds (optional)
        
    Returns:
        str: Presigned URL or None if failed
    """
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}")
        return None


def display_image_with_url(url, caption=None, width=None):
    """
    Display an image from a URL.
    
    Args:
        url: The image URL
        caption: Image caption (optional)
        width: Image width (optional)
        
    Returns:
        bool: Success status
    """
    try:
        response = requests.get(url)
        image = Image.open(io.BytesIO(response.content))
        st.image(image, caption=caption, width=width)
        return True
    except Exception as e:
        st.error(f"Failed to load image: {e}")
        return False


def create_download_link(content, filename, link_text="Download"):
    """
    Create a download link for file content.
    
    Args:
        content: The file content as bytes or string
        filename: The filename for the download
        link_text: The text to display for the link (optional)
        
    Returns:
        str: HTML link for downloading the file
    """
    import base64
    
    # Convert string to bytes if needed
    if isinstance(content, str):
        content = content.encode()
    
    b64 = base64.b64encode(content).decode()
    href = f'<a href="data:file/txt;base64,{b64}" download="{filename}">{link_text}</a>'
    return href