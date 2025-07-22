"""
WebSocket client for real-time updates.

This module provides a WebSocket client for receiving real-time updates
about job status and processing progress.
"""

import json
import logging
import threading
import time
from typing import Dict, Any, Callable, Optional

import websocket
import streamlit as st

# Configure logging
logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    WebSocket client for real-time updates.
    
    This client connects to a WebSocket server and receives real-time updates
    about job status and processing progress.
    """
    
    def __init__(self, url: str, on_message: Callable[[Dict[str, Any]], None]):
        """
        Initialize the WebSocket client.
        
        Args:
            url: The WebSocket server URL
            on_message: Callback function for handling messages
        """
        self.url = url
        self.on_message = on_message
        self.ws = None
        self.connected = False
        self.thread = None
        self.should_reconnect = True
        self.reconnect_interval = 3  # seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
    
    def connect(self):
        """Connect to the WebSocket server."""
        if self.connected:
            return
        
        try:
            # Create WebSocket connection
            self.ws = websocket.WebSocketApp(
                self.url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open
            )
            
            # Start WebSocket connection in a separate thread
            self.thread = threading.Thread(target=self.ws.run_forever)
            self.thread.daemon = True
            self.thread.start()
            
            logger.info(f"WebSocket client connecting to {self.url}")
        
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket server: {e}")
            self._schedule_reconnect()
    
    def disconnect(self):
        """Disconnect from the WebSocket server."""
        self.should_reconnect = False
        if self.ws:
            self.ws.close()
        
        self.connected = False
        logger.info("WebSocket client disconnected")
    
    def subscribe_to_job(self, job_id: str):
        """
        Subscribe to updates for a specific job.
        
        Args:
            job_id: The ID of the job to subscribe to
        """
        if not self.connected:
            logger.warning("Cannot subscribe: WebSocket not connected")
            return
        
        try:
            message = json.dumps({
                "action": "subscribe",
                "job_id": job_id
            })
            self.ws.send(message)
            logger.info(f"Subscribed to updates for job {job_id}")
        
        except Exception as e:
            logger.error(f"Failed to subscribe to job updates: {e}")
    
    def _on_message(self, ws, message):
        """
        Handle incoming WebSocket messages.
        
        Args:
            ws: WebSocket connection
            message: The received message
        """
        try:
            data = json.loads(message)
            self.on_message(data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse WebSocket message: {message}")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
    
    def _on_error(self, ws, error):
        """
        Handle WebSocket errors.
        
        Args:
            ws: WebSocket connection
            error: The error
        """
        logger.error(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """
        Handle WebSocket connection close.
        
        Args:
            ws: WebSocket connection
            close_status_code: Close status code
            close_msg: Close message
        """
        self.connected = False
        logger.info(f"WebSocket connection closed: {close_status_code} {close_msg}")
        
        if self.should_reconnect:
            self._schedule_reconnect()
    
    def _on_open(self, ws):
        """
        Handle WebSocket connection open.
        
        Args:
            ws: WebSocket connection
        """
        self.connected = True
        self.reconnect_attempts = 0
        logger.info("WebSocket connection established")
    
    def _schedule_reconnect(self):
        """Schedule a reconnection attempt."""
        if not self.should_reconnect:
            return
        
        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnect_attempts:
            logger.error("Maximum reconnection attempts reached")
            return
        
        logger.info(f"Scheduling reconnection attempt {self.reconnect_attempts} in {self.reconnect_interval} seconds")
        
        def reconnect():
            if self.should_reconnect:
                self.connect()
        
        threading.Timer(self.reconnect_interval, reconnect).start()


# Simulated WebSocket client for development
class SimulatedWebSocketClient:
    """
    Simulated WebSocket client for development.
    
    This client simulates WebSocket updates for development and testing.
    """
    
    def __init__(self, on_message: Callable[[Dict[str, Any]], None]):
        """
        Initialize the simulated WebSocket client.
        
        Args:
            on_message: Callback function for handling messages
        """
        self.on_message = on_message
        self.connected = False
        self.thread = None
        self.subscribed_jobs = set()
        self.running = False
    
    def connect(self):
        """Connect to the simulated WebSocket server."""
        if self.connected:
            return
        
        self.connected = True
        self.running = True
        
        # Start simulation thread
        self.thread = threading.Thread(target=self._simulation_loop)
        self.thread.daemon = True
        self.thread.start()
        
        logger.info("Simulated WebSocket client connected")
    
    def disconnect(self):
        """Disconnect from the simulated WebSocket server."""
        self.running = False
        self.connected = False
        self.subscribed_jobs = set()
        logger.info("Simulated WebSocket client disconnected")
    
    def subscribe_to_job(self, job_id: str):
        """
        Subscribe to updates for a specific job.
        
        Args:
            job_id: The ID of the job to subscribe to
        """
        if not self.connected:
            logger.warning("Cannot subscribe: WebSocket not connected")
            return
        
        self.subscribed_jobs.add(job_id)
        logger.info(f"Subscribed to updates for job {job_id}")
    
    def _simulation_loop(self):
        """Simulation loop for generating fake updates."""
        while self.running:
            # Sleep for a random interval
            time.sleep(5)
            
            # Generate updates for subscribed jobs
            for job_id in self.subscribed_jobs:
                # Generate a random status update
                import random
                statuses = ["UPLOADED", "SEGMENTING", "CONVERTING", "ENHANCING", "COMPLETED"]
                status = random.choice(statuses)
                
                # Generate progress percentage
                progress = random.uniform(0, 1)
                
                # Create update message
                message = {
                    "job_id": job_id,
                    "status": status,
                    "progress": progress,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                
                # Send message to callback
                self.on_message(message)


def get_websocket_client(url: Optional[str] = None) -> WebSocketClient:
    """
    Get a WebSocket client instance.
    
    Args:
        url: The WebSocket server URL (optional)
        
    Returns:
        WebSocketClient: A WebSocket client instance
    """
    # Use simulated client if no URL is provided
    if url is None or url == "simulated":
        return SimulatedWebSocketClient(on_message=_handle_websocket_message)
    else:
        return WebSocketClient(url=url, on_message=_handle_websocket_message)


def _handle_websocket_message(data: Dict[str, Any]):
    """
    Handle incoming WebSocket messages.
    
    This function updates the session state with the received data.
    
    Args:
        data: The message data
    """
    # Store the update in session state
    if "job_id" in data:
        job_id = data["job_id"]
        
        # Initialize updates dict if needed
        if "websocket_updates" not in st.session_state:
            st.session_state.websocket_updates = {}
        
        # Store update for this job
        st.session_state.websocket_updates[job_id] = data
        
        # Set refresh flag to update UI
        st.session_state.refresh_data = True
        
        logger.info(f"Received update for job {job_id}: {data['status']}")