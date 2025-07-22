#!/usr/bin/env python
"""
SageMaker Model Validation Script.

This script validates the SageMaker models used in the healthcare image analysis
pipeline by sending test requests to the endpoints and verifying the responses.
"""

import os
import sys
import json
import time
import base64
import argparse
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
import numpy as np
from PIL import Image
import io


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ModelValidator:
    """Validate SageMaker models for the healthcare image analysis pipeline."""
    
    def __init__(self, region: str = None):
        """
        Initialize the model validator.
        
        Args:
            region: AWS region name (defaults to environment variable or 'us-east-1')
        """
        self.region = region or os.environ.get('AWS_REGION', 'us-east-1')
        
        # Initialize AWS clients
        self.sagemaker_runtime = boto3.client('sagemaker-runtime', region_name=self.region)
        self.s3_client = boto3.client('s3', region_name=self.region)
        
        # Load configuration
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, str]:
        """
        Load configuration from environment variables or config file.
        
        Returns:
            Dictionary with configuration values
        """
        config = {}
        
        # Try to load from config file
        config_file = os.environ.get('SAGEMAKER_CONFIG_FILE', 'config/sagemaker_models_config.env')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        config[key] = value
        
        # Override with environment variables
        for key, value in os.environ.items():
            if key.startswith('SEGMENTATION_') or key.startswith('VLM_'):
                config[key] = value
        
        return config
    
    def _load_test_image(self, image_path: str) -> bytes:
        """
        Load a test image from a file or S3.
        
        Args:
            image_path: Path to the test image (local file path or S3 URI)
            
        Returns:
            Binary data of the image
        """
        if image_path.startswith('s3://'):
            # Parse S3 URI
            bucket_name = image_path.split('/')[2]
            key = '/'.join(image_path.split('/')[3:])
            
            # Download from S3
            try:
                response = self.s3_client.get_object(Bucket=bucket_name, Key=key)
                return response['Body'].read()
            except ClientError as e:
                logger.error(f"Error downloading image from S3: {e}")
                raise
        else:
            # Load from local file
            with open(image_path, 'rb') as f:
                return f.read()
    
    def validate_segmentation_model(self, test_image_path: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate the MRI segmentation model.
        
        Args:
            test_image_path: Path to a test MRI image
            
        Returns:
            Tuple of (success, results)
        """
        endpoint_name = self.config.get('SEGMENTATION_ENDPOINT_NAME', 'mri-segmentation-endpoint')
        
        try:
            # Load test image
            logger.info(f"Loading test image from {test_image_path}")
            image_data = self._load_test_image(test_image_path)
            
            # Invoke endpoint
            logger.info(f"Invoking segmentation endpoint: {endpoint_name}")
            start_time = time.time()
            
            response = self.sagemaker_runtime.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType="application/octet-stream",
                Body=image_data,
                Accept="application/json"
            )
            
            processing_time = time.time() - start_time
            logger.info(f"Segmentation completed in {processing_time:.2f} seconds")
            
            # Parse response
            response_body = json.loads(response['Body'].read().decode('utf-8'))
            
            # Validate response structure
            if 'segmentation_data' not in response_body:
                logger.error("Missing 'segmentation_data' in response")
                return False, {
                    'error': "Invalid response format: missing 'segmentation_data'",
                    'response': response_body
                }
            
            if 'confidence_score' not in response_body:
                logger.warning("Missing 'confidence_score' in response")
            
            # Check confidence score if available
            confidence_score = response_body.get('confidence_score', 0.0)
            if confidence_score < 0.7:
                logger.warning(f"Low confidence score: {confidence_score}")
            
            return True, {
                'success': True,
                'processing_time': processing_time,
                'confidence_score': confidence_score,
                'response_size': len(response_body.get('segmentation_data', '')),
                'endpoint': endpoint_name
            }
            
        except ClientError as e:
            logger.error(f"Error invoking segmentation endpoint: {e}")
            return False, {
                'success': False,
                'error': str(e),
                'endpoint': endpoint_name
            }
        except Exception as e:
            logger.error(f"Unexpected error validating segmentation model: {e}")
            return False, {
                'success': False,
                'error': str(e),
                'endpoint': endpoint_name
            }
    
    def validate_vlm_model(self, test_image_path: str, prompt: str = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate the VLM image-to-text model.
        
        Args:
            test_image_path: Path to a test image
            prompt: Optional prompt for the VLM model
            
        Returns:
            Tuple of (success, results)
        """
        endpoint_name = self.config.get('VLM_ENDPOINT_NAME', 'huggingface-vlm-endpoint')
        default_prompt = "Describe the medical findings in this MRI image in detail."
        prompt = prompt or default_prompt
        
        try:
            # Load test image
            logger.info(f"Loading test image from {test_image_path}")
            image_data = self._load_test_image(test_image_path)
            
            # Prepare payload
            payload = {
                "image": base64.b64encode(image_data).decode('utf-8'),
                "prompt": prompt
            }
            
            # Invoke endpoint
            logger.info(f"Invoking VLM endpoint: {endpoint_name}")
            start_time = time.time()
            
            response = self.sagemaker_runtime.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType="application/json",
                Body=json.dumps(payload),
                Accept="application/json"
            )
            
            processing_time = time.time() - start_time
            logger.info(f"VLM processing completed in {processing_time:.2f} seconds")
            
            # Parse response
            response_body = json.loads(response['Body'].read().decode('utf-8'))
            
            # Validate response structure
            if 'text_description' not in response_body:
                logger.error("Missing 'text_description' in response")
                return False, {
                    'error': "Invalid response format: missing 'text_description'",
                    'response': response_body
                }
            
            # Check text description
            text_description = response_body.get('text_description', '')
            if len(text_description) < 50:
                logger.warning(f"Short text description: {len(text_description)} characters")
            
            # Check confidence score if available
            confidence_score = response_body.get('confidence_score', 0.0)
            if confidence_score < 0.7:
                logger.warning(f"Low confidence score: {confidence_score}")
            
            return True, {
                'success': True,
                'processing_time': processing_time,
                'confidence_score': confidence_score,
                'text_description': text_description,
                'text_length': len(text_description),
                'endpoint': endpoint_name
            }
            
        except ClientError as e:
            logger.error(f"Error invoking VLM endpoint: {e}")
            return False, {
                'success': False,
                'error': str(e),
                'endpoint': endpoint_name
            }
        except Exception as e:
            logger.error(f"Unexpected error validating VLM model: {e}")
            return False, {
                'success': False,
                'error': str(e),
                'endpoint': endpoint_name
            }
    
    def validate_all_models(self, segmentation_image_path: str, vlm_image_path: str = None) -> Dict[str, Any]:
        """
        Validate all models in the pipeline.
        
        Args:
            segmentation_image_path: Path to a test MRI image for segmentation
            vlm_image_path: Path to a test image for VLM (defaults to segmentation_image_path)
            
        Returns:
            Dictionary with validation results
        """
        results = {}
        
        # Validate segmentation model
        seg_success, seg_results = self.validate_segmentation_model(segmentation_image_path)
        results['segmentation'] = seg_results
        
        # Validate VLM model
        vlm_image_path = vlm_image_path or segmentation_image_path
        vlm_success, vlm_results = self.validate_vlm_model(vlm_image_path)
        results['vlm'] = vlm_results
        
        # Overall success
        results['overall_success'] = seg_success and vlm_success
        
        return results


