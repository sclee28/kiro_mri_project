"""
Example script for using WebSocket for real-time updates.

This script demonstrates how to use the WebSocket API to receive
real-time updates about job status and processing progress.
"""

import json
import asyncio
import streamlit as st
import websockets
import requests
from streamlit_autorefresh import st_autorefresh


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


async def connect_websocket(ws_url, api_key, job_id):
    """
    Connect to WebSocket and subscribe to job updates.
    
    Args:
        ws_url: The WebSocket URL
        api_key: The API key
        job_id: The job ID to subscribe to
        
    Returns:
        list: List of received messages
    """
    messages = []
    
    try:
        # Connect to WebSocket with API key
        async with websockets.connect(ws_url, extra_headers={"X-API-Key": api_key}) as websocket:
            # Subscribe to job updates
            await websocket.send(json.dumps({
                "action": "subscribe",
                "job_id": job_id
            }))
            
            # Wait for subscription confirmation
            response = await websocket.recv()
            messages.append(json.loads(response))
            
            # Set a timeout for receiving messages
            timeout = 30  # seconds
            start_time = asyncio.get_event_loop().time()
            
            # Receive messages until timeout
            while asyncio.get_event_loop().time() - start_time < timeout:
                try:
                    # Wait for a message with a short timeout
                    message = await asyncio.wait_for(websocket.recv(), timeout=1)
                    messages.append(json.loads(message))
                except asyncio.TimeoutError:
                    # No message received within the timeout
                    continue
            
            # Unsubscribe from job updates
            await websocket.send(json.dumps({
                "action": "unsubscribe",
                "job_id": job_id
            }))
            
            # Wait for unsubscription confirmation
            response = await websocket.recv()
            messages.append(json.loads(response))
    
    except Exception as e:
        st.error(f"WebSocket error: {e}")
    
    return messages


def websocket_demo():
    """Streamlit demo for WebSocket updates."""
    st.title("WebSocket Real-time Updates Demo")
    
    # Auto-refresh the page every 5 seconds
    st_autorefresh(interval=5000, key="websocket_refresh")
    
    # API configuration
    api_url = st.text_input("API URL", value="http://localhost:8000")
    ws_url = st.text_input("WebSocket URL", value="ws://localhost:8000/ws")
    api_key = st.text_input("API Key", value="dev-api-key-for-testing", type="password")
    
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
    
    # Job selection
    if "access_token" in st.session_state:
        st.subheader("Job Selection")
        
        # Get user's jobs
        try:
            response = requests.get(
                f"{api_url}/api/jobs",
                headers={"Authorization": f"Bearer {st.session_state.access_token}"},
                params={"user_id": username}
            )
            response.raise_for_status()
            
            jobs = response.json()
            
            if jobs:
                # Create a selectbox with job IDs
                job_options = [f"{job['job_id']} - {job['status']}" for job in jobs]
                selected_job = st.selectbox("Select a job", job_options)
                
                if selected_job:
                    # Extract job ID from selected option
                    job_id = selected_job.split(" - ")[0]
                    
                    # Store selected job ID in session state
                    st.session_state.selected_job_id = job_id
                    
                    # Display job details
                    job_details = next((job for job in jobs if job["job_id"] == job_id), None)
                    if job_details:
                        st.write(f"Status: {job_details['status']}")
                        st.write(f"Created: {job_details['created_at']}")
                        st.write(f"Updated: {job_details['updated_at']}")
            else:
                st.info("No jobs found")
        
        except Exception as e:
            st.error(f"Failed to get jobs: {e}")
    
    # WebSocket connection
    if "selected_job_id" in st.session_state:
        st.subheader("WebSocket Updates")
        
        if st.button("Connect to WebSocket"):
            # Run WebSocket connection in asyncio event loop
            job_id = st.session_state.selected_job_id
            messages = asyncio.run(connect_websocket(ws_url, api_key, job_id))
            
            # Store messages in session state
            st.session_state.websocket_messages = messages
        
        # Display received messages
        if "websocket_messages" in st.session_state:
            st.write(f"Received {len(st.session_state.websocket_messages)} messages:")
            
            for i, message in enumerate(st.session_state.websocket_messages):
                st.json(message)
        
        # Simulate job update
        st.subheader("Simulate Job Update")
        
        status_options = ["UPLOADED", "SEGMENTING", "CONVERTING", "ENHANCING", "COMPLETED", "FAILED"]
        status = st.selectbox("Status", status_options)
        progress = st.slider("Progress", 0.0, 1.0, 0.5, 0.01)
        message = st.text_input("Message", value="Processing in progress...")
        
        if st.button("Send Update"):
            try:
                response = requests.post(
                    f"{api_url}/api/jobs/{st.session_state.selected_job_id}/update",
                    headers={"X-API-Key": api_key},
                    data={
                        "status": status,
                        "progress": progress,
                        "message": message
                    }
                )
                response.raise_for_status()
                
                st.success("Update sent successfully!")
            except Exception as e:
                st.error(f"Failed to send update: {e}")


if __name__ == "__main__":
    websocket_demo()