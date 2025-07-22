"""
Unit tests for the LLM and RAG enhancement Lambda function.
"""

import os
import json
import unittest
from unittest.mock import patch, MagicMock, ANY

import boto3
from botocore.exceptions import ClientError

from src.lambda_functions.llm_rag_enhancement.handler import (
    handler, OpenSearchClient, BedrockLLMClient, 
    extract_confidence_scores, extract_source_references,
    update_job_status, update_analysis_result
)
from src.shared.models.database import JobStatus


class TestLLMRAGEnhancement(unittest.TestCase):
    """Test cases for the LLM and RAG enhancement Lambda function."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock environment variables
        self.env_patcher = patch.dict(os.environ, {
            'BEDROCK_MODEL_ID': 'anthropic.claude-3-sonnet-20240229-v1:0',
            'OPENSEARCH_ENDPOINT': 'test-endpoint.us-east-1.es.amazonaws.com',
            'OPENSEARCH_INDEX': 'medical-knowledge-test',
            'OUTPUT_BUCKET': 'test-output-bucket',
            'MODEL_TIMEOUT_SECONDS': '300',
            'MAX_TOKENS': '4096',
            'TEMPERATURE': '0.7',
            'TOP_K': '5'
        })
        self.env_patcher.start()
        
        # Sample test data
        self.job_id = '12345678-1234-5678-1234-567812345678'
        self.image_description = 'MRI scan shows abnormal signal intensity in the left temporal lobe.'
        self.vlm_result = {
            'image_description': self.image_description,
            'confidence_score': 0.85
        }
        self.event = {
            'job_id': self.job_id,
            'vlm_result': self.vlm_result,
            'execution_id': 'test-execution-id'
        }
        
        # Sample RAG context
        self.rag_context = [
            {
                'content': 'Abnormal signal intensity in the temporal lobe can indicate various conditions including tumors, infections, or vascular abnormalities.',
                'title': 'Temporal Lobe Abnormalities in MRI',
                'source': 'Journal of Neuroradiology',
                'author': 'Smith et al.',
                'publication_date': '2023',
                'url': 'https://example.com/journal/article1',
                'relevance_score': 0.92,
                'confidence': 0.88
            },
            {
                'content': 'Left temporal lobe lesions are often associated with language deficits and memory impairment.',
                'title': 'Functional Impact of Temporal Lobe Lesions',
                'source': 'Neurology Today',
                'author': 'Johnson and Brown',
                'publication_date': '2022',
                'url': 'https://example.com/journal/article2',
                'relevance_score': 0.85,
                'confidence': 0.9
            }
        ]
        
        # Sample enhanced report
        self.enhanced_report = """
# Medical Report

## Key Findings
- Abnormal signal intensity in the left temporal lobe (High confidence)
- No evidence of mass effect or midline shift (Medium confidence)

## Clinical Significance
The abnormal signal intensity in the left temporal lobe may indicate several possible pathologies including tumor, infection, or vascular abnormality. The absence of mass effect suggests a less aggressive process.

## Differential Diagnosis
1. Low-grade glioma (Medium confidence)
2. Focal encephalitis (Medium confidence)
3. Vascular malformation (Low confidence)

## Recommended Follow-up
1. Contrast-enhanced MRI to better characterize the lesion
2. Clinical correlation with neurological assessment
3. Consider EEG to rule out seizure activity

