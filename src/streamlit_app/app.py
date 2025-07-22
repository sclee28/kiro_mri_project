"""
Healthcare Image Analysis - Streamlit Frontend Application

This is the main entry point for the Streamlit web application that allows users
to upload MRI images, track processing status, and view analysis results.
"""

import os
import uuid
import json
import logging
from datetime import datetime
import time
from typing import Dict, Any, Optional, Tuple

import streamlit as st
import boto3
from botocore.exceptions import ClientError
import pandas as pd
import plotly.express as px
from PIL import Image
import io
import requests

from api_client import APIClient
from auth import authenticate_user, login_required, logout_user, get_current_user
from config import load_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration
config = load_config()

# Initialize API client
api_client = APIClient(base_url=config.api_base_url)

# Set page configuration
st.set_page_config(
    page_title="Healthcare Image Analysis",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #0083B8;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #0083B8;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .status-box {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .status-uploaded {
        background-color: #f0f2f6;
    }
    .status-segmenting {
        background-color: #ffffd0;
    }
    .status-converting {
        background-color: #d0ffff;
    }
    .status-enhancing {
        background-color: #d0d0ff;
    }
    .status-completed {
        background-color: #d0ffd0;
    }
    .status-failed {
        background-color: #ffd0d0;
    }
    .info-box {
        background-color: #e6f3ff;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .stButton>button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)


def initialize_session_state():
    """Initialize session state variables if they don't exist."""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'jobs' not in st.session_state:
        st.session_state.jobs = []
    if 'selected_job_id' not in st.session_state:
        st.session_state.selected_job_id = None
    if 'refresh_data' not in st.session_state:
        st.session_state.refresh_data = True


def display_header():
    """Display the application header."""
    st.markdown('<h1 class="main-header">Healthcare Image Analysis</h1>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="info-box">
        This application allows healthcare professionals to upload MRI images for automated analysis.
        The system processes images through segmentation, image-to-text conversion, and LLM-enhanced analysis
        to generate comprehensive medical reports.
        </div>
        """,
        unsafe_allow_html=True
    )


def login_page():
    """Display the login page."""
    st.markdown('<h2 class="sub-header">Login</h2>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        
        if st.button("Login"):
            if authenticate_user(username, password):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.user_id = username  # In a real app, this would be a proper user ID
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid username or password")
    
    with col2:
        st.markdown(
            """
            <div class="info-box">
            <h3>Demo Credentials</h3>
            <p>For demonstration purposes, use:</p>
            <ul>
                <li>Username: demo</li>
                <li>Password: password</li>
            </ul>
            </div>
            """,
            unsafe_allow_html=True
        )


def sidebar():
    """Display the sidebar with navigation options."""
    st.sidebar.title("Navigation")
    
    # User info
    st.sidebar.markdown(f"**Logged in as:** {st.session_state.username}")
    
    # Navigation
    page = st.sidebar.radio(
        "Select Page",
        ["Upload Image", "My Jobs", "Results"]
    )
    
    # Logout button
    if st.sidebar.button("Logout"):
        logout_user()
        st.rerun()
    
    return page


def get_s3_client():
    """Get an authenticated S3 client."""
    return boto3.client(
        's3',
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
        region_name=config.aws_region
    )


def upload_to_s3(file_bytes, file_name):
    """
    Upload a file to S3 bucket.
    
    Args:
        file_bytes: The file content as bytes
        file_name: The name of the file
        
    Returns:
        Tuple[bool, str]: Success status and S3 key or error message
    """
    try:
        # Generate a unique key for the file
        file_extension = os.path.splitext(file_name)[1]
        s3_key = f"uploads/{st.session_state.user_id}/{uuid.uuid4()}{file_extension}"
        
        # Upload the file
        s3_client = get_s3_client()
        s3_client.put_object(
            Bucket=config.s3_bucket_name,
            Key=s3_key,
            Body=file_bytes,
            ContentType=f"image/{file_extension[1:]}"  # Remove the dot from extension
        )
        
        return True, s3_key
    
    except ClientError as e:
        logger.error(f"Error uploading file to S3: {e}")
        return False, str(e)


def create_analysis_job(s3_key):
    """
    Create a new analysis job via the API.
    
    Args:
        s3_key: The S3 key of the uploaded image
        
    Returns:
        Tuple[bool, str]: Success status and job ID or error message
    """
    try:
        response = api_client.create_job(
            user_id=st.session_state.user_id,
            image_key=s3_key
        )
        
        if response.get('job_id'):
            return True, response['job_id']
        else:
            return False, "Failed to create job: No job ID returned"
    
    except Exception as e:
        logger.error(f"Error creating analysis job: {e}")
        return False, str(e)


def get_user_jobs():
    """
    Get all jobs for the current user.
    
    Returns:
        List[Dict]: List of job dictionaries
    """
    try:
        jobs = api_client.get_user_jobs(user_id=st.session_state.user_id)
        return jobs
    except Exception as e:
        logger.error(f"Error fetching user jobs: {e}")
        st.error(f"Failed to fetch jobs: {e}")
        return []


def get_job_details(job_id):
    """
    Get detailed information about a specific job.
    
    Args:
        job_id: The ID of the job
        
    Returns:
        Dict: Job details including results if available
    """
    try:
        job_details = api_client.get_job_details(job_id=job_id)
        return job_details
    except Exception as e:
        logger.error(f"Error fetching job details: {e}")
        st.error(f"Failed to fetch job details: {e}")
        return None


def get_presigned_url(s3_key):
    """
    Generate a presigned URL for an S3 object.
    
    Args:
        s3_key: The S3 key of the object
        
    Returns:
        str: Presigned URL or None if failed
    """
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': config.s3_bucket_name,
                'Key': s3_key
            },
            ExpiresIn=3600  # URL valid for 1 hour
        )
        return url
    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}")
        return None


def display_job_status(job):
    """Display the status of a job with appropriate styling."""
    status = job.get('status', 'unknown')
    status_class = f"status-{status.lower()}"
    
    st.markdown(
        f"""
        <div class="status-box {status_class}">
            <h3>Job Status: {status.upper()}</h3>
            <p>Job ID: {job.get('job_id')}</p>
            <p>Created: {job.get('created_at')}</p>
            <p>Last Updated: {job.get('updated_at')}</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Display progress based on status
    progress_value = {
        'uploaded': 0.2,
        'segmenting': 0.4,
        'converting': 0.6,
        'enhancing': 0.8,
        'completed': 1.0,
        'failed': 1.0
    }.get(status.lower(), 0)
    
    st.progress(progress_value)
    
    # Display estimated time remaining
    if status.lower() not in ['completed', 'failed']:
        st.info("Estimated time remaining: Calculating...")


def display_image_with_url(url, caption):
    """Display an image from a URL."""
    try:
        response = requests.get(url)
        image = Image.open(io.BytesIO(response.content))
        st.image(image, caption=caption, use_column_width=True)
    except Exception as e:
        st.error(f"Failed to load image: {e}")


def display_results(job_details):
    """Display the analysis results for a completed job."""
    if not job_details or not job_details.get('results'):
        st.warning("No results available for this job.")
        return
    
    results = job_details['results']
    
    # Display original image
    original_image_url = get_presigned_url(job_details.get('original_image_key'))
    if original_image_url:
        st.markdown('<h3>Original MRI Image</h3>', unsafe_allow_html=True)
        display_image_with_url(original_image_url, "Original MRI Image")
    
    # Display segmentation result if available
    if results.get('segmentation_result_key'):
        segmentation_url = get_presigned_url(results['segmentation_result_key'])
        if segmentation_url:
            st.markdown('<h3>Segmentation Result</h3>', unsafe_allow_html=True)
            display_image_with_url(segmentation_url, "Segmented MRI Image")
    
    # Display image description
    if results.get('image_description'):
        st.markdown('<h3>Image Description</h3>', unsafe_allow_html=True)
        st.markdown(results['image_description'])
    
    # Display enhanced report
    if results.get('enhanced_report'):
        st.markdown('<h3>Enhanced Medical Report</h3>', unsafe_allow_html=True)
        st.markdown(results['enhanced_report'])
    
    # Display confidence scores if available
    if results.get('confidence_scores'):
        st.markdown('<h3>Confidence Scores</h3>', unsafe_allow_html=True)
        
        confidence_scores = results['confidence_scores']
        if isinstance(confidence_scores, str):
            try:
                confidence_scores = json.loads(confidence_scores)
            except json.JSONDecodeError:
                confidence_scores = {}
        
        if confidence_scores:
            # Create a DataFrame for the confidence scores
            df = pd.DataFrame({
                'Model': list(confidence_scores.keys()),
                'Confidence': list(confidence_scores.values())
            })
            
            # Create a bar chart
            fig = px.bar(
                df, 
                x='Model', 
                y='Confidence', 
                title='Model Confidence Scores',
                color='Confidence',
                color_continuous_scale='Viridis',
                range_y=[0, 1]
            )
            st.plotly_chart(fig, use_container_width=True)
    
    # Download buttons
    st.markdown('<h3>Download Results</h3>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if results.get('enhanced_report'):
            if st.button("Download Report (PDF)"):
                st.info("PDF download functionality would be implemented here")
    
    with col2:
        if results.get('segmentation_result_key'):
            if st.button("Download Segmentation Image"):
                segmentation_url = get_presigned_url(results['segmentation_result_key'])
                if segmentation_url:
                    st.markdown(f"[Click here to download]({segmentation_url})")
    
    with col3:
        if st.button("Download All Results (ZIP)"):
            st.info("ZIP download functionality would be implemented here")


def upload_page():
    """Display the upload page."""
    st.markdown('<h2 class="sub-header">Upload MRI Image</h2>', unsafe_allow_html=True)
    
    # File uploader
    uploaded_file = st.file_uploader(
        "Choose an MRI image file",
        type=["jpg", "jpeg", "png", "dicom", "dcm", "nii", "nii.gz"]
    )
    
    if uploaded_file is not None:
        # Display the uploaded image
        try:
            image = Image.open(uploaded_file)
            st.image(image, caption="Uploaded MRI Image", use_column_width=True)
        except:
            st.info("Preview not available for this file format. Processing will still work.")
        
        # Upload button
        if st.button("Process Image"):
            with st.spinner("Uploading image..."):
                # Reset the file pointer to the beginning
                uploaded_file.seek(0)
                
                # Upload to S3
                success, s3_key_or_error = upload_to_s3(
                    uploaded_file.getvalue(),
                    uploaded_file.name
                )
                
                if success:
                    st.success(f"Image uploaded successfully to S3: {s3_key_or_error}")
                    
                    # Create analysis job
                    with st.spinner("Creating analysis job..."):
                        job_success, job_id_or_error = create_analysis_job(s3_key_or_error)
                        
                        if job_success:
                            st.success(f"Analysis job created successfully. Job ID: {job_id_or_error}")
                            st.session_state.selected_job_id = job_id_or_error
                            st.session_state.refresh_data = True
                            
                            # Redirect to job details
                            st.info("Redirecting to job status page...")
                            time.sleep(2)
                            st.rerun()
                        else:
                            st.error(f"Failed to create analysis job: {job_id_or_error}")
                else:
                    st.error(f"Failed to upload image: {s3_key_or_error}")


def jobs_page():
    """Display the jobs page with a list of user's jobs."""
    st.markdown('<h2 class="sub-header">My Analysis Jobs</h2>', unsafe_allow_html=True)
    
    # Refresh button
    if st.button("Refresh Jobs"):
        st.session_state.refresh_data = True
    
    # Fetch jobs if needed
    if st.session_state.refresh_data:
        with st.spinner("Fetching jobs..."):
            st.session_state.jobs = get_user_jobs()
            st.session_state.refresh_data = False
    
    # Display jobs in a table
    if st.session_state.jobs:
        # Create a DataFrame for the jobs
        jobs_data = []
        for job in st.session_state.jobs:
            jobs_data.append({
                "Job ID": job.get('job_id'),
                "Status": job.get('status', 'Unknown'),
                "Created": job.get('created_at', 'Unknown'),
                "Updated": job.get('updated_at', 'Unknown')
            })
        
        df = pd.DataFrame(jobs_data)
        
        # Apply color coding to the status column
        def color_status(val):
            color_map = {
                'UPLOADED': 'background-color: #f0f2f6',
                'SEGMENTING': 'background-color: #ffffd0',
                'CONVERTING': 'background-color: #d0ffff',
                'ENHANCING': 'background-color: #d0d0ff',
                'COMPLETED': 'background-color: #d0ffd0',
                'FAILED': 'background-color: #ffd0d0'
            }
            return color_map.get(val, '')
        
        # Display the styled table
        st.dataframe(
            df.style.applymap(color_status, subset=['Status']),
            use_container_width=True
        )
        
        # Job selection
        selected_job_id = st.selectbox(
            "Select a job to view details",
            options=[job.get('job_id') for job in st.session_state.jobs],
            index=0 if st.session_state.jobs else None
        )
        
        if selected_job_id:
            st.session_state.selected_job_id = selected_job_id
            
            # View details button
            if st.button("View Job Details"):
                st.rerun()
    else:
        st.info("No jobs found. Upload an MRI image to create a new analysis job.")


def results_page():
    """Display the results page for a selected job."""
    st.markdown('<h2 class="sub-header">Analysis Results</h2>', unsafe_allow_html=True)
    
    if not st.session_state.selected_job_id:
        st.warning("No job selected. Please select a job from the 'My Jobs' page.")
        return
    
    # Fetch job details
    with st.spinner("Loading job details..."):
        job_details = get_job_details(st.session_state.selected_job_id)
    
    if not job_details:
        st.error("Failed to load job details.")
        return
    
    # Display job status
    display_job_status(job_details)
    
    # Display results if job is completed
    if job_details.get('status', '').lower() == 'completed':
        display_results(job_details)
    elif job_details.get('status', '').lower() == 'failed':
        st.error(f"Job failed: {job_details.get('error_message', 'Unknown error')}")
    else:
        st.info("Job is still processing. Results will be available once processing is complete.")
        
        # Add auto-refresh for in-progress jobs
        st.markdown("Page will refresh automatically every 10 seconds...")
        time.sleep(10)
        st.rerun()


def main():
    """Main application entry point."""
    initialize_session_state()
    display_header()
    
    # Check authentication
    if not st.session_state.authenticated:
        login_page()
    else:
        # Display sidebar and get selected page
        page = sidebar()
        
        # Display selected page
        if page == "Upload Image":
            upload_page()
        elif page == "My Jobs":
            jobs_page()
        elif page == "Results":
            results_page()


if __name__ == "__main__":
    main()