# Healthcare Image Analysis - Streamlit Frontend

This directory contains the Streamlit frontend application for the Healthcare Image Analysis system. The application provides a user interface for uploading MRI images, tracking processing status, and viewing analysis results.

## Features

- User authentication and session management
- MRI image upload interface
- Job status tracking and progress display
- Results visualization with interactive charts
- Report generation and download

## Directory Structure

```
streamlit_app/
├── app.py                 # Main Streamlit application
├── api_client.py          # Client for interacting with backend API
├── api_server.py          # FastAPI server for backend services
├── auth.py                # Authentication and session management
├── config.py              # Configuration management
├── Dockerfile             # Docker configuration
├── file_utils.py          # Utilities for file operations
├── requirements.txt       # Python dependencies
├── run.py                 # Script to run both Streamlit and API server
├── test_app.py            # Tests for the application
├── visualizations.py      # Visualization utilities
└── websocket_client.py    # Client for real-time updates
```

## Running the Application

### Local Development

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the application:
   ```
   python run.py
   ```

3. Access the application at http://localhost:8501

### Docker

1. Build the Docker image:
   ```
   docker build -t healthcare-streamlit .
   ```

2. Run the container:
   ```
   docker run -p 8501:8501 -p 8000:8000 healthcare-streamlit
   ```

3. Access the application at http://localhost:8501

## Configuration

The application can be configured using environment variables:

- `API_BASE_URL`: URL of the backend API (default: "simulated")
- `AWS_REGION`: AWS region (default: "us-east-1")
- `AWS_ACCESS_KEY_ID`: AWS access key ID
- `AWS_SECRET_ACCESS_KEY`: AWS secret access key
- `S3_BUCKET_NAME`: S3 bucket for storing images (default: "healthcare-mri-images")
- `STREAMLIT_PORT`: Port for Streamlit server (default: 8501)
- `API_PORT`: Port for API server (default: 8000)
- `DEBUG_MODE`: Enable debug mode (default: false)
- `LOG_LEVEL`: Logging level (default: INFO)

## Testing

Run the tests using:

```
pytest test_app.py
```

## API Documentation

When running the application, API documentation is available at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc