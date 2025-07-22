# Healthcare Image Analysis System

AI-powered healthcare image analysis system for processing MRI images through a multi-stage pipeline using AWS services.

## Project Structure

```
├── src/
│   ├── lambda_functions/          # AWS Lambda functions
│   │   ├── segmentation_trigger/  # MRI segmentation trigger
│   │   ├── vlm_processing/        # Vision-Language Model processing
│   │   ├── llm_rag_enhancement/   # LLM with RAG enhancement
│   │   ├── results_storage/       # Results storage handler
│   │   └── s3_event_handler/      # S3 event processing
│   ├── streamlit_app/             # Frontend Streamlit application
│   └── shared/                    # Shared utilities and models
│       ├── models/                # Data models and schemas
│       └── utils/                 # Utility functions
├── infrastructure/                # Infrastructure as Code
│   └── aws_cdk/                  # AWS CDK definitions
├── config/                       # Environment configurations
└── requirements.txt              # Python dependencies
```

## Setup

### Prerequisites
- Python 3.11+
- AWS CLI configured
- Node.js (for AWS CDK)

### Installation

1. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install development dependencies:
```bash
pip install -e ".[dev]"
```

### Infrastructure Setup

1. Install CDK dependencies:
```bash
cd infrastructure
pip install -r requirements.txt
```

2. Deploy infrastructure:
```bash
cd aws_cdk
cdk deploy
```

## Development

### Running the Streamlit App
```bash
cd src/streamlit_app
streamlit run app.py
```

### Testing
```bash
pytest
```

### Code Formatting
```bash
black src/
flake8 src/
```

## Environment Configuration

Copy the appropriate environment file and configure your settings:
- `config/development.env` - Development environment
- `config/production.env` - Production environment

## Architecture

The system processes MRI images through the following pipeline:
1. Image upload via Streamlit interface
2. S3 event triggers processing pipeline
3. Step Functions orchestrates multi-stage AI processing
4. Results stored in RDS and displayed to users

For detailed architecture information, see the design document in `.kiro/specs/healthcare-image-analysis/design.md`.