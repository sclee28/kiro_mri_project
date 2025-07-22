FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose ports for Streamlit and API
EXPOSE 8501
EXPOSE 8000

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV API_PORT=8000
ENV API_HOST=0.0.0.0

# Run the application
CMD ["python", "run.py"]