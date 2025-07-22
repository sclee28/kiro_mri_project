"""
SageMaker Models Stack for Healthcare Image Analysis System.

This module defines the AWS CDK stack for deploying SageMaker models used in the
healthcare image analysis pipeline, including MRI segmentation and VLM models.
"""

from aws_cdk import (
    Stack,
    aws_sagemaker as sagemaker,
    aws_iam as iam,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_sns as sns,
    aws_logs as logs,
    Duration,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct


class SageMakerModelsStack(Stack):
    """
    CDK Stack for SageMaker model deployments with auto-scaling and monitoring.
    """

    def __init__(self, scope: Construct, construct_id: str, 
                 s3_buckets: dict, **kwargs) -> None:
        """
        Initialize the SageMaker Models Stack.
        
        Args:
            scope: CDK construct scope
            construct_id: CDK construct ID
            s3_buckets: Dictionary containing S3 bucket references
            **kwargs: Additional keyword arguments
        """
        super().__init__(scope, construct_id, **kwargs)
        
        # Create SageMaker execution role
        self.sagemaker_role = self._create_sagemaker_execution_role(s3_buckets)
        
        # Create SNS topic for model alerts
        self.alerts_topic = sns.Topic(
            self, "ModelAlertsSnsTopic",
            display_name="SageMaker Model Alerts",
            topic_name="sagemaker-model-alerts"
        )
        
        # Deploy MRI segmentation model
        self.segmentation_endpoint = self._deploy_mri_segmentation_model()
        
        # Deploy HuggingFace VLM model
        self.vlm_endpoint = self._deploy_huggingface_vlm_model()
        
        # Set up monitoring for both endpoints
        self._setup_endpoint_monitoring(self.segmentation_endpoint, "MRISegmentation")
        self._setup_endpoint_monitoring(self.vlm_endpoint, "VLM")
        
        # Output the endpoint names
        CfnOutput(
            self, "SegmentationEndpointName",
            value=self.segmentation_endpoint.attr_endpoint_name,
            description="MRI Segmentation SageMaker endpoint name"
        )
        
        CfnOutput(
            self, "VLMEndpointName",
            value=self.vlm_endpoint.attr_endpoint_name,
            description="VLM SageMaker endpoint name"
        )

    def _create_sagemaker_execution_role(self, s3_buckets: dict) -> iam.Role:
        """
        Create IAM role for SageMaker execution.
        
        Args:
            s3_buckets: Dictionary containing S3 bucket references
            
        Returns:
            IAM role for SageMaker execution
        """
        role = iam.Role(
            self, "SageMakerExecutionRole",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSageMakerFullAccess"
                )
            ]
        )
        
        # Add S3 access permissions
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "s3:GetObject",
                "s3:PutObject",
                "s3:ListBucket"
            ],
            resources=[
                s3_buckets['images'].bucket_arn,
                f"{s3_buckets['images'].bucket_arn}/*",
                s3_buckets['results'].bucket_arn,
                f"{s3_buckets['results'].bucket_arn}/*"
            ]
        ))
        
        # Add CloudWatch permissions for logging
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            resources=["*"]
        ))
        
        # Add ECR permissions for container images
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability"
            ],
            resources=["*"]
        ))
        
        return role

    def _deploy_mri_segmentation_model(self) -> sagemaker.CfnEndpoint:
        """
        Deploy MRI segmentation model to SageMaker.
        
        Returns:
            SageMaker endpoint for MRI segmentation
        """
        # Create model
        model = sagemaker.CfnModel(
            self, "MRISegmentationModel",
            execution_role_arn=self.sagemaker_role.role_arn,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                image="763104351884.dkr.ecr.us-east-1.amazonaws.com/pytorch-inference:1.12.0-gpu-py38",
                model_data_url="s3://model-artifacts/mri-segmentation/model.tar.gz",
                environment={
                    "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
                    "SAGEMAKER_REGION": self.region
                }
            ),
            model_name="mri-segmentation-model"
        )
        
        # Create endpoint configuration with auto-scaling
        endpoint_config = sagemaker.CfnEndpointConfig(
            self, "MRISegmentationEndpointConfig",
            production_variants=[
                sagemaker.CfnEndpointConfig.ProductionVariantProperty(
                    model_name=model.attr_model_name,
                    variant_name="AllTraffic",
                    initial_instance_count=1,
                    instance_type="ml.g4dn.xlarge",
                    initial_variant_weight=1.0
                )
            ],
            data_capture_config=sagemaker.CfnEndpointConfig.DataCaptureConfigProperty(
                capture_options=[
                    sagemaker.CfnEndpointConfig.CaptureOptionProperty(
                        capture_mode="Input"
                    ),
                    sagemaker.CfnEndpointConfig.CaptureOptionProperty(
                        capture_mode="Output"
                    )
                ],
                destination_s3_uri=f"s3://{self.account}-sagemaker-datacapture/mri-segmentation/",
                initial_sampling_percentage=20.0,
                capture_content_type_header=sagemaker.CfnEndpointConfig.CaptureContentTypeHeaderProperty(
                    csv_content_types=["text/csv"],
                    json_content_types=["application/json"]
                )
            )
        )
        
        # Create endpoint
        endpoint = sagemaker.CfnEndpoint(
            self, "MRISegmentationEndpoint",
            endpoint_config_name=endpoint_config.attr_endpoint_config_name,
            endpoint_name="mri-segmentation-endpoint"
        )
        
        # Add auto-scaling configuration
        self._configure_autoscaling(
            endpoint_name="mri-segmentation-endpoint",
            variant_name="AllTraffic",
            min_capacity=1,
            max_capacity=4,
            target_utilization=70.0,
            scale_in_cooldown=300,
            scale_out_cooldown=60
        )
        
        return endpoint

    def _deploy_huggingface_vlm_model(self) -> sagemaker.CfnEndpoint:
        """
        Deploy HuggingFace VLM model to SageMaker.
        
        Returns:
            SageMaker endpoint for VLM processing
        """
        # Create model
        model = sagemaker.CfnModel(
            self, "HuggingFaceVLMModel",
            execution_role_arn=self.sagemaker_role.role_arn,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                image="763104351884.dkr.ecr.us-east-1.amazonaws.com/huggingface-pytorch-inference:1.13.1-transformers4.26.0-gpu-py39-cu117-ubuntu20.04",
                environment={
                    "HF_MODEL_ID": "microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224",
                    "HF_TASK": "image-to-text",
                    "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
                    "SAGEMAKER_REGION": self.region
                }
            ),
            model_name="huggingface-vlm-model"
        )
        
        # Create endpoint configuration with auto-scaling
        endpoint_config = sagemaker.CfnEndpointConfig(
            self, "HuggingFaceVLMEndpointConfig",
            production_variants=[
                sagemaker.CfnEndpointConfig.ProductionVariantProperty(
                    model_name=model.attr_model_name,
                    variant_name="AllTraffic",
                    initial_instance_count=1,
                    instance_type="ml.g5.xlarge",
                    initial_variant_weight=1.0
                )
            ],
            data_capture_config=sagemaker.CfnEndpointConfig.DataCaptureConfigProperty(
                capture_options=[
                    sagemaker.CfnEndpointConfig.CaptureOptionProperty(
                        capture_mode="Input"
                    ),
                    sagemaker.CfnEndpointConfig.CaptureOptionProperty(
                        capture_mode="Output"
                    )
                ],
                destination_s3_uri=f"s3://{self.account}-sagemaker-datacapture/vlm-processing/",
                initial_sampling_percentage=20.0,
                capture_content_type_header=sagemaker.CfnEndpointConfig.CaptureContentTypeHeaderProperty(
                    csv_content_types=["text/csv"],
                    json_content_types=["application/json"]
                )
            )
        )
        
        # Create endpoint
        endpoint = sagemaker.CfnEndpoint(
            self, "HuggingFaceVLMEndpoint",
            endpoint_config_name=endpoint_config.attr_endpoint_config_name,
            endpoint_name="huggingface-vlm-endpoint"
        )
        
        # Add auto-scaling configuration
        self._configure_autoscaling(
            endpoint_name="huggingface-vlm-endpoint",
            variant_name="AllTraffic",
            min_capacity=1,
            max_capacity=3,
            target_utilization=60.0,
            scale_in_cooldown=300,
            scale_out_cooldown=60
        )
        
        return endpoint

    def _configure_autoscaling(self, endpoint_name: str, variant_name: str,
                              min_capacity: int, max_capacity: int,
                              target_utilization: float,
                              scale_in_cooldown: int, scale_out_cooldown: int) -> None:
        """
        Configure auto-scaling for a SageMaker endpoint.
        
        Args:
            endpoint_name: Name of the SageMaker endpoint
            variant_name: Name of the production variant
            min_capacity: Minimum number of instances
            max_capacity: Maximum number of instances
            target_utilization: Target utilization percentage
            scale_in_cooldown: Scale-in cooldown period in seconds
            scale_out_cooldown: Scale-out cooldown period in seconds
        """
        # Create auto-scaling target
        target_tracking_specification = sagemaker.CfnScalingPolicy.TargetTrackingScalingPolicyConfigurationProperty(
            target_value=target_utilization,
            scale_in_cooldown=scale_in_cooldown,
            scale_out_cooldown=scale_out_cooldown,
            predefined_metric_specification=sagemaker.CfnScalingPolicy.PredefinedMetricSpecificationProperty(
                predefined_metric_type="SageMakerVariantInvocationsPerInstance"
            )
        )
        
        # Create scaling policy
        sagemaker.CfnScalingPolicy(
            self, f"{endpoint_name}-ScalingPolicy",
            policy_name=f"{endpoint_name}-autoscaling-policy",
            policy_type="TargetTrackingScaling",
            resource_id=f"endpoint/{endpoint_name}/variant/{variant_name}",
            scalable_dimension="sagemaker:variant:DesiredInstanceCount",
            service_namespace="sagemaker",
            target_tracking_scaling_policy_configuration=target_tracking_specification
        )
        
        # Set min and max capacity
        sagemaker.CfnScalableTarget(
            self, f"{endpoint_name}-ScalableTarget",
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            resource_id=f"endpoint/{endpoint_name}/variant/{variant_name}",
            scalable_dimension="sagemaker:variant:DesiredInstanceCount",
            service_namespace="sagemaker"
        )

    def _setup_endpoint_monitoring(self, endpoint: sagemaker.CfnEndpoint, endpoint_type: str) -> None:
        """
        Set up CloudWatch monitoring for a SageMaker endpoint.
        
        Args:
            endpoint: SageMaker endpoint
            endpoint_type: Type of endpoint (for naming)
        """
        # Create log group for endpoint
        log_group = logs.LogGroup(
            self, f"{endpoint_type}EndpointLogGroup",
            log_group_name=f"/aws/sagemaker/Endpoints/{endpoint.attr_endpoint_name}",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_MONTH
        )
        
        # Create CloudWatch alarms for endpoint metrics
        
        # 1. Invocation errors alarm
        invocation_errors_alarm = cloudwatch.Alarm(
            self, f"{endpoint_type}InvocationErrorsAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SageMaker",
                metric_name="ModelLatency",
                dimensions_map={
                    "EndpointName": endpoint.attr_endpoint_name,
                    "VariantName": "AllTraffic"
                },
                statistic="p99",
                period=Duration.minutes(5)
            ),
            evaluation_periods=3,
            threshold=5000,  # 5 seconds (5000ms)
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description=f"High latency detected for {endpoint_type} endpoint",
            alarm_name=f"{endpoint_type}-high-latency-alarm"
        )
        
        # 2. Model latency alarm
        model_latency_alarm = cloudwatch.Alarm(
            self, f"{endpoint_type}ModelLatencyAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SageMaker",
                metric_name="Invocation4XXErrors",
                dimensions_map={
                    "EndpointName": endpoint.attr_endpoint_name,
                    "VariantName": "AllTraffic"
                },
                statistic="sum",
                period=Duration.minutes(5)
            ),
            evaluation_periods=3,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description=f"High 4XX error rate detected for {endpoint_type} endpoint",
            alarm_name=f"{endpoint_type}-4xx-errors-alarm"
        )
        
        # 3. Invocation 5XX errors alarm
        invocation_5xx_alarm = cloudwatch.Alarm(
            self, f"{endpoint_type}Invocation5XXAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SageMaker",
                metric_name="Invocation5XXErrors",
                dimensions_map={
                    "EndpointName": endpoint.attr_endpoint_name,
                    "VariantName": "AllTraffic"
                },
                statistic="sum",
                period=Duration.minutes(5)
            ),
            evaluation_periods=3,
            threshold=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description=f"High 5XX error rate detected for {endpoint_type} endpoint",
            alarm_name=f"{endpoint_type}-5xx-errors-alarm"
        )
        
        # 4. CPU utilization alarm
        cpu_utilization_alarm = cloudwatch.Alarm(
            self, f"{endpoint_type}CPUUtilizationAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SageMaker",
                metric_name="CPUUtilization",
                dimensions_map={
                    "EndpointName": endpoint.attr_endpoint_name,
                    "VariantName": "AllTraffic"
                },
                statistic="average",
                period=Duration.minutes(5)
            ),
            evaluation_periods=3,
            threshold=85,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description=f"High CPU utilization detected for {endpoint_type} endpoint",
            alarm_name=f"{endpoint_type}-cpu-utilization-alarm"
        )
        
        # 5. Memory utilization alarm
        memory_utilization_alarm = cloudwatch.Alarm(
            self, f"{endpoint_type}MemoryUtilizationAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SageMaker",
                metric_name="MemoryUtilization",
                dimensions_map={
                    "EndpointName": endpoint.attr_endpoint_name,
                    "VariantName": "AllTraffic"
                },
                statistic="average",
                period=Duration.minutes(5)
            ),
            evaluation_periods=3,
            threshold=85,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description=f"High memory utilization detected for {endpoint_type} endpoint",
            alarm_name=f"{endpoint_type}-memory-utilization-alarm"
        )
        
        # 6. GPU utilization alarm (for GPU instances)
        gpu_utilization_alarm = cloudwatch.Alarm(
            self, f"{endpoint_type}GPUUtilizationAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SageMaker",
                metric_name="GPUUtilization",
                dimensions_map={
                    "EndpointName": endpoint.attr_endpoint_name,
                    "VariantName": "AllTraffic"
                },
                statistic="average",
                period=Duration.minutes(5)
            ),
            evaluation_periods=3,
            threshold=90,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description=f"High GPU utilization detected for {endpoint_type} endpoint",
            alarm_name=f"{endpoint_type}-gpu-utilization-alarm"
        )
        
        # Add SNS actions to all alarms
        invocation_errors_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))
        model_latency_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))
        invocation_5xx_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))
        cpu_utilization_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))
        memory_utilization_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))
        gpu_utilization_alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))