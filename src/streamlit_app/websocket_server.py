"""
WebSocket server for real-time updates.

This module provides a WebSocket server for sending real-time updates
about job status and processing progress to connected clients.
"""

import os
import json
import logging
import asyncio
import uuid
from typing import Dict, Set, Any, Optional

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# WebSocket connections and subscriptions
active_connections: Dict[str, WebSocket] = {}
job_subscriptions: Dict[str, Set[str]] = {}

# API key header for WebSocket authentication
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


class WebSocketMessage(BaseModel):
    """Model for WebSocket messages."""
    action: str
    job_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


async def get_api_key(api_key_header: str = Depends(API_KEY_HEADER)):
    """
    Validate API key for WebSocket connections.
    
    Args:
        api_key_header: The API key from the header
        
    Returns:
        str: The validated API key
    
    Raises:
        HTTPException: If the API key is invalid
    """
    # In production, validate against a secure store
    # For this implementation, we'll use a simple environment variable
    valid_api_key = os.getenv("WEBSOCKET_API_KEY", "dev-api-key-for-testing")
    
    if not api_key_header or api_key_header != valid_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return api_key_header


async def websocket_endpoint(websocket: WebSocket, api_key: str = Depends(get_api_key)):
    """
    WebSocket endpoint for real-time updates.
    
    Args:
        websocket: The WebSocket connection
        api_key: The validated API key
    """
    # Generate a unique connection ID
    connection_id = str(uuid.uuid4())
    
    try:
        # Accept the connection
        await websocket.accept()
        logger.info(f"WebSocket connection established: {connection_id}")
        
        # Store the connection
        active_connections[connection_id] = websocket
        
        # Handle messages
        while True:
            # Wait for a message
            data = await websocket.receive_text()
            
            try:
                # Parse the message
                message = json.loads(data)
                
                # Handle subscription
                if message.get("action") == "subscribe" and "job_id" in message:
                    job_id = message["job_id"]
                    
                    # Initialize subscription set if needed
                    if job_id not in job_subscriptions:
                        job_subscriptions[job_id] = set()
                    
                    # Add connection to subscription
                    job_subscriptions[job_id].add(connection_id)
                    logger.info(f"Connection {connection_id} subscribed to job {job_id}")
                    
                    # Send confirmation
                    await websocket.send_text(json.dumps({
                        "action": "subscribed",
                        "job_id": job_id
                    }))
                
                # Handle unsubscription
                elif message.get("action") == "unsubscribe" and "job_id" in message:
                    job_id = message["job_id"]
                    
                    # Remove connection from subscription
                    if job_id in job_subscriptions and connection_id in job_subscriptions[job_id]:
                        job_subscriptions[job_id].remove(connection_id)
                        logger.info(f"Connection {connection_id} unsubscribed from job {job_id}")
                    
                    # Send confirmation
                    await websocket.send_text(json.dumps({
                        "action": "unsubscribed",
                        "job_id": job_id
                    }))
            
            except json.JSONDecodeError:
                logger.error(f"Invalid WebSocket message: {data}")
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Clean up connection
        if connection_id in active_connections:
            del active_connections[connection_id]
        
        # Remove from all subscriptions
        for job_id in list(job_subscriptions.keys()):
            if connection_id in job_subscriptions[job_id]:
                job_subscriptions[job_id].remove(connection_id)
                
                # Remove empty subscription sets
                if not job_subscriptions[job_id]:
                    del job_subscriptions[job_id]


async def broadcast_job_update(job_id: str, data: Dict[str, Any]):
    """
    Broadcast a job update to all subscribed connections.
    
    Args:
        job_id: The ID of the job
        data: The update data
    """
    if job_id not in job_subscriptions:
        return
    
    # Prepare message
    message = json.dumps({
        "job_id": job_id,
        **data
    })
    
    # Get connections subscribed to this job
    connections = [
        active_connections[conn_id]
        for conn_id in job_subscriptions[job_id]
        if conn_id in active_connections
    ]
    
    # Send message to all connections
    for connection in connections:
        try:
            await connection.send_text(message)
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")


def setup_websocket_routes(app: FastAPI):
    """
    Set up WebSocket routes for the FastAPI application.
    
    Args:
        app: The FastAPI application
    """
    app.add_websocket_route("/ws", websocket_endpoint)