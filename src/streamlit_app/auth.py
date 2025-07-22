"""
Authentication module for the Streamlit application.

This module provides functions for user authentication, session management,
and access control.
"""

import os
import logging
import hashlib
import hmac
import streamlit as st
from functools import wraps

# Configure logging
logger = logging.getLogger(__name__)

# Demo users (in a real application, this would be stored in a database)
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


def hash_password(password):
    """
    Hash a password using SHA-256.
    
    Args:
        password: The password to hash
        
    Returns:
        str: The hashed password
    """
    return hashlib.sha256(password.encode()).hexdigest()


def authenticate_user(username, password):
    """
    Authenticate a user with username and password.
    
    Args:
        username: The username
        password: The password
        
    Returns:
        bool: True if authentication is successful, False otherwise
    """
    if username in DEMO_USERS:
        stored_hash = DEMO_USERS[username]["password_hash"]
        provided_hash = hash_password(password)
        
        if hmac.compare_digest(stored_hash, provided_hash):
            logger.info(f"User {username} authenticated successfully")
            return True
    
    logger.warning(f"Failed authentication attempt for user {username}")
    return False


def login_required(func):
    """
    Decorator to require login for a function.
    
    Args:
        func: The function to decorate
        
    Returns:
        function: The decorated function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not st.session_state.get("authenticated", False):
            st.error("Please log in to access this page")
            st.stop()
        return func(*args, **kwargs)
    return wrapper


def logout_user():
    """Log out the current user by clearing session state."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    
    # Re-initialize authentication state
    st.session_state.authenticated = False
    st.session_state.user_id = None
    st.session_state.username = None
    
    logger.info("User logged out")


def get_current_user():
    """
    Get the current authenticated user.
    
    Returns:
        dict: User information or None if not authenticated
    """
    if not st.session_state.get("authenticated", False):
        return None
    
    username = st.session_state.get("username")
    if username and username in DEMO_USERS:
        return {
            "username": username,
            "name": DEMO_USERS[username]["name"],
            "role": DEMO_USERS[username]["role"]
        }
    
    return None