"""
LLM and RAG Enhancement Processing Lambda Function.

This Lambda function integrates OpenSearch for medical knowledge retrieval,
calls Bedrock LLM with RAG context, and generates comprehensive medical reports
with confidence scoring and source reference tracking.
"""

import os
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import boto3
from botocore.exceptions import ClientError
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from src.shared.models.database import AnalysisJob, JobStatus, AnalysisResult
from src.shared.utils.database import db_session_scope
from src.shared.utils.error_handler import (
    ErrorContext, handle_lambda_errors, retry_with_backoff, RetryConfig,
    RetryableError, PermanentError, ErrorType
)

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')

# Environment variables
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
OPENSEARCH_ENDPOINT = os.environ.get("OPENSEARCH_ENDPOINT", "")
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "medical-knowledge")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "healthcare-processed-results")
MODEL_TIMEOUT_SECONDS = int(os.environ.get("MODEL_TIMEOUT_SECONDS", "300"))  # 5 minutes timeout
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.7"))
TOP_K = int(os.environ.get("TOP_K", "5"))  # Number of relevant documents to retrieve


class LLMEnhancementError(Exception):
    """Exception raised for errors in the LLM enhancement process."""
    pass


class OpenSearchClient:
    """Client for interacting with OpenSearch for medical knowledge retrieval."""
    
    def __init__(self, endpoint: str, index: str):
        """
        Initialize the OpenSearch client.
        
        Args:
            endpoint: OpenSearch endpoint URL
            index: OpenSearch index name
        """
        self.endpoint = endpoint
        self.index = index
        self.client = self._create_client()
    
    def _create_client(self) -> OpenSearch:
        """
        Create an OpenSearch client with AWS authentication.
        
        Returns:
            OpenSearch client instance
        """
        if not self.endpoint:
            logger.warning("OpenSearch endpoint not configured, using mock client")
            return None
        
        try:
            region = os.environ.get("AWS_REGION", "us-east-1")
            service = 'es'
            credentials = boto3.Session().get_credentials()
            aws_auth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                region,
                service,
                session_token=credentials.token
            )
            
            client = OpenSearch(
                hosts=[{'host': self.endpoint, 'port': 443}],
                http_auth=aws_auth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=30
            )
            
            logger.info(f"Successfully connected to OpenSearch endpoint: {self.endpoint}")
            return client
            
        except Exception as e:
            logger.error(f"Failed to create OpenSearch client: {e}")
            raise
    
    @retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
    def search_medical_knowledge(self, query: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
        """
        Search for relevant medical knowledge based on the query.
        
        Args:
            query: Search query text
            top_k: Number of top results to return
            
        Returns:
            List of relevant documents with content and metadata
            
        Raises:
            RetryableError: For transient errors that can be retried
            PermanentError: For permanent errors that should not be retried
        """
        if not self.client:
            # Return mock data if no client is available
            logger.warning("Using mock OpenSearch results")
            return self._get_mock_results(query, top_k)
        
        try:
            # Use a combination of match and multi_match queries for better results
            search_body = {
                "size": top_k,
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"content": {"query": query, "boost": 1.0}}},
                            {"multi_match": {
                                "query": query,
                                "fields": ["title^2", "content", "keywords^1.5"],
                                "type": "best_fields",
                                "tie_breaker": 0.3,
                                "boost": 1.5
                            }}
                        ],
                        "minimum_should_match": 1
                    }
                },
                "_source": ["title", "content", "source", "publication_date", "author", "url", "confidence"]
            }
            
            start_time = time.time()
            response = self.client.search(
                body=search_body,
                index=self.index
            )
            search_time = time.time() - start_time
            
            logger.info(f"OpenSearch query completed in {search_time:.2f} seconds")
            
            hits = response.get('hits', {}).get('hits', [])
            results = []
            
            for hit in hits:
                source = hit.get('_source', {})
                score = hit.get('_score', 0.0)
                
                # Normalize score to a 0-1 range (approximate)
                normalized_score = min(score / 10.0, 1.0)
                
                result = {
                    'content': source.get('content', ''),
                    'title': source.get('title', 'Unknown'),
                    'source': source.get('source', 'Unknown'),
                    'publication_date': source.get('publication_date', ''),
                    'author': source.get('author', ''),
                    'url': source.get('url', ''),
                    'relevance_score': normalized_score,
                    'confidence': source.get('confidence', 0.8)
                }
                results.append(result)
            
            logger.info(f"Retrieved {len(results)} relevant documents from OpenSearch")
            return results
            
        except Exception as e:
            logger.error(f"OpenSearch query failed: {e}")
            raise RetryableError(f"OpenSearch query failed: {e}", ErrorType.TRANSIENT)
    
    def _get_mock_results(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """
        Generate mock search results for testing or when OpenSearch is not available.
        
        Args:
            query: Search query text
            top_k: Number of top results to return
            
        Returns:
            List of mock documents
        """
        mock_results = [
            {
                'content': 'MRI segmentation is a critical technique in medical imaging that allows for the identification and isolation of specific anatomical structures or pathological regions. Advanced deep learning models have shown superior performance in segmenting brain MRI images, particularly for detecting abnormalities such as tumors, lesions, and structural changes.',
                'title': 'Advances in MRI Segmentation Techniques',
                'source': 'Journal of Medical Imaging',
                'publication_date': '2023-06-15',
                'author': 'Smith, J. et al.',
                'url': 'https://example.com/journal/mri-segmentation',
                'relevance_score': 0.95,
                'confidence': 0.9
            },
            {
                'content': 'Vision-Language Models (VLMs) have demonstrated remarkable capabilities in medical image interpretation, providing detailed descriptions of radiological findings. These models combine computer vision and natural language processing to generate human-readable reports from medical images, potentially assisting radiologists in diagnosis and reporting.',
                'title': 'Vision-Language Models in Medical Imaging',
                'source': 'Radiology AI Journal',
                'publication_date': '2023-09-22',
                'author': 'Johnson, A. and Williams, B.',
                'url': 'https://example.com/radiology/vlm-applications',
                'relevance_score': 0.87,
                'confidence': 0.85
            },
            {
                'content': 'Retrieval-Augmented Generation (RAG) enhances large language model outputs by incorporating domain-specific knowledge. In medical contexts, RAG systems can access medical literature, clinical guidelines, and case studies to provide evidence-based insights, improving the accuracy and reliability of AI-generated medical reports.',
                'title': 'RAG Systems in Clinical Decision Support',
                'source': 'Healthcare Informatics Review',
                'publication_date': '2024-01-10',
                'author': 'Chen, L. et al.',
                'url': 'https://example.com/healthcare/rag-clinical-applications',
                'relevance_score': 0.82,
                'confidence': 0.88
            }
        ]
        
        # Return a subset based on top_k
        return mock_results[:min(top_k, len(mock_results))]


class BedrockLLMClient:
    """Client for interacting with Amazon Bedrock LLM models."""
    
    def __init__(self, model_id: str):
        """
        Initialize the Bedrock LLM client.
        
        Args:
            model_id: Bedrock model ID
        """
        self.model_id = model_id
        self.client = bedrock_runtime
    
    @retry_with_backoff(RetryConfig(max_attempts=3, initial_delay=1.0))
    def generate_enhanced_report(
        self, 
        image_description: str, 
        rag_context: List[Dict[str, Any]],
        max_tokens: int = MAX_TOKENS,
        temperature: float = TEMPERATURE
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate an enhanced medical report using Bedrock LLM with RAG context.
        
        Args:
            image_description: Text description of the MRI image from VLM
            rag_context: List of relevant medical knowledge documents
            max_tokens: Maximum number of tokens to generate
            temperature: Temperature parameter for text generation
            
        Returns:
            Tuple containing the enhanced report text and metadata
            
        Raises:
            RetryableError: For transient errors that can be retried
            PermanentError: For permanent errors that should not be retried
        """
        try:
            # Format RAG context for the prompt
            formatted_context = self._format_rag_context(rag_context)
            
            # Create the prompt with image description and RAG context
            prompt = self._create_prompt(image_description, formatted_context)
            
            # Prepare request body based on the model
            if self.model_id.startswith("anthropic.claude"):
                request_body = self._prepare_claude_request(prompt, max_tokens, temperature)
            elif self.model_id.startswith("amazon.titan"):
                request_body = self._prepare_titan_request(prompt, max_tokens, temperature)
            else:
                raise PermanentError(f"Unsupported model: {self.model_id}", ErrorType.PERMANENT)
            
            start_time = time.time()
            
            # Invoke Bedrock model
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )
            
            processing_time = time.time() - start_time
            logger.info(f"Bedrock LLM invocation completed in {processing_time:.2f} seconds")
            
            # Parse response based on model
            response_body = json.loads(response.get('body').read())
            
            if self.model_id.startswith("anthropic.claude"):
                report_text = response_body.get('content', [{}])[0].get('text', '')
            elif self.model_id.startswith("amazon.titan"):
                report_text = response_body.get('results', [{}])[0].get('outputText', '')
            else:
                report_text = ""
            
            # Extract metadata
            metadata = {
                'model_id': self.model_id,
                'processing_time_seconds': processing_time,
                'token_count': response_body.get('usage', {}).get('output_tokens', 0),
                'temperature': temperature
            }
            
            return report_text, metadata
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', '')
            
            if error_code in ['ThrottlingException', 'ServiceUnavailable', 'InternalServerException']:
                logger.warning(f"Transient Bedrock error: {error_code} - {error_message}")
                raise RetryableError(f"Bedrock error: {error_message}", ErrorType.TRANSIENT)
            elif error_code == 'ValidationException':
                logger.error(f"Validation error when invoking Bedrock: {error_message}")
                raise PermanentError(f"Invalid input for Bedrock model: {error_message}", ErrorType.VALIDATION)
            else:
                logger.error(f"Bedrock error: {error_code} - {error_message}")
                raise PermanentError(f"Failed to invoke Bedrock: {error_message}", ErrorType.PERMANENT)
                
        except Exception as e:
            logger.error(f"Unexpected error when invoking Bedrock: {e}")
            raise RetryableError(f"Unexpected error: {e}", ErrorType.TRANSIENT)
    
    def _format_rag_context(self, rag_context: List[Dict[str, Any]]) -> str:
        """
        Format RAG context documents into a string for the prompt.
        
        Args:
            rag_context: List of relevant medical knowledge documents
            
        Returns:
            Formatted context string
        """
        if not rag_context:
            return "No relevant medical knowledge found."
        
        formatted_docs = []
        for i, doc in enumerate(rag_context, 1):
            formatted_doc = (
                f"[Document {i}]\n"
                f"Title: {doc.get('title', 'Unknown')}\n"
                f"Source: {doc.get('source', 'Unknown')}"
            )
            
            if doc.get('author'):
                formatted_doc += f" by {doc.get('author')}"
            
            if doc.get('publication_date'):
                formatted_doc += f" ({doc.get('publication_date')})"
            
            formatted_doc += f"\nRelevance Score: {doc.get('relevance_score', 0.0):.2f}\n"
            formatted_doc += f"Content: {doc.get('content', '')}\n"
            
            formatted_docs.append(formatted_doc)
        
        return "\n\n".join(formatted_docs)
    
    def _create_prompt(self, image_description: str, rag_context: str) -> str:
        """
        Create a prompt for the LLM with image description and RAG context.
        
        Args:
            image_description: Text description of the MRI image from VLM
            rag_context: Formatted RAG context string
            
        Returns:
            Complete prompt for the LLM
        """
        prompt = f"""
You are a medical AI assistant specialized in analyzing MRI images. Your task is to generate a comprehensive medical report based on the image description provided by a Vision-Language Model and relevant medical knowledge.

## MRI Image Description:
{image_description}

## Relevant Medical Knowledge:
{rag_context}

## Instructions:
Please generate a detailed medical report that includes:

1. Key Findings: Identify and describe the main observations from the MRI image.
2. Clinical Significance: Explain the potential medical implications of these findings.
3. Differential Diagnosis: List possible diagnoses based on the findings, ordered by likelihood.
4. Recommended Follow-up: Suggest appropriate next steps for further evaluation or treatment.
5. Confidence Assessment: For each key finding and diagnosis, provide a confidence level (High, Medium, or Low) and explain your reasoning.
6. References: Cite the relevant medical knowledge sources that informed your analysis.

Your report should be professional, clear, and medically accurate. Use medical terminology appropriately but ensure the report remains understandable. Acknowledge any limitations in the analysis.

## Medical Report:
"""
        return prompt
    
    def _prepare_claude_request(self, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        """
        Prepare request body for Claude models.
        
        Args:
            prompt: Complete prompt for the LLM
            max_tokens: Maximum number of tokens to generate
            temperature: Temperature parameter for text generation
            
        Returns:
            Request body dictionary
        """
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }
    
    def _prepare_titan_request(self, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        """
        Prepare request body for Titan models.
        
        Args:
            prompt: Complete prompt for the LLM
            max_tokens: Maximum number of tokens to generate
            temperature: Temperature parameter for text generation
            
        Returns:
            Request body dictionary
        """
        return {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
                "topP": 0.9
            }
        }


def update_job_status(job_id: str, status: JobStatus, error_message: Optional[str] = None) -> None:
    """
    Update the status of an analysis job in the database.
    
    Args:
        job_id: Job ID for the analysis job
        status: New status for the job
        error_message: Optional error message if the job failed
    
    Raises:
        Exception: If the database update fails
    """
    try:
        with db_session_scope() as session:
            job = session.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
            
            if not job:
                logger.error(f"Job not found in database: {job_id}")
                raise PermanentError(f"Job not found: {job_id}", ErrorType.PERMANENT)
            
            job.status = status
            if error_message:
                job.error_message = error_message
            
            logger.info(f"Updated job {job_id} status to {status.value}")
            
    except Exception as e:
        logger.error(f"Failed to update job status in database: {e}")
        raise


def update_analysis_result(
    job_id: str, 
    enhanced_report: str, 
    confidence_scores: Dict[str, float],
    source_references: List[Dict[str, Any]],
    processing_metrics: Dict[str, Any]
) -> None:
    """
    Update or create an analysis result with LLM enhancement output.
    
    Args:
        job_id: Job ID for the analysis job
        enhanced_report: Enhanced medical report text
        confidence_scores: Confidence scores for different aspects of the report
        source_references: Source references used in the report
        processing_metrics: Processing metrics from the LLM invocation
    
    Raises:
        Exception: If the database update fails
    """
    try:
        with db_session_scope() as session:
            # Check if a result already exists for this job
            result = session.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).first()
            
            if result:
                # Update existing result
                result.enhanced_report = enhanced_report
                
                # Update confidence scores
                if not result.confidence_scores:
                    result.confidence_scores = {}
                result.confidence_scores['llm_confidence'] = confidence_scores
                
                # Update processing metrics
                if not result.processing_metrics:
                    result.processing_metrics = {}
                result.processing_metrics['llm_processing'] = processing_metrics
                result.processing_metrics['source_references'] = source_references
            else:
                # Create new result
                result = AnalysisResult(
                    job_id=job_id,
                    enhanced_report=enhanced_report,
                    confidence_scores={'llm_confidence': confidence_scores},
                    processing_metrics={
                        'llm_processing': processing_metrics,
                        'source_references': source_references
                    }
                )
                session.add(result)
            
            logger.info(f"Updated analysis result for job {job_id}")
            
    except Exception as e:
        logger.error(f"Failed to update analysis result in database: {e}")
        raise


def extract_confidence_scores(report_text: str) -> Dict[str, float]:
    """
    Extract confidence scores from the report text.
    
    Args:
        report_text: Enhanced medical report text
        
    Returns:
        Dictionary of confidence scores
    """
    # This is a simple implementation that could be enhanced with more sophisticated NLP
    confidence_scores = {
        'overall': 0.0,
        'findings': 0.0,
        'diagnosis': 0.0
    }
    
    # Look for confidence indicators in the text
    if "High confidence" in report_text or "high confidence" in report_text:
        confidence_scores['overall'] = 0.9
    elif "Medium confidence" in report_text or "medium confidence" in report_text:
        confidence_scores['overall'] = 0.7
    elif "Low confidence" in report_text or "low confidence" in report_text:
        confidence_scores['overall'] = 0.5
    else:
        confidence_scores['overall'] = 0.8  # Default if not specified
    
    # More specific confidence scores could be extracted with regex or NLP
    # This is a placeholder implementation
    confidence_scores['findings'] = confidence_scores['overall']
    confidence_scores['diagnosis'] = confidence_scores['overall'] - 0.1  # Slightly lower for diagnosis
    
    return confidence_scores


def extract_source_references(report_text: str, rag_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract source references from the report text and RAG context.
    
    Args:
        report_text: Enhanced medical report text
        rag_context: List of relevant medical knowledge documents
        
    Returns:
        List of source references with metadata
    """
    source_references = []
    
    # Create a mapping of titles to documents for easy lookup
    title_to_doc = {doc.get('title', ''): doc for doc in rag_context}
    
    # Simple extraction based on document titles
    # A more sophisticated implementation would use NLP to match citations
    for title in title_to_doc:
        if title in report_text:
            doc = title_to_doc[title]
            source_references.append({
                'title': doc.get('title', ''),
                'source': doc.get('source', ''),
                'author': doc.get('author', ''),
                'publication_date': doc.get('publication_date', ''),
                'url': doc.get('url', ''),
                'relevance_score': doc.get('relevance_score', 0.0)
            })
    
    # If no references were found, include the top document as a fallback
    if not source_references and rag_context:
        top_doc = rag_context[0]
        source_references.append({
            'title': top_doc.get('title', ''),
            'source': top_doc.get('source', ''),
            'author': top_doc.get('author', ''),
            'publication_date': top_doc.get('publication_date', ''),
            'url': top_doc.get('url', ''),
            'relevance_score': top_doc.get('relevance_score', 0.0),
            'inferred': True  # Flag to indicate this was not explicitly cited
        })
    
    return source_references


@handle_lambda_errors(ErrorContext(
    function_name="llm_rag_enhancement",
    operation="medical_report_generation"
))
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function handler for LLM and RAG enhancement processing.
    
    Args:
        event: Lambda event containing job_id and vlm_result
        context: Lambda context
        
    Returns:
        Dictionary containing the LLM enhancement results
    """
    logger.info(f"Received LLM enhancement request: {json.dumps(event)}")
    
    # Extract parameters from the event
    job_id = event.get('job_id')
    vlm_result = event.get('vlm_result', {})
    execution_id = event.get('execution_id', str(uuid.uuid4()))
    
    # Validate input parameters
    if not job_id:
        error_msg = "Missing required parameter: job_id"
        logger.error(error_msg)
        return {
            'statusCode': 400,
            'error': error_msg
        }
    
    # Extract image description from VLM result
    image_description = vlm_result.get('image_description')
    if not image_description:
        error_msg = "Missing image description in VLM result"
        logger.error(error_msg)
        return {
            'statusCode': 400,
            'error': error_msg
        }
    
    try:
        # Update job status to ENHANCING
        update_job_status(job_id, JobStatus.ENHANCING)
        
        # Initialize OpenSearch client
        opensearch_client = OpenSearchClient(OPENSEARCH_ENDPOINT, OPENSEARCH_INDEX)
        
        # Search for relevant medical knowledge
        logger.info(f"Searching for relevant medical knowledge for job {job_id}")
        rag_context = opensearch_client.search_medical_knowledge(image_description, TOP_K)
        
        # Initialize Bedrock LLM client
        bedrock_client = BedrockLLMClient(BEDROCK_MODEL_ID)
        
        # Generate enhanced medical report
        logger.info(f"Generating enhanced medical report for job {job_id}")
        start_time = time.time()
        enhanced_report, llm_metrics = bedrock_client.generate_enhanced_report(
            image_description=image_description,
            rag_context=rag_context
        )
        
        # Check if processing time exceeds the timeout
        processing_time = time.time() - start_time
        if processing_time > MODEL_TIMEOUT_SECONDS:
            logger.warning(f"LLM processing time ({processing_time:.2f}s) exceeded timeout ({MODEL_TIMEOUT_SECONDS}s)")
        
        # Extract confidence scores from the report
        confidence_scores = extract_confidence_scores(enhanced_report)
        
        # Extract source references
        source_references = extract_source_references(enhanced_report, rag_context)
        
        # Update the analysis result in the database
        update_analysis_result(
            job_id=job_id,
            enhanced_report=enhanced_report,
            confidence_scores=confidence_scores,
            source_references=source_references,
            processing_metrics=llm_metrics
        )
        
        # Prepare the response
        response = {
            'statusCode': 200,
            'job_id': job_id,
            'enhanced_report': enhanced_report,
            'confidence_scores': confidence_scores,
            'source_references': source_references,
            'processing_time_seconds': processing_time,
            'execution_id': execution_id
        }
        
        logger.info(f"LLM enhancement completed successfully for job {job_id}")
        return response
        
    except LLMEnhancementError as e:
        logger.error(f"LLM enhancement error for job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise
        
    except (RetryableError, PermanentError) as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, str(e))
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error for job {job_id}: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, f"Unexpected error: {str(e)}")
        raise