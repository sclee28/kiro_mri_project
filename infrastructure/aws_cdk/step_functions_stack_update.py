"""
AWS CDK stack for Step Functions state machine.
"""

from aws_cdk import (
    Stack,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_logs as logs,
    aws_ec2 as ec2,
    Duration
)
from constructs import Construct


class StepFunctionsStack(Stack):
    """
    CDK Stack for Step Functions state machine orchestration.
    
    This stack creates the Step Functions state machine that orchestrates
    the MRI image analysis pipeline.
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        lambda_execution_role: iam.Role,
        vpc: ec2.Vpc,
        shared_layer: lambda_.LayerVersion,
        segmentation_lambda: lambda_.Function,
        vlm_lambda: lambda_.Function,
        llm_rag_lambda: lambda_.Function,
        results_storage_lambda: str,
        notification_lambda: str,
        **kwargs
    ) -> None:
        """
        Initialize the stack.
        
        Args:
            scope: CDK construct scope
            construct_id: CDK construct ID
            lambda_execution_role: IAM role for Lambda functions
            vpc: VPC for Lambda functions
            shared_layer: Shared Lambda layer
            segmentation_lambda: Segmentation Lambda function
            vlm_lambda: VLM processing Lambda function
            llm_rag_lambda: LLM and RAG enhancement Lambda function
            results_storage_lambda: Results storage Lambda function ARN
            notification_lambda: Notification Lambda function ARN
            **kwargs: Additional arguments
        """
        super().__init__(scope, construct_id, **kwargs)
        
        # Create error handler Lambda
        error_handler_lambda = lambda_.Function(
            self,
            "StepFunctionsErrorHandler",
            function_name="healthcare-step-functions-error-handler",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="src.lambda_functions.step_functions_error_handler.handler.handler",
            code=lambda_.Code.from_asset("."),
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO"
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            role=lambda_execution_role,
            layers=[shared_layer]
        )
        
        # Create log group for Step Functions
        log_group = logs.LogGroup(
            self,
            "StepFunctionsLogGroup",
            log_group_name="/aws/vendedlogs/states/healthcare-image-analysis",
            retention=logs.RetentionDays.ONE_WEEK
        )
        
        # Create Step Functions tasks
        segment_image_task = tasks.LambdaInvoke(
            self,
            "SegmentImage",
            lambda_function=segmentation_lambda,
            payload=sfn.TaskInput.from_object({
                "job_id.$": "$.job_id",
                "bucket_name.$": "$.bucket_name",
                "object_key.$": "$.object_key",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.segmentation_result",
            retry_on_service_exceptions=True,
            payload_response_only=True
        )
        
        handle_segmentation_error_task = tasks.LambdaInvoke(
            self,
            "HandleSegmentationError",
            lambda_function=error_handler_lambda,
            payload=sfn.TaskInput.from_object({
                "error.$": "$.error",
                "job_id.$": "$.job_id",
                "stage": "segmentation",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.error_handler_result"
        )
        
        image_to_text_task = tasks.LambdaInvoke(
            self,
            "ImageToText",
            lambda_function=vlm_lambda,
            payload=sfn.TaskInput.from_object({
                "job_id.$": "$.job_id",
                "segmentation_result.$": "$.segmentation_result",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.vlm_result",
            retry_on_service_exceptions=True,
            payload_response_only=True
        )
        
        handle_vlm_error_task = tasks.LambdaInvoke(
            self,
            "HandleVLMError",
            lambda_function=error_handler_lambda,
            payload=sfn.TaskInput.from_object({
                "error.$": "$.error",
                "job_id.$": "$.job_id",
                "stage": "vlm_processing",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.error_handler_result"
        )
        
        enhance_with_llm_task = tasks.LambdaInvoke(
            self,
            "EnhanceWithLLM",
            lambda_function=llm_rag_lambda,
            payload=sfn.TaskInput.from_object({
                "job_id.$": "$.job_id",
                "vlm_result.$": "$.vlm_result",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.llm_result",
            retry_on_service_exceptions=True,
            payload_response_only=True
        )
        
        handle_llm_error_task = tasks.LambdaInvoke(
            self,
            "HandleLLMError",
            lambda_function=error_handler_lambda,
            payload=sfn.TaskInput.from_object({
                "error.$": "$.error",
                "job_id.$": "$.job_id",
                "stage": "llm_enhancement",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.error_handler_result"
        )
        
        # Create task for results storage Lambda
        store_results_task = tasks.LambdaInvoke(
            self,
            "StoreResults",
            lambda_function=lambda_.Function.from_function_arn(
                self, "ResultsStorageLambda", results_storage_lambda
            ),
            payload=sfn.TaskInput.from_object({
                "job_id.$": "$.job_id",
                "segmentation_result.$": "$.segmentation_result",
                "vlm_result.$": "$.vlm_result",
                "llm_result.$": "$.llm_result",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.storage_result",
            retry_on_service_exceptions=True,
            payload_response_only=True
        )
        
        handle_storage_error_task = tasks.LambdaInvoke(
            self,
            "HandleStorageError",
            lambda_function=error_handler_lambda,
            payload=sfn.TaskInput.from_object({
                "error.$": "$.error",
                "job_id.$": "$.job_id",
                "stage": "results_storage",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.error_handler_result"
        )
        
        # Create task for notification Lambda
        notify_success_task = tasks.LambdaInvoke(
            self,
            "NotifySuccess",
            lambda_function=lambda_.Function.from_function_arn(
                self, "NotificationLambda", notification_lambda
            ),
            payload=sfn.TaskInput.from_object({
                "job_id.$": "$.job_id",
                "status": "completed",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.notification_result",
            retry_on_service_exceptions=True
        )
        
        fail_execution_task = tasks.LambdaInvoke(
            self,
            "FailExecution",
            lambda_function=lambda_.Function.from_function_arn(
                self, "NotificationLambdaForFailure", notification_lambda
            ),
            payload=sfn.TaskInput.from_object({
                "job_id.$": "$.job_id",
                "status": "failed",
                "error.$": "$.error",
                "execution_id.$": "$.execution_id"
            }),
            result_path="$.notification_result",
            retry_on_service_exceptions=True
        )
        
        # Define the state machine
        definition = segment_image_task \
            .addCatch(handle_segmentation_error_task.next(fail_execution_task), result_path="$.error") \
            .next(image_to_text_task \
                .addCatch(handle_vlm_error_task.next(fail_execution_task), result_path="$.error") \
                .next(enhance_with_llm_task \
                    .addCatch(handle_llm_error_task.next(fail_execution_task), result_path="$.error") \
                    .next(store_results_task \
                        .addCatch(handle_storage_error_task.next(fail_execution_task), result_path="$.error") \
                        .next(notify_success_task))))
        
        # Create the state machine
        self.state_machine = sfn.StateMachine(
            self,
            "MRIAnalysisPipeline",
            definition=definition,
            timeout=Duration.hours(1),
            tracing_enabled=True,
            logs={
                "destination": log_group,
                "level": sfn.LogLevel.ALL,
                "include_execution_data": True
            }
        )
    
    @property
    def state_machine_arn(self) -> str:
        """Get the ARN of the state machine."""
        return self.state_machine.state_machine_arn