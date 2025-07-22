"""
Example script for using presigned URLs for direct S3 uploads.

This script demonstrates how to use the presigned URL API endpoint
to upload files directly to S3 from the client side.
"""

import os
import requests
import json
import mimetypes
import streamlit as st


def get_access_token(api_url, username, password):
    """
    Get an access token using username and password.
    
    Args:
        api_url: The API base URL
        username: The username
        password: The password
        
    Returns:
        str: The access token or None if authentication fails
    """
    try:
        response = requests.post(
            f"{api_url}/api/token",
            data={"username": username, "password": password}
        )
        response.raise_for_status()
        
        token_data = response.json()
        return token_data["access_token"]
    
    except Exception as e:
        st.error(f"Authentication failed: {e}")
        return None


def get_presigned_url(api_url, access_token, filename, user_id):
    """
    Get a presigned URL for direct S3 upload.
    
    Args:
        api_url: The API base URL
        access_token: The access token
        filename: The name of the file to upload
        user_id: The user ID
        
    Returns:
        tuple: (presigned_url, s3_key) or (None, None) if failed
    """
    try:
        # Determine content type
        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = "application/octet-stream"
        
        # Request presigned URL
        response = requests.post(
            f"{api_url}/api/presigned-url",
            headers={"Authorization": f"Bearer {access_token}"},
            data={
                "filename": filename,
                "user_id": user_id,
                "content_type": content_type
            }
        )
        response.raise_for_status()
        
        data = response.json()
        return data["presigned_url"], data["s3_key"]
    
    except Exception as e:
        st.error(f"Failed to get presigned URL: {e}")
        return None, None


def upload_file_with_presigned_url(presigned_url, file_path, content_type):
    """
    Upload a file using a presigned URL.
    
    Args:
        presigned_url: The presigned URL
        file_path: The path to the file
        content_type: The content type of the file
        
    Returns:
        bool: True if upload was successful, False otherwise
    """
    try:
        with open(file_path, "rb") as file:
            file_data = file.read()
        
        # Upload file directly to S3
        response = requests.put(
            presigned_url,
            data=file_data,
            headers={"Content-Type": content_type}
        )
        response.raise_for_status()
        
        return True
    
    except Exception as e:
        st.error(f"Failed to upload file: {e}")
        return False


def create_job(api_url, access_token, user_id, s3_key):
    """
    Create a new analysis job.
    
    Args:
        api_url: The API base URL
        access_token: The access token
        user_id: The user ID
        s3_key: The S3 key of the uploaded image
        
    Returns:
        str: The job ID or None if failed
    """
    try:
        response = requests.post(
            f"{api_url}/api/jobs",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "user_id": user_id,
                "image_key": s3_key
            }
        )
        response.raise_for_status()
        
        job_data = response.json()
        return job_data["job_id"]
    
    except Exception as e:
        st.error(f"Failed to create job: {e}")
        return None


def presigned_upload_demo():
    """Streamlit demo for presigned URL uploads."""
    st.title("Presigned URL Upload Demo")
    
    # API configuration
    api_url = st.text_input("API URL", value="http://localhost:8000")
    
    # Authentication
    st.subheader("Authentication")
    username = st.text_input("Username", value="demo")
    password = st.text_input("Password", value="password", type="password")
    
    if st.button("Authenticate"):
        access_token = get_access_token(api_url, username, password)
        if access_token:
            st.session_state.access_token = access_token
            st.success("Authentication successful!")
        else:
            st.error("Authentication failed!")
    
    # File upload
    if "access_token" in st.session_state:
        st.subheader("File Upload")
        uploaded_file = st.file_uploader("Choose an MRI image file", type=["jpg", "jpeg", "png", "dcm"])
        
        if uploaded_file is not None:
            # Display the uploaded image
            st.image(uploaded_file, caption="Uploaded Image", width=300)
            
            # Get presigned URL
            if st.button("Upload and Process"):
                # Save uploaded file temporarily
                temp_file_path = f"/tmp/{uploaded_file.name}"
                with open(temp_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # Get content type
                content_type, _ = mimetypes.guess_type(uploaded_file.name)
                if content_type is None:
                    content_type = "application/octet-stream"
                
                # Get presigned URL
                presigned_url, s3_key = get_presigned_url(
                    api_url,
                    st.session_state.access_token,
                    uploaded_file.name,
                    username
                )
                
                if presigned_url and s3_key:
                    # Upload file
                    if upload_file_with_presigned_url(presigned_url, temp_file_path, content_type):
                        st.success(f"File uploaded successfully to S3 key: {s3_key}")
                        
                        # Create job
                        job_id = create_job(api_url, st.session_state.access_token, username, s3_key)
                        if job_id:
                            st.success(f"Job created successfully with ID: {job_id}")
                            
                            # Store job ID in session state
                            if "jobs" not in st.session_state:
                                st.session_state.jobs = []
                            
                            st.session_state.jobs.append({
                                "job_id": job_id,
                                "s3_key": s3_key,
                                "filename": uploaded_file.name
                            })
                    else:
                        st.error("Failed to upload file")
                
                # Clean up temporary file
                os.remove(temp_file_path)
        
        # Job tracking
        if "jobs" in st.session_state and st.session_state.jobs:
            st.subheader("Job Tracking")
            
            for job in st.session_state.jobs:
                st.write(f"Job ID: {job['job_id']}")
                st.write(f"File: {job['filename']}")
                st.write(f"S3 Key: {job['s3_key']}")
                
                if st.button(f"Check Status for {job['job_id']}", key=job['job_id']):
                    try:
                        response = requests.get(
                            f"{api_url}/api/jobs/{job['job_id']}",
                            headers={"Authorization": f"Bearer {st.session_state.access_token}"}
                        )
                        response.raise_for_status()
                        
                        job_data = response.json()
                        st.json(job_data)
                    except Exception as e:
                        st.error(f"Failed to get job status: {e}")


if __name__ == "__main__":
    presigned_upload_demo()