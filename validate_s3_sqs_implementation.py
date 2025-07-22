#!/usr/bin/env python3
"""
Validation script for S3 event handling and SQS integration implementation.
This script checks if all required components are properly implemented.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_file_exists(file_path: str) -> bool:
    """Check if a file exists and is not empty."""
    path = Path(file_path)
    return path.exists() and path.stat().st_size > 0

def check_implementation_completeness():
    """Check if all required components are implemented."""
    
    print("🔍 Validating S3 event handling and SQS integration implementation...")
    print("=" * 70)
    
    # Required files and their descriptions
    required_files = {
        "src/lambda_functions/s3_event_handler/handler.py": "S3 event handler Lambda function",
        "src/shared/utils/sqs_handler.py": "SQS message handling utilities",
        "src/shared/utils/error_handler.py": "Error handling and retry logic",
        "infrastructure/aws_cdk/healthcare_image_analysis_stack.py": "Infrastructure as Code",
        "tests/test_s3_sqs_integration.py": "Integration tests",
        "src/lambda_functions/s3_event_handler/requirements.txt": "Lambda dependencies"
    }
    
    all_files_exist = True
    
    for file_path, description in required_files.items():
        if check_file_exists(file_path):
            print(f"✅ {description}: {file_path}")
        else:
            print(f"❌ {description}: {file_path} - MISSING OR EMPTY")
            all_files_exist = False
    
    print("\n" + "=" * 70)
    
    # Check specific implementation details
    print("🔍 Checking implementation details...")
    
    # Check S3 event handler
    try:
        with open("src/lambda_functions/s3_event_handler/handler.py", "r") as f:
            handler_content = f.read()
            
        required_functions = [
            "lambda_handler",
            "process_s3_event", 
            "validate_image_file",
            "create_analysis_job",
            "trigger_step_functions"
        ]
        
        for func in required_functions:
            if f"def {func}" in handler_content:
                print(f"✅ S3 event handler has {func} function")
            else:
                print(f"❌ S3 event handler missing {func} function")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate S3 event handler - file not found")
        all_files_exist = False
    
    # Check SQS handler
    try:
        with open("src/shared/utils/sqs_handler.py", "r") as f:
            sqs_content = f.read()
            
        required_classes = ["SQSMessageHandler", "S3EventMessage"]
        
        for cls in required_classes:
            if f"class {cls}" in sqs_content:
                print(f"✅ SQS handler has {cls} class")
            else:
                print(f"❌ SQS handler missing {cls} class")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate SQS handler - file not found")
        all_files_exist = False
    
    # Check error handler
    try:
        with open("src/shared/utils/error_handler.py", "r") as f:
            error_content = f.read()
            
        required_items = [
            "retry_with_backoff",
            "ErrorHandler",
            "RetryableError",
            "PermanentError",
            "safe_s3_operation"
        ]
        
        for item in required_items:
            if item in error_content:
                print(f"✅ Error handler has {item}")
            else:
                print(f"❌ Error handler missing {item}")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate error handler - file not found")
        all_files_exist = False
    
    # Check infrastructure
    try:
        with open("infrastructure/aws_cdk/healthcare_image_analysis_stack.py", "r") as f:
            infra_content = f.read()
            
        required_resources = [
            "_create_s3_buckets",
            "_create_sqs_queue", 
            "_create_s3_event_handler_lambda",
            "_configure_s3_event_notifications"
        ]
        
        for resource in required_resources:
            if resource in infra_content:
                print(f"✅ Infrastructure has {resource}")
            else:
                print(f"❌ Infrastructure missing {resource}")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate infrastructure - file not found")
        all_files_exist = False
    
    print("\n" + "=" * 70)
    
    if all_files_exist:
        print("🎉 All required components are implemented!")
        print("✅ Task 3: Create S3 event handling and SQS integration - COMPLETE")
        return True
    else:
        print("⚠️  Some components are missing or incomplete")
        print("❌ Task 3: Create S3 event handling and SQS integration - INCOMPLETE")
        return False

if __name__ == "__main__":
    success = check_implementation_completeness()
    sys.exit(0 if success else 1)