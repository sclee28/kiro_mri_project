"""
Healthcare Image Analysis CDK Stack - Updated with Results Storage Lambda
"""
from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_stepfunctions as sfn,
    aws_sqs as sqs,
    aws_rds as rds,
    aws_opensearch as opensearch,
    aws_iam as iam,
    aws_ec2 as ec2,
    RemovalPolicy,
    Duration
)
from constructs import Construct
from .step_functions_stack import StepFunctionsStack
from .llm_rag_lambda_stack import LLMRAGLambdaStack
from .sagemaker_models_stack import SageMakerModelsStack
from .vlm_lambda_stack import VLMLambdaStack
from .notification_stack import NotificationStack
from .results_storage_lambda_stack import ResultsStorageLambdaStack


class HealthcareImageAnalysisStack(Stack):
    """
    Main CDK Stack for Healthcare Image Analysis System
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC for secure networking
        self.vpc = self._create_vpc()
        
        # S3 buckets for image storage
        self.s3_buckets = self._create_s3_buckets()
        
        # SQS queue for event processing
        self.sqs_queue = self._create_sqs_queue()
        
        # RDS database for results storage
        self.database = self._create_database()
        
        # OpenSearch for medical knowledge
        self.opensearch_domain = self._create_opensearch_domain()
        
        # IAM roles for Lambda functions
        self.lambda_execution_role = self._create_lambda_execution_role()
        
        # Create security group for Lambda functions
        self.lambda_security_group = ec2.SecurityGroup(
            self, "LambdaSecurityGroup",
            vpc=self.vpc,
            description="Security group for Lambda functions",
            allow_all_outbound=True
        )
        
        # SageMaker models stack
        self.sagemaker_models_stack = SageMakerModelsStack(
            self, "SageMakerModelsStack",
            s3_buckets=self.s3_buckets
        )
        
        # Create shared Lambda layer for common utilities
        self.shared_layer = _lambda.LayerVersion(
            self, "SharedUtilsLayer",
            code=_lambda.Code.from_asset("src/shared"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
            description="Shared utilities and models"
        )
        
        # Notification stack for SNS topics
        self.notification_stack = NotificationStack(
            self, "NotificationStack"
        )
        
        # Results storage Lambda stack
        self.results_storage_lambda_stack = ResultsStorageLambdaStack(
            self, "ResultsStorageLambdaStack",
            vpc=self.vpc,
            lambda_security_group=self.lambda_security_group,
            lambda_role=self.lambda_execution_role,
            notification_topic=self.notification_stack.topic
        )
        
        # Lambda functions
        self.s3_event_handler = self._create_s3_event_handler_lambda()
        self.segmentation_lambda = self._create_segmentation_lambda()
        
        # VLM processing Lambda
        self.vlm_lambda_stack = VLMLambdaStack(
            self, "VLMLambdaStack",
            lambda_execution_role=self.lambda_execution_role,
            vpc=self.vpc,
            shared_layer=self.shared_layer,
            s3_buckets=self.s3_buckets,
            vlm_endpoint_name=self.sagemaker_models_stack.vlm_endpoint.attr_endpoint_name
        )
        
        # LLM and RAG enhancement Lambda
        self.llm_rag_stack = LLMRAGLambdaStack(
            self, "LLMRAGStack",
            lambda_execution_role=self.lambda_execution_role,
            vpc=self.vpc,
            shared_layer=self.shared_layer,
            opensearch_domain=self.opensearch_domain
        )
        
        # Step Functions stack
        self.step_functions_stack = StepFunctionsStack(
            self, "StepFunctionsStack",
            lambda_execution_role=self.lambda_execution_role,
            vpc=self.vpc,
            shared_layer=self.shared_layer,
            segmentation_lambda=self.segmentation_lambda,
            vlm_lambda=self.vlm_lambda_stack.vlm_lambda,
            llm_rag_lambda=self.llm_rag_stack.llm_rag_lambda,
            results_storage_lambda=self.results_storage_lambda_stack.lambda_arn,
            notification_lambda=self.notification_stack.topic.topic_arn
        )
        
        # Update S3 event handler with Step Functions ARN
        self.s3_event_handler.add_environment(
            "STEP_FUNCTIONS_ARN",
            self.step_functions_stack.state_machine.state_machine_arn
        )
        
        # S3 event notifications
        self._configure_s3_event_notifications()

    # Rest of the methods remain the same as in the original file
    # ...