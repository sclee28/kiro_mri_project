"""
AWS CDK stack for the results storage and notification Lambda function.
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_sns as sns,
    aws_logs as logs,
    aws_ec2 as ec2
)
from constructs import Construct


class ResultsStorageLambdaStack(Stack):
    """
    CDK Stack for the results storage and notification Lambda function.
    
    This stack creates the Lambda function for storing final analysis results
    in RDS and sending completion notifications.
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        lambda_security_group: ec2.SecurityGroup,
        lambda_role: iam.Role,
        notification_topic: sns.Topic,
        **kwargs
    ) -> None:
        """
        Initialize the stack.
        
        Args:
            scope: CDK construct scope
            construct_id: CDK construct ID
            vpc: VPC for the Lambda function
            lambda_security_group: Security group for the Lambda function
            lambda_role: IAM role for the Lambda function
            notification_topic: SNS topic for notifications
            **kwargs: Additional arguments
        """
        super().__init__(scope, construct_id, **kwargs)
        
        # Create the Lambda function
        results_storage_lambda = lambda_.Function(
            self,
            "ResultsStorageNotificationFunction",
            function_name="healthcare-results-storage-notification",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="src.lambda_functions.results_storage_notification.handler.handler",
            code=lambda_.Code.from_asset("."),
            timeout=Duration.seconds(60),
            memory_size=256,
            environment={
                "NOTIFICATION_TOPIC_ARN": notification_topic.topic_arn,
                "ENABLE_NOTIFICATIONS": "true",
                "LOG_LEVEL": "INFO"
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[lambda_security_group],
            role=lambda_role,
            log_retention=logs.RetentionDays.ONE_WEEK,
            description="Lambda function for storing final analysis results and sending notifications"
        )
        
        # Grant permissions to publish to SNS topic
        notification_topic.grant_publish(results_storage_lambda)
        
        # Output the Lambda ARN
        self.results_storage_lambda_arn = results_storage_lambda.function_arn
    
    @property
    def lambda_arn(self) -> str:
        """Get the ARN of the Lambda function."""
        return self.results_storage_lambda_arn