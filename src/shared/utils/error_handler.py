"""
Error handling utilities for Lambda functions.

This module provides centralized error handling, retry logic, and logging
for the healthcare image analysis system.
"""

import logging
import time
import functools
from typing import Any, Callable, Dict, List, Optional, Type, Union
from dataclasses import dataclass
from enum import Enum

import boto3
from botocore.exceptions import ClientError, BotoCoreError


logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """Classification of error types for different handling strategies"""
    TRANSIENT = "transient"  # Temporary errors that can be retried
    PERMANENT = "permanent"  # Permanent errors that should not be retried
    THROTTLING = "throttling"  # Rate limiting errors
    AUTHENTICATION = "authentication"  # Auth/permission errors
    VALIDATION = "validation"  # Input validation errors


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True


@dataclass
class ErrorContext:
    """Context information for error handling"""
    function_name: str
    operation: str
    resource_id: Optional[str] = None
    user_id: Optional[str] = None
    additional_context: Optional[Dict[str, Any]] = None


class RetryableError(Exception):
    """Exception that indicates an operation should be retried"""
    def __init__(self, message: str, error_type: ErrorType = ErrorType.TRANSIENT):
        super().__init__(message)
        self.error_type = error_type


class PermanentError(Exception):
    """Exception that indicates an operation should not be retried"""
    def __init__(self, message: str, error_type: ErrorType = ErrorType.PERMANENT):
        super().__init__(message)
        self.error_type = error_type


def classify_aws_error(error: Union[ClientError, BotoCoreError]) -> ErrorType:
    """
    Classify AWS errors to determine retry strategy
    
    Args:
        error: AWS SDK error
        
    Returns:
        ErrorType classification
    """
    if isinstance(error, ClientError):
        error_code = error.response.get('Error', {}).get('Code', '')
        
        # Throttling errors
        if error_code in ['Throttling', 'ThrottlingException', 'RequestLimitExceeded']:
            return ErrorType.THROTTLING
        
        # Authentication/authorization errors
        if error_code in ['AccessDenied', 'UnauthorizedOperation', 'InvalidUserID.NotFound']:
            return ErrorType.AUTHENTICATION
        
        # Validation errors
        if error_code in ['ValidationException', 'InvalidParameterValue', 'MalformedInput']:
            return ErrorType.VALIDATION
        
        # Transient errors
        if error_code in ['ServiceUnavailable', 'InternalError', 'RequestTimeout']:
            return ErrorType.TRANSIENT
        
        # HTTP status code based classification
        status_code = error.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0)
        if status_code >= 500:
            return ErrorType.TRANSIENT
        elif status_code in [400, 403, 404]:
            return ErrorType.PERMANENT
        elif status_code == 429:
            return ErrorType.THROTTLING
    
    # Default to transient for BotoCoreError and unknown errors
    return ErrorType.TRANSIENT


def exponential_backoff(attempt: int, config: RetryConfig) -> float:
    """
    Calculate exponential backoff delay
    
    Args:
        attempt: Current attempt number (0-based)
        config: Retry configuration
        
    Returns:
        Delay in seconds
    """
    delay = config.initial_delay * (config.backoff_multiplier ** attempt)
    delay = min(delay, config.max_delay)
    
    if config.jitter:
        import random
        delay *= (0.5 + random.random() * 0.5)  # Add 0-50% jitter
    
    return delay


def retry_with_backoff(
    config: RetryConfig = None,
    retryable_exceptions: tuple = (RetryableError, ClientError, BotoCoreError),
    permanent_exceptions: tuple = (PermanentError,)
):
    """
    Decorator for adding retry logic with exponential backoff
    
    Args:
        config: Retry configuration
        retryable_exceptions: Exceptions that should trigger retries
        permanent_exceptions: Exceptions that should not be retried
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except permanent_exceptions as e:
                    logger.error(f"Permanent error in {func.__name__}: {e}")
                    raise
                    
                except retryable_exceptions as e:
                    last_exception = e
                    
                    # Classify AWS errors
                    if isinstance(e, (ClientError, BotoCoreError)):
                        error_type = classify_aws_error(e)
                        if error_type in [ErrorType.PERMANENT, ErrorType.AUTHENTICATION, ErrorType.VALIDATION]:
                            logger.error(f"Non-retryable AWS error in {func.__name__}: {e}")
                            raise PermanentError(f"AWS error: {e}") from e
                    
                    if attempt < config.max_attempts - 1:
                        delay = exponential_backoff(attempt, config)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.2f} seconds..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {config.max_attempts} attempts failed for {func.__name__}")
                        
                except Exception as e:
                    logger.error(f"Unexpected error in {func.__name__}: {e}")
                    raise
            
            # If we get here, all retries failed
            raise last_exception
            
        return wrapper
    return decorator


class ErrorHandler:
    """Centralized error handler for Lambda functions"""
    
    def __init__(self, context: ErrorContext):
        self.context = context
        self.logger = logging.getLogger(f"{__name__}.{context.function_name}")
    
    def handle_error(self, error: Exception, operation: str = None) -> Dict[str, Any]:
        """
        Handle and log errors with appropriate context
        
        Args:
            error: The exception that occurred
            operation: Optional operation description
            
        Returns:
            Error response dictionary
        """
        operation = operation or self.context.operation
        
        error_info = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'function_name': self.context.function_name,
            'operation': operation,
            'resource_id': self.context.resource_id,
            'user_id': self.context.user_id
        }
        
        if self.context.additional_context:
            error_info.update(self.context.additional_context)
        
        # Log error with appropriate level
        if isinstance(error, (RetryableError, ClientError, BotoCoreError)):
            error_type = classify_aws_error(error) if isinstance(error, (ClientError, BotoCoreError)) else error.error_type
            
            if error_type == ErrorType.TRANSIENT:
                self.logger.warning(f"Transient error in {operation}: {error}")
            elif error_type == ErrorType.THROTTLING:
                self.logger.warning(f"Throttling error in {operation}: {error}")
            else:
                self.logger.error(f"Error in {operation}: {error}")
        else:
            self.logger.error(f"Unexpected error in {operation}: {error}")
        
        return error_info
    
    def create_lambda_response(self, error: Exception, status_code: int = 500) -> Dict[str, Any]:
        """
        Create a standardized Lambda error response
        
        Args:
            error: The exception that occurred
            status_code: HTTP status code
            
        Returns:
            Lambda response dictionary
        """
        error_info = self.handle_error(error)
        
        return {
            'statusCode': status_code,
            'headers': {
                'Content-Type': 'application/json',
                'X-Error-Type': error_info['error_type']
            },
            'body': {
                'error': error_info['error_message'],
                'error_type': error_info['error_type'],
                'function_name': error_info['function_name'],
                'operation': error_info['operation']
            }
        }


def handle_lambda_errors(context: ErrorContext):
    """
    Decorator for Lambda functions to handle errors consistently
    
    Args:
        context: Error context information
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(event, lambda_context):
            error_handler = ErrorHandler(context)
            
            try:
                return func(event, lambda_context)
            except Exception as e:
                return error_handler.create_lambda_response(e)
                
        return wrapper
    return decorator


# Convenience functions for common AWS operations
@retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
def safe_s3_operation(operation: Callable, *args, **kwargs):
    """Safely execute S3 operations with retry logic"""
    return operation(*args, **kwargs)


@retry_with_backoff(RetryConfig(max_attempts=5, initial_delay=0.5, max_delay=30.0))
def safe_sqs_operation(operation: Callable, *args, **kwargs):
    """Safely execute SQS operations with retry logic"""
    return operation(*args, **kwargs)


@retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=2.0))
def safe_rds_operation(operation: Callable, *args, **kwargs):
    """Safely execute RDS operations with retry logic"""
    return operation(*args, **kwargs)