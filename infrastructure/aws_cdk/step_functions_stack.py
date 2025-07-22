"""
CDK Stack for Step Functions state machine and related resources.
"""
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as sfn_tasks,
    aws_logs as logs,
    aws_iam as iam,
    Duration,
    RemovalPolicy
)
from constructs import Construct
import json
import os


class StepFunctionsStack(Stack):
    """
    CDK Stack for Step Functions state machine and related resources.
    """

    def __init__(
        self, 
        scope: Construct, 
        construct_id: str, 
        lambda_execution_role: iam.Role,
        vpc,
        shared_layer: _lambda.LayerVersion,
        segmentation_lambda=None,
        vlm_lambda=None,
        llm_rag_lambda=None,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Store the Lambda references
        self.segmentation_lambda = segmentation_lambda
        self.vlm_lambda = vlm_lambda
        self.llm_rag_lambda = llm_rag_lambda
        
        # Create CloudWatch Logs group for Step Functions
        self.step_functions_log_group = logs.LogGroup(
            self, "StepFunctionsLogGroup",
            log_group_name=f"/aws/states/MRIAnalysisPipeline-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_MONTH
        )
        
        # Create Lambda functions for Step Functions workflow
        self.error_handler_lambda = self._create_error_handler_lambda(lambda_execution_role, shared_layer, vpc)
        self.step_functions_trigger_lambda = self._create_step_functions_trigger_lambda(lambda_execution_role, shared_layer, vpc)
        
        # Create Step Functions state machine
        self.state_machine = self._create_state_machine(lambda_execution_role)
        
        # Update the Step Functions trigger Lambda with the state machine ARN
        self.step_functions_trigger_lambda.add_environment(
            "STEP_FUNCTIONS_ARN", 
            self.state_machine.state_machine_arn
        )
        
        # Grant permissions for Step Functions execution
        self.state_machine.grant_start_execution(lambda_execution_role)
        
    def _create_error_handler_lambda(self, execution_role: iam.Role, shared_layer: _lambda.LayerVersion, vpc) -> _lambda.Function:
        """
        Create Lambda function for handling Step Functions errors
        
        Args:
            execution_role: IAM role for Lambda execution
            shared_layer: Shared Lambda layer
            vpc: VPC for Lambda function
            
        Returns:
            Lambda function
        """
        return _lambda.Function(
            self, "StepFunctionsErrorHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("src/lambda_functions/step_functions_error_handler"),
            role=execution_role,
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "AWS_REGION": self.region,
                "CLOUDWATCH_LOG_GROUP": self.step_functions_log_group.log_group_name
            },
            vpc=vpc,
            layers=[shared_layer],
            description="Lambda function for handling Step Functions errors"
        )
    
    def _create_step_functions_trigger_lambda(self, execution_role: iam.Role, shared_layer: _lambda.LayerVersion, vpc) -> _lambda.Function:
        """
        Create Lambda function for triggering Step Functions workflow
        
        Args:
            execution_role: IAM role for Lambda execution
            shared_layer: Shared Lambda layer
            vpc: VPC for Lambda function
            
        Returns:
            Lambda function
        """
        return _lambda.Function(
            self, "StepFunctionsTrigger",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("src/lambda_functions/step_functions_trigger"),
            role=execution_role,
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "AWS_REGION": self.region,
                # STEP_FUNCTIONS_ARN will be set after state machine creation
            },
            vpc=vpc,
            layers=[shared_layer],
            description="Lambda function for triggering Step Functions workflow"
        )
    
    def _create_state_machine(self, execution_role: iam.Role) -> sfn.StateMachine:
        """
        Create Step Functions state machine for MRI image analysis pipeline
        
        Args:
            execution_role: IAM role for state machine execution
            
        Returns:
            Step Functions state machine
        """
        # Load state machine definition from JSON file
        definition_path = os.path.join(
            "src", "lambda_functions", "step_functions_trigger", "state_machine_definition.json"
        )
        
        with open(definition_path, 'r') as f:
            state_machine_definition = json.load(f)
        
        # Replace placeholders in the state machine definition
        if self.segmentation_lambda:
            # Replace the segmentation Lambda ARN placeholder
            state_machine_definition = json.dumps(state_machine_definition).replace(
                "${SegmentationLambdaArn}", 
                self.segmentation_lambda.function_arn
            )
            state_machine_definition = json.loads(state_machine_definition)
            
        if self.vlm_lambda:
            # Replace the VLM Lambda ARN placeholder
            state_machine_definition = json.dumps(state_machine_definition).replace(
                "${VLMLambdaArn}", 
                self.vlm_lambda.function_arn
            )
            state_machine_definition = json.loads(state_machine_definition)
            
        if self.llm_rag_lambda:
            # Replace the LLM RAG Lambda ARN placeholder
            state_machine_definition = json.dumps(state_machine_definition).replace(
                "${LLMRAGLambdaArn}", 
                self.llm_rag_lambda.function_arn
            )
            state_machine_definition = json.loads(state_machine_definition)
        
        # Replace the error handler Lambda ARN placeholder
        state_machine_definition = json.dumps(state_machine_definition).replace(
            "${ErrorHandlerLambdaArn}", 
            self.error_handler_lambda.function_arn
        )
        
        # Replace the log group ARN placeholder
        state_machine_definition = json.dumps(state_machine_definition).replace(
            "${StepFunctionsLogGroupArn}", 
            self.step_functions_log_group.log_group_arn
        )
        
        # Create state machine with CloudWatch logging
        state_machine = sfn.StateMachine(
            self, "MRIAnalysisPipeline",
            definition=sfn.DefinitionBody.from_string(state_machine_definition),
            role=execution_role,
            timeout=Duration.hours(1),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=self.step_functions_log_group,
                level=sfn.LogLevel.ALL,
                include_execution_data=True
            )
        )
        
        # Add permissions for Lambda invocation
        state_machine.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=["*"]  # This should be restricted to specific Lambda functions in production
            )
        )
        
        return state_machine