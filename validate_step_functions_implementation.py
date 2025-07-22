#!/usr/bin/env python3
"""
Validation script for Step Functions state machine orchestration implementation.
This script checks if all required components are properly implemented.
"""

import sys
import os
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_file_exists(file_path: str) -> bool:
    """Check if a file exists and is not empty."""
    path = Path(file_path)
    return path.exists() and path.stat().st_size > 0

def validate_state_machine_definition(file_path: str) -> bool:
    """Validate the state machine definition JSON."""
    try:
        with open(file_path, 'r') as f:
            definition = json.load(f)
        
        # Check required top-level properties
        required_props = ['Comment', 'StartAt', 'States', 'TimeoutSeconds', 'TracingConfiguration', 'LoggingConfiguration']
        for prop in required_props:
            if prop not in definition:
                print(f"❌ State machine definition missing required property: {prop}")
                return False
        
        # Check states
        required_states = [
            'SegmentImage', 'ImageToText', 'EnhanceWithLLM', 'StoreResults', 
            'HandleSegmentationError', 'HandleVLMError', 'HandleLLMError', 
            'HandleStorageError', 'NotifySuccess', 'FailExecution'
        ]
        
        for state in required_states:
            if state not in definition['States']:
                print(f"❌ State machine definition missing required state: {state}")
                return False
        
        # Check error handling
        for state_name in ['SegmentImage', 'ImageToText', 'EnhanceWithLLM', 'StoreResults']:
            state = definition['States'][state_name]
            if 'Retry' not in state:
                print(f"❌ State {state_name} missing retry configuration")
                return False
            if 'Catch' not in state:
                print(f"❌ State {state_name} missing catch configuration")
                return False
        
        print("✅ State machine definition is valid")
        return True
        
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Failed to validate state machine definition: {e}")
        return False

def check_implementation_completeness():
    """Check if all required components are implemented."""
    
    print("🔍 Validating Step Functions state machine orchestration implementation...")
    print("=" * 70)
    
    # Required files and their descriptions
    required_files = {
        "infrastructure/aws_cdk/step_functions_stack.py": "Step Functions CDK stack",
        "src/lambda_functions/step_functions_trigger/handler.py": "Step Functions trigger Lambda",
        "src/lambda_functions/step_functions_trigger/state_machine_definition.json": "State machine definition",
        "src/lambda_functions/step_functions_error_handler/handler.py": "Error handler Lambda"
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
    
    # Validate state machine definition
    state_machine_valid = validate_state_machine_definition(
        "src/lambda_functions/step_functions_trigger/state_machine_definition.json"
    )
    all_files_exist = all_files_exist and state_machine_valid
    
    # Check Step Functions stack
    try:
        with open("infrastructure/aws_cdk/step_functions_stack.py", "r") as f:
            stack_content = f.read()
            
        required_methods = [
            "_create_state_machine",
            "_create_error_handler_lambda",
            "_create_step_functions_trigger_lambda"
        ]
        
        for method in required_methods:
            if method in stack_content:
                print(f"✅ Step Functions stack has {method} method")
            else:
                print(f"❌ Step Functions stack missing {method} method")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate Step Functions stack - file not found")
        all_files_exist = False
    
    # Check Step Functions trigger Lambda
    try:
        with open("src/lambda_functions/step_functions_trigger/handler.py", "r") as f:
            trigger_content = f.read()
            
        required_functions = [
            "lambda_handler",
            "start_step_functions_execution",
            "update_job_status"
        ]
        
        for func in required_functions:
            if f"def {func}" in trigger_content:
                print(f"✅ Step Functions trigger Lambda has {func} function")
            else:
                print(f"❌ Step Functions trigger Lambda missing {func} function")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate Step Functions trigger Lambda - file not found")
        all_files_exist = False
    
    # Check error handler Lambda
    try:
        with open("src/lambda_functions/step_functions_error_handler/handler.py", "r") as f:
            error_handler_content = f.read()
            
        required_functions = [
            "lambda_handler",
            "update_job_status",
            "log_error_to_cloudwatch"
        ]
        
        for func in required_functions:
            if f"def {func}" in error_handler_content:
                print(f"✅ Error handler Lambda has {func} function")
            else:
                print(f"❌ Error handler Lambda missing {func} function")
                all_files_exist = False
                
    except FileNotFoundError:
        print("❌ Cannot validate error handler Lambda - file not found")
        all_files_exist = False
    
    print("\n" + "=" * 70)
    
    if all_files_exist:
        print("🎉 All required components are implemented!")
        print("✅ Task 4: Implement Step Functions state machine orchestration - COMPLETE")
        return True
    else:
        print("⚠️  Some components are missing or incomplete")
        print("❌ Task 4: Implement Step Functions state machine orchestration - INCOMPLETE")
        return False

if __name__ == "__main__":
    success = check_implementation_completeness()
    sys.exit(0 if success else 1)