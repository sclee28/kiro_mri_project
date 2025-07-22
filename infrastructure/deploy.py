#!/usr/bin/env python3
"""
Deployment script for Healthcare Image Analysis CDK Stack
"""

import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import aws_cdk as cdk
from aws_cdk.healthcare_image_analysis_stack import HealthcareImageAnalysisStack


def main():
    """Main deployment function"""
    app = cdk.App()
    
    # Get environment variables
    account = os.environ.get('CDK_DEFAULT_ACCOUNT')
    region = os.environ.get('CDK_DEFAULT_REGION', 'us-east-1')
    
    if not account:
        print("Error: CDK_DEFAULT_ACCOUNT environment variable not set")
        sys.exit(1)
    
    # Create the stack
    HealthcareImageAnalysisStack(
        app, 
        "HealthcareImageAnalysisStack",
        env=cdk.Environment(account=account, region=region),
        description="Healthcare Image Analysis System with S3, SQS, Lambda, and RDS"
    )
    
    app.synth()


if __name__ == "__main__":
    main()