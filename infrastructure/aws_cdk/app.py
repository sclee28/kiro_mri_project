#!/usr/bin/env python3
"""
AWS CDK App for Healthcare Image Analysis System
"""
import os
from aws_cdk import App, Environment
from healthcare_image_analysis_stack import HealthcareImageAnalysisStack

app = App()

# Get environment configuration
account = os.environ.get('CDK_DEFAULT_ACCOUNT')
region = os.environ.get('CDK_DEFAULT_REGION', 'us-east-1')

env = Environment(account=account, region=region)

# Create the main stack
HealthcareImageAnalysisStack(
    app, 
    "HealthcareImageAnalysisStack",
    env=env,
    description="Healthcare Image Analysis System with MRI processing pipeline"
)

app.synth()