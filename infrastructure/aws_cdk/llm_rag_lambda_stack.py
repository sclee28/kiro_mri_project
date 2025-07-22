"""
CDK Stack for LLM and RAG enhancement Lambda function.
"""
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_iam as iam,
    Duration
)
from constructs import Construct


class LLMRAGLambdaStack(Construct):
    """
    CDK Construct for LLM and RAG enhancement Lambda function.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        lambda_execution_role: iam.Role,
        vpc,
        shared_layer: _lambda.LayerVersion,
        opensearch_domain,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id)
        
        # Create LLM and RAG enhancement Lambda function
        self.llm_rag_lambda = self._create_llm_rag_lambda(
            lambda_execution_role, 
            shared_layer, 
            vpc,
            opensearch_domain
        )
    
    def _create_llm_rag_lambda(
        self, 
        execution_role: iam.Role, 
        shared_layer: _lambda.LayerVersion, 
        vpc,
        opensearch_domain
    ) -> _lambda.Function:
        """
        Create Lambda function for LLM and RAG enhancement processing
        
        Args:
            execution_role: IAM role for Lambda execution
            shared_layer: Shared Lambda layer
            vpc: VPC for Lambda function
            opensearch_domain: OpenSearch domain for medical knowledge retrieval
            
        Returns:
            Lambda function
        """
        # Create Lambda layer for OpenSearch dependencies
        opensearch_layer = _lambda.LayerVersion(
            self, "OpenSearchLayer",
            code=_lambda.Code.from_asset("src/lambda_functions/llm_rag_enhancement"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
            description="OpenSearch and AWS4Auth dependencies"
        )
        
        # Create Lambda function
        llm_rag_lambda = _lambda.Function(
            self, "LLMRAGEnhancement",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset("src/lambda_functions/llm_rag_enhancement"),
            role=execution_role,
            timeout=Duration.minutes(10),
            memory_size=1024,
            environment={
                "BEDROCK_MODEL_ID": "anthropic.claude-3-sonnet-20240229-v1:0",
                "OPENSEARCH_ENDPOINT": opensearch_domain.domain_endpoint,
                "OPENSEARCH_INDEX": "medical-knowledge",
                "MAX_TOKENS": "4096",
                "TEMPERATURE": "0.7",
                "TOP_K": "5",
                "MODEL_TIMEOUT_SECONDS": "300"
            },
            vpc=vpc,
            layers=[shared_layer, opensearch_layer],
            reserved_concurrent_executions=10,  # Limit concurrent executions
            retry_attempts=2
        )
        
        # Add permissions for Bedrock model invocation
        llm_rag_lambda.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:InvokeModel"
            ],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0"
            ]
        ))
        
        # Add permissions for OpenSearch access
        llm_rag_lambda.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "es:ESHttpGet",
                "es:ESHttpPost",
                "es:ESHttpPut"
            ],
            resources=[
                opensearch_domain.domain_arn,
                f"{opensearch_domain.domain_arn}/*"
            ]
        ))
        
        return llm_rag_lambda