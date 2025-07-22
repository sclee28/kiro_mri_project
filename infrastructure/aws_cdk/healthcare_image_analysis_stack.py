"""
Healthcare Image Analysis CDK Stack
"""
import aws_cdk as cdk
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


class HealthcareImageAnalysisStack(Stack):
    """
    Main CDK Stack for Healthcare Image Analysis System
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # This is a placeholder stack structure
        # Individual components will be implemented in subsequent tasks
        
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
            llm_rag_lambda=self.llm_rag_stack.llm_rag_lambda
        )
        
        # Update S3 event handler with Step Functions ARN
        self.s3_event_handler.add_environment(
            "STEP_FUNCTIONS_ARN",
            self.step_functions_stack.state_machine.state_machine_arn
        )
        
        # S3 event notifications
        self._configure_s3_event_notifications()

    def _create_vpc(self) -> ec2.Vpc:
        """Create VPC for the application"""
        return ec2.Vpc(
            self, "HealthcareAnalysisVPC",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                )
            ]
        )

    def _create_s3_buckets(self) -> dict:
        """Create S3 buckets for image and results storage"""
        buckets = {}
        
        # MRI Images bucket
        buckets['images'] = s3.Bucket(
            self, "MRIImagesBucket",
            bucket_name=f"healthcare-mri-images-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionToIA",
                    enabled=True,
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30)
                        )
                    ]
                )
            ]
        )
        
        # Results bucket
        buckets['results'] = s3.Bucket(
            self, "ProcessedResultsBucket",
            bucket_name=f"healthcare-processed-results-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        return buckets

    def _create_sqs_queue(self) -> sqs.Queue:
        """Create SQS queue for processing events"""
        # Dead letter queue for failed messages
        dlq = sqs.Queue(
            self, "MRIProcessingDLQ",
            queue_name="mri-processing-dlq",
            retention_period=Duration.days(14)
        )
        
        # Main processing queue
        return sqs.Queue(
            self, "MRIProcessingQueue",
            queue_name="mri-processing-queue",
            visibility_timeout=Duration.minutes(15),
            retention_period=Duration.days(14),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq
            ),
            receive_message_wait_time=Duration.seconds(20)  # Long polling
        )

    def _create_database(self) -> rds.DatabaseInstance:
        """Create RDS PostgreSQL database"""
        return rds.DatabaseInstance(
            self, "HealthcareAnalysisDB",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_15
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3,
                ec2.InstanceSize.MICRO
            ),
            vpc=self.vpc,
            database_name="healthcare_analysis",
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False
        )

    def _create_opensearch_domain(self) -> opensearch.Domain:
        """Create OpenSearch domain for medical knowledge"""
        # Create security group for OpenSearch
        opensearch_sg = ec2.SecurityGroup(
            self, "OpenSearchSecurityGroup",
            vpc=self.vpc,
            description="Security group for OpenSearch domain",
            allow_all_outbound=True
        )
        
        # Create access policy for OpenSearch
        access_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["es:*"],
            principals=[iam.AnyPrincipal()],
            resources=["*"]
        )
        
        # Create OpenSearch domain with optimized settings
        domain = opensearch.Domain(
            self, "MedicalKnowledgeSearch",
            version=opensearch.EngineVersion.OPENSEARCH_2_11,
            capacity=opensearch.CapacityConfig(
                data_nodes=2,  # Increased for better performance and redundancy
                data_node_instance_type="t3.medium.search",  # Upgraded instance type
                master_nodes=3,  # Dedicated master nodes for better cluster management
                master_node_instance_type="t3.small.search"
            ),
            ebs=opensearch.EbsOptions(
                volume_size=50,  # Increased volume size for medical knowledge storage
                volume_type=ec2.EbsDeviceVolumeType.GP3,
                iops=3000,  # Improved IOPS for better performance
                throughput=125  # Improved throughput
            ),
            vpc=self.vpc,
            security_groups=[opensearch_sg],
            access_policies=[access_policy],
            encryption_at_rest=opensearch.EncryptionAtRestOptions(
                enabled=True  # Enable encryption at rest for security
            ),
            node_to_node_encryption=True,  # Enable node-to-node encryption
            enforce_https=True,  # Enforce HTTPS for all traffic
            logging=opensearch.LoggingOptions(
                slow_search_log_enabled=True,  # Enable slow search logging for performance monitoring
                app_log_enabled=True,
                slow_index_log_enabled=True
            ),
            fine_grained_access_control=opensearch.AdvancedSecurityOptions(
                master_user_name="admin",
                master_user_password=cdk.SecretValue.unsafe_plain_text("REPLACE_WITH_SECURE_PASSWORD")  # Should use Secrets Manager in production
            ),
            removal_policy=RemovalPolicy.DESTROY,
            zone_awareness=opensearch.ZoneAwarenessConfig(
                enabled=True,  # Enable zone awareness for high availability
                availability_zone_count=2
            )
        )
        
        return domain

    def _create_lambda_execution_role(self) -> iam.Role:
        """Create IAM role for Lambda functions"""
        role = iam.Role(
            self, "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                )
            ]
        )
        
        # Add permissions for S3 access
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "s3:GetObject",
                "s3:GetObjectMetadata",
                "s3:HeadObject",
                "s3:ListBucket"
            ],
            resources=[
                self.s3_buckets['images'].bucket_arn,
                f"{self.s3_buckets['images'].bucket_arn}/*",
                self.s3_buckets['results'].bucket_arn,
                f"{self.s3_buckets['results'].bucket_arn}/*"
            ]
        ))
        
        # Add permissions for SQS access
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes",
                "sqs:SendMessage"
            ],
            resources=[self.sqs_queue.queue_arn]
        ))
        
        # Add permissions for RDS access
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "rds:DescribeDBInstances",
                "rds:Connect"
            ],
            resources=[self.database.instance_arn]
        ))
        
        # Add permissions for Step Functions execution
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "states:StartExecution",
                "states:DescribeExecution",
                "states:StopExecution"
            ],
            resources=["*"]  # Will be restricted when Step Functions is created
        ))
        
        return role

    def _create_s3_event_handler_lambda(self) -> _lambda.Function:
        """Create Lambda function for handling S3 events"""
        return _lambda.Function(
            self, "S3EventHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("src/lambda_functions/s3_event_handler"),
            role=self.lambda_execution_role,
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "SQS_QUEUE_URL": self.sqs_queue.queue_url,
                "AWS_REGION": self.region,
                "DB_HOST": self.database.instance_endpoint.hostname,
                "DB_PORT": str(self.database.instance_endpoint.port),
                "DB_NAME": "healthcare_analysis",
                "DB_USERNAME": "postgres",
                # DB_PASSWORD should be set via AWS Secrets Manager in production
            },
            vpc=self.vpc,
            layers=[
                _lambda.LayerVersion(
                    self, "SharedUtilsLayer",
                    code=_lambda.Code.from_asset("src/shared"),
                    compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
                    description="Shared utilities and models"
                )
            ],
            reserved_concurrent_executions=10,  # Limit concurrent executions
            retry_attempts=2
        )

    def _configure_s3_event_notifications(self) -> None:
        """Configure S3 event notifications to trigger SQS queue"""
        # Add S3 event notification for object creation - NIfTI format
        self.s3_buckets['images'].add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.sqs_queue),
            s3.NotificationKeyFilter(
                prefix="uploads/",
                suffix=".nii"
            )
        )
        
        # Support .nii.gz compressed format
        self.s3_buckets['images'].add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.sqs_queue),
            s3.NotificationKeyFilter(
                prefix="uploads/",
                suffix=".nii.gz"
            )
        )
        
        # Support DICOM format
        self.s3_buckets['images'].add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.sqs_queue),
            s3.NotificationKeyFilter(
                prefix="uploads/",
                suffix=".dcm"
            )
        )
        
        # Configure Lambda to be triggered by SQS messages
        self.s3_event_handler.add_event_source(
            lambda_events.SqsEventSource(
                self.sqs_queue,
                batch_size=10,  # Process up to 10 messages at once
                max_batching_window=Duration.seconds(5),  # Wait up to 5 seconds to batch
                report_batch_item_failures=True  # Enable partial batch failure reporting
            )
        )
        
    def _create_segmentation_lambda(self) -> _lambda.Function:
        """Create Lambda function for MRI segmentation processing"""
        # Get the segmentation endpoint name from the SageMaker models stack
        segmentation_endpoint_name = self.sagemaker_models_stack.segmentation_endpoint.attr_endpoint_name
        
        segmentation_lambda = _lambda.Function(
            self, "SegmentationTrigger",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset("src/lambda_functions/segmentation_trigger"),
            role=self.lambda_execution_role,
            timeout=Duration.minutes(10),
            memory_size=1024,
            environment={
                "SAGEMAKER_ENDPOINT_NAME": segmentation_endpoint_name,
                "OUTPUT_BUCKET": self.s3_buckets['results'].bucket_name,
                "MODEL_TIMEOUT_SECONDS": "300",
                "AWS_REGION": self.region,
                "DB_HOST": self.database.instance_endpoint.hostname,
                "DB_PORT": str(self.database.instance_endpoint.port),
                "DB_NAME": "healthcare_analysis",
                "DB_USERNAME": "postgres",
                # DB_PASSWORD should be set via AWS Secrets Manager in production
            },
            vpc=self.vpc,
            layers=[self.shared_layer],
            reserved_concurrent_executions=10,  # Limit concurrent executions
            retry_attempts=2
        )
        
        # Add permissions for SageMaker endpoint invocation
        segmentation_lambda.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "sagemaker:InvokeEndpoint"
            ],
            resources=[
                f"arn:aws:sagemaker:{self.region}:{self.account}:endpoint/{segmentation_endpoint_name}"
            ]
        ))
        
        return segmentation_lambda