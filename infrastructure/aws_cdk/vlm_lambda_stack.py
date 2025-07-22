"""
VLM Processing Lambda Stack for Healthcare Image Analysis System.

This module defines the AWS CDK stack for the VLM image-to-text processing Lambda function.
"""

from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_ec2 as ec2,
    Duration
)
from constructs import Construct


class VLMLambdaStack(Stack):
    """
    CDK Stack for VLM processing Lambda function.
    """

    def __init__(self, scope: Construct, construct_id: str,
                 lambda_execution_role: iam.Role,
                 vpc: ec2.Vpc,
                 shared_layer: _lambda.LayerVersion,
                 s3_buckets: dict,
                 vlm_endpoint_name: str,
                 **kwargs) -> None:
        """
        Initialize the VLM Lambda Stack.
        
        Args:
            scope: CDK construct scope
            construct_id: CDK construct ID
            lambda_execution_role: IAM role for Lambda execution
            vpc: VPC for Lambda function
            shared_layer: Shared Lambda layer
            s3_buckets: Dictionary containing S3 bucket references
            vlm_endpoint_name: Name of the VLM SageMaker endpoint
            **kwargs: Additional keyword arguments
        """
        super().__init__(scope, construct_id, **kwargs)
        
        # Create VLM processing Lambda function
        self.vlm_lambda = self._create_vlm_lambda(
            lambda_execution_role=lambda_execution_role,
            vpc=vpc,
            shared_layer=shared_layer,
            s3_buckets=s3_buckets,
            vlm_endpoint_name=vlm_endpoint_name
        )

    def _create_vlm_lambda(self, lambda_execution_role: iam.Role,
                          vpc: ec2.Vpc,
                          shared_layer: _lambda.LayerVersion,
                          s3_buckets: dict,
                          vlm_endpoint_name: str) -> _lambda.Function:
        """
        Create Lambda function for VLM image-to-text processing.
        
        Args:
            lambda_execution_role: IAM role for Lambda execution
            vpc: VPC for Lambda function
            shared_layer: Shared Lambda layer
            s3_buckets: Dictionary containing S3 bucket references
            vlm_endpoint_name: Name of the VLM SageMaker endpoint
            
        Returns:
            Lambda function for VLM processing
        """
        vlm_lambda = _lambda.Function(
            self, "VLMProcessingLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset("src/lambda_functions/vlm_processing"),
            role=lambda_execution_role,
            timeout=Duration.minutes(10),
            memory_size=1024,
            environment={
                "SAGEMAKER_VLM_ENDPOINT": vlm_endpoint_name,
                "OUTPUT_BUCKET": s3_buckets['results'].bucket_name,
                "MODEL_TIMEOUT_SECONDS": "300",
                "DEFAULT_VLM_PROMPT": "Describe the medical findings in this MRI image in detail.",
                "AWS_REGION": self.region
            },
            vpc=vpc,
            layers=[shared_layer],
            reserved_concurrent_executions=10,  # Limit concurrent executions
            retry_attempts=2
        )
        
        # Add permissions for SageMaker endpoint invocation
        vlm_lambda.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "sagemaker:InvokeEndpoint"
            ],
            resources=[
                f"arn:aws:sagemaker:{self.region}:{self.account}:endpoint/{vlm_endpoint_name}"
            ]
        ))
        
        return vlm_lambda