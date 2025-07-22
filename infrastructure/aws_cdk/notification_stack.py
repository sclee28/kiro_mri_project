"""
AWS CDK stack for the notification system.
"""

from aws_cdk import (
    Stack,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    aws_iam as iam
)
from constructs import Construct


class NotificationStack(Stack):
    """
    CDK Stack for the notification system.
    
    This stack creates an SNS topic for sending notifications about
    job completion and other events.
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs
    ) -> None:
        """
        Initialize the stack.
        
        Args:
            scope: CDK construct scope
            construct_id: CDK construct ID
            **kwargs: Additional arguments
        """
        super().__init__(scope, construct_id, **kwargs)
        
        # Create the SNS topic for notifications
        self.notification_topic = sns.Topic(
            self,
            "JobCompletionTopic",
            display_name="Healthcare Image Analysis Job Completion",
            topic_name="healthcare-job-completion"
        )
        
        # Create a policy for the topic
        topic_policy = iam.PolicyStatement(
            actions=["sns:Publish"],
            resources=[self.notification_topic.topic_arn],
            effect=iam.Effect.ALLOW,
            principals=[iam.ServicePrincipal("lambda.amazonaws.com")]
        )
        
        # Add the policy to the topic
        self.notification_topic.add_to_resource_policy(topic_policy)
    
    @property
    def topic(self) -> sns.Topic:
        """Get the SNS topic."""
        return self.notification_topic