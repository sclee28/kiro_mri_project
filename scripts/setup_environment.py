#!/usr/bin/env python3
"""
Environment setup script for Healthcare Image Analysis System
"""
import os
import subprocess
import sys
from pathlib import Path


def run_command(command, cwd=None):
    """Run a shell command and return the result"""
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            check=True, 
            capture_output=True, 
            text=True,
            cwd=cwd
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command '{command}': {e.stderr}")
        return None


def setup_virtual_environment():
    """Set up Python virtual environment"""
    print("Setting up Python virtual environment...")
    
    # Create virtual environment
    if not os.path.exists("venv"):
        run_command(f"{sys.executable} -m venv venv")
        print("✓ Virtual environment created")
    else:
        print("✓ Virtual environment already exists")
    
    # Determine activation script path
    if os.name == 'nt':  # Windows
        activate_script = "venv\\Scripts\\activate"
        pip_path = "venv\\Scripts\\pip"
    else:  # Unix/Linux/macOS
        activate_script = "venv/bin/activate"
        pip_path = "venv/bin/pip"
    
    print(f"To activate the virtual environment, run: {activate_script}")
    return pip_path


def install_dependencies(pip_path):
    """Install Python dependencies"""
    print("Installing Python dependencies...")
    
    # Install main dependencies
    result = run_command(f"{pip_path} install -r requirements.txt")
    if result is not None:
        print("✓ Main dependencies installed")
    
    # Install development dependencies
    result = run_command(f"{pip_path} install -e .[dev]")
    if result is not None:
        print("✓ Development dependencies installed")


def setup_infrastructure_dependencies():
    """Set up infrastructure dependencies"""
    print("Setting up infrastructure dependencies...")
    
    # Check if Node.js is installed (required for CDK)
    node_version = run_command("node --version")
    if node_version:
        print(f"✓ Node.js found: {node_version}")
    else:
        print("⚠ Node.js not found. Please install Node.js for AWS CDK support")
    
    # Install CDK if Node.js is available
    if node_version:
        cdk_version = run_command("cdk --version")
        if not cdk_version:
            print("Installing AWS CDK...")
            run_command("npm install -g aws-cdk")
            print("✓ AWS CDK installed")
        else:
            print(f"✓ AWS CDK found: {cdk_version}")


def create_env_file():
    """Create local environment file from template"""
    env_file = ".env"
    template_file = "config/development.env"
    
    if not os.path.exists(env_file) and os.path.exists(template_file):
        print("Creating local environment file...")
        with open(template_file, 'r') as src, open(env_file, 'w') as dst:
            dst.write(src.read())
        print("✓ Environment file created (.env)")
        print("Please update .env with your specific configuration values")
    else:
        print("✓ Environment file already exists or template not found")


def main():
    """Main setup function"""
    print("Healthcare Image Analysis System - Environment Setup")
    print("=" * 55)
    
    # Change to project root directory
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Setup steps
    pip_path = setup_virtual_environment()
    install_dependencies(pip_path)
    setup_infrastructure_dependencies()
    create_env_file()
    
    print("\n" + "=" * 55)
    print("Setup completed successfully!")
    print("\nNext steps:")
    print("1. Activate the virtual environment")
    print("2. Configure your .env file with AWS credentials and settings")
    print("3. Run 'aws configure' to set up AWS CLI")
    print("4. Deploy infrastructure with 'cd infrastructure/aws_cdk && cdk deploy'")
    print("5. Start the Streamlit app with 'cd src/streamlit_app && streamlit run app.py'")


if __name__ == "__main__":
    main()