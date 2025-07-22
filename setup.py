"""
Setup script for Healthcare Image Analysis System
"""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="healthcare-image-analysis",
    version="0.1.0",
    author="Healthcare Analysis Team",
    description="AI-powered healthcare image analysis system for MRI processing",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Healthcare Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.11",
    install_requires=[
        "boto3>=1.34.0",
        "botocore>=1.34.0",
        "streamlit>=1.28.0",
        "fastapi>=0.104.0",
        "uvicorn>=0.24.0",
        "sqlalchemy>=2.0.0",
        "psycopg2-binary>=2.9.0",
        "opensearch-py>=2.4.0",
        "pydantic>=2.5.0",
        "python-multipart>=0.0.6",
        "websockets>=12.0",
        "pillow>=10.1.0",
        "numpy>=1.24.0",
        "pandas>=2.1.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.7.0",
        ],
        "infrastructure": [
            "aws-cdk-lib>=2.110.0",
            "constructs>=10.3.0",
        ]
    }
)