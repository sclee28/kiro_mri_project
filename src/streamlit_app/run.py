"""
Run script for starting both the Streamlit app and API server.

This script starts both the Streamlit application and the FastAPI server
in separate processes.
"""

import os
import sys
import subprocess
import time
import signal
import logging
from multiprocessing import Process

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_streamlit():
    """Run the Streamlit application."""
    logger.info("Starting Streamlit application...")
    
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Run streamlit
    cmd = [
        "streamlit", "run", 
        os.path.join(script_dir, "app.py"),
        "--server.port", os.getenv("STREAMLIT_PORT", "8501"),
        "--server.address", os.getenv("STREAMLIT_HOST", "0.0.0.0")
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Log output
    for line in process.stdout:
        logger.info(f"Streamlit: {line.strip()}")
    
    process.wait()
    logger.info(f"Streamlit process exited with code {process.returncode}")


def run_api_server():
    """Run the FastAPI server."""
    logger.info("Starting API server...")
    
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Run uvicorn
    cmd = [
        "python", 
        os.path.join(script_dir, "api_server.py")
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Log output
    for line in process.stdout:
        logger.info(f"API Server: {line.strip()}")
    
    process.wait()
    logger.info(f"API server process exited with code {process.returncode}")


def main():
    """Main entry point."""
    logger.info("Starting Healthcare Image Analysis application...")
    
    # Start processes
    streamlit_process = Process(target=run_streamlit)
    api_process = Process(target=run_api_server)
    
    streamlit_process.start()
    api_process.start()
    
    # Handle termination signals
    def signal_handler(sig, frame):
        logger.info("Received termination signal. Shutting down...")
        streamlit_process.terminate()
        api_process.terminate()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Wait for processes to complete
        streamlit_process.join()
        api_process.join()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
        streamlit_process.terminate()
        api_process.terminate()
    
    logger.info("Application shutdown complete.")


if __name__ == "__main__":
    main()