"""
Configuration module for the Streamlit application.

This module loads configuration from environment variables and provides
a configuration object for the application.
"""

import os
from dataclasses import dataclass
from typing import Optional
import logging
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Configuration class for the Streamlit application."""
    
    # API configuration
    api_base_url: str = os.getenv("API_BASE_URL", "simulated")
    
    # AWS configuration
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME", "healthcare-mri-images")
    
    # Database configuration
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "healthcare_analysis")
    db_username: str = os.getenv("DB_USERNAME", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "")
    
    # Application configuration
    debug_mode: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        # Set up logging based on configuration
        numeric_level = getattr(logging, self.log_level.upper(), None)
        if not isinstance(numeric_level, int):
            numeric_level = logging.INFO
        logging.basicConfig(level=numeric_level)
        
        # Log configuration (excluding sensitive values)
        if self.debug_mode:
            logger.debug(f"API Base URL: {self.api_base_url}")
            logger.debug(f"AWS Region: {self.aws_region}")
            logger.debug(f"S3 Bucket: {self.s3_bucket_name}")
            logger.debug(f"Database Host: {self.db_host}")
            logger.debug(f"Database Name: {self.db_name}")
            logger.debug(f"Log Level: {self.log_level}")


def load_config() -> AppConfig:
    """
    Load and return the application configuration.
    
    Returns:
        AppConfig: The application configuration
    """
    return AppConfig()