## References
1. Smith et al. (2023) "Temporal Lobe Abnormalities in MRI", Journal of Neuroradiology
2. Johnson and Brown (2022) "Functional Impact of Temporal Lobe Lesions", Neurology Today
"""
    
    def tearDown(self):
        """Tear down test fixtures."""
        self.env_patcher.stop()
    
    @patch('src.lambda_functions.llm_rag_enhancement.handler.update_job_status')
    @patch('src.lambda_functions.llm_rag_enhancement.handler.update_analysis_result')
    @patch('src.lambda_functions.llm_rag_enhancement.handler.OpenSearchClient')
    @patch('src.lambda_functions.llm_rag_enhancement.handler.BedrockLLMClient')
    def test_handler_success(self, mock_bedrock_client, mock_opensearch_client, 
                            mock_update_result, mock_update_status):
        """Test successful execution of the handler."""
        # Configure mocks
        mock_opensearch_instance = mock_opensearch_client.return_value
        mock_opensearch_instance.search_medical_knowledge.return_value = self.rag_context
        
        mock_bedrock_instance = mock_bedrock_client.return_value
        mock_bedrock_instance.generate_enhanced_report.return_value = (
            self.enhanced_report, 
            {'model_id': 'test-model', 'processing_time_seconds': 2.5}
        )
        
        # Execute handler
        response = handler(self.event, {})
        
        # Verify results
        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(response['job_id'], self.job_id)
        self.assertEqual(response['enhanced_report'], self.enhanced_report)
        
        # Verify function calls
        mock_update_status.assert_any_call(self.job_id, JobStatus.ENHANCING)
        mock_opensearch_instance.search_medical_knowledge.assert_called_once_with(
            self.image_description, 5
        )
        mock_bedrock_instance.generate_enhanced_report.assert_called_once_with(
            image_description=self.image_description,
            rag_context=self.rag_context
        )
        mock_update_result.assert_called_once()
    
    @patch('src.lambda_functions.llm_rag_enhancement.handler.update_job_status')
    def test_handler_missing_job_id(self, mock_update_status):
        """Test handler with missing job ID."""
        event = {'vlm_result': self.vlm_result}
        response = handler(event, {})
        
        self.assertEqual(response['statusCode'], 400)
        self.assertIn('Missing required parameter', response['error'])
        mock_update_status.assert_not_called()
    
    @patch('src.lambda_functions.llm_rag_enhancement.handler.update_job_status')
    def test_handler_missing_image_description(self, mock_update_status):
        """Test handler with missing image description."""
        event = {'job_id': self.job_id, 'vlm_result': {}}
        response = handler(event, {})
        
        self.assertEqual(response['statusCode'], 400)
        self.assertIn('Missing image description', response['error'])
        mock_update_status.assert_not_called()
    
    def test_extract_confidence_scores(self):
        """Test extraction of confidence scores from report text."""
        scores = extract_confidence_scores(self.enhanced_report)
        
        self.assertIn('overall', scores)
        self.assertIn('findings', scores)
        self.assertIn('diagnosis', scores)
        self.assertGreaterEqual(scores['overall'], 0.0)
        self.assertLessEqual(scores['overall'], 1.0)
    
    def test_extract_source_references(self):
        """Test extraction of source references from report text."""
        references = extract_source_references(self.enhanced_report, self.rag_context)
        
        self.assertGreaterEqual(len(references), 1)
        self.assertIn('title', references[0])
        self.assertIn('source', references[0])
    
    @patch('src.lambda_functions.llm_rag_enhancement.handler.OpenSearch')
    def test_opensearch_client_initialization(self, mock_opensearch):
        """Test OpenSearch client initialization."""
        client = OpenSearchClient('test-endpoint.us-east-1.es.amazonaws.com', 'test-index')
        
        mock_opensearch.assert_called_once()
        self.assertEqual(client.endpoint, 'test-endpoint.us-east-1.es.amazonaws.com')
        self.assertEqual(client.index, 'test-index')
    
    @patch('src.lambda_functions.llm_rag_enhancement.handler.OpenSearch')
    def test_opensearch_search_medical_knowledge(self, mock_opensearch):
        """Test OpenSearch search_medical_knowledge method."""
        # Configure mock
        mock_opensearch_instance = mock_opensearch.return_value
        mock_opensearch_instance.search.return_value = {
            'hits': {
                'hits': [
                    {
                        '_score': 9.5,
                        '_source': {
                            'content': 'Test content',
                            'title': 'Test title',
                            'source': 'Test source'
                        }
                    }
                ]
            }
        }
        
        client = OpenSearchClient('test-endpoint', 'test-index')
        results = client.search_medical_knowledge('test query')
        
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Test title')
        mock_opensearch_instance.search.assert_called_once()
    
    @patch('src.lambda_functions.llm_rag_enhancement.handler.bedrock_runtime')
    def test_bedrock_client_generate_enhanced_report(self, mock_bedrock_runtime):
        """Test Bedrock client generate_enhanced_report method."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.get.return_value.read.return_value = json.dumps({
            'content': [{'text': 'Test report'}],
            'usage': {'output_tokens': 100}
        }).encode()
        mock_bedrock_runtime.invoke_model.return_value = mock_response
        
        client = BedrockLLMClient('anthropic.claude-3-sonnet-20240229-v1:0')
        report, metadata = client.generate_enhanced_report(
            image_description='Test description',
            rag_context=self.rag_context
        )
        
        self.assertEqual(report, 'Test report')
        self.assertIn('model_id', metadata)
        self.assertIn('processing_time_seconds', metadata)
        mock_bedrock_runtime.invoke_model.assert_called_once()


if __name__ == '__main__':
    unittest.main()