def main():
    """Main function to run the model validator."""
    parser = argparse.ArgumentParser(description='Validate SageMaker models')
    parser.add_argument('--region', help='AWS region name')
    parser.add_argument('--segmentation-image', required=True, help='Path to test MRI image for segmentation')
    parser.add_argument('--vlm-image', help='Path to test image for VLM (defaults to segmentation image)')
    parser.add_argument('--output', help='Output file for validation results (JSON format)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    validator = ModelValidator(region=args.region)
    
    results = validator.validate_all_models(
        segmentation_image_path=args.segmentation_image,
        vlm_image_path=args.vlm_image
    )
    
    # Print summary
    print("\nModel Validation Summary:")
    print("========================")
    print(f"Overall Success: {results['overall_success']}")
    
    print("\nSegmentation Model:")
    if results['segmentation'].get('success', False):
        print(f"  Status: Success")
        print(f"  Processing Time: {results['segmentation'].get('processing_time', 0):.2f} seconds")
        print(f"  Confidence Score: {results['segmentation'].get('confidence_score', 0):.4f}")
    else:
        print(f"  Status: Failed")
        print(f"  Error: {results['segmentation'].get('error', 'Unknown error')}")
    
    print("\nVLM Model:")
    if results['vlm'].get('success', False):
        print(f"  Status: Success")
        print(f"  Processing Time: {results['vlm'].get('processing_time', 0):.2f} seconds")
        print(f"  Confidence Score: {results['vlm'].get('confidence_score', 0):.4f}")
        print(f"  Text Length: {results['vlm'].get('text_length', 0)} characters")
        print(f"  Text Sample: {results['vlm'].get('text_description', '')[:100]}...")
    else:
        print(f"  Status: Failed")
        print(f"  Error: {results['vlm'].get('error', 'Unknown error')}")
    
    # Write results to output file if specified
    if args.output:
        try:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"\nResults written to {args.output}")
        except Exception as e:
            logger.error(f"Error writing results to {args.output}: {e}")
    
    # Return non-zero exit code if validation failed
    return 0 if results['overall_success'] else 1


if __name__ == '__main__':
    sys.exit(main())