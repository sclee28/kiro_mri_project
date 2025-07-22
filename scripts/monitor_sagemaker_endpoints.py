#!/usr/bin/env python
"""
SageMaker Endpoint Monitoring Script.

This script monitors the health and performance of SageMaker endpoints used in the
healthcare image analysis pipeline. It checks endpoint status, invocation metrics,
and model performance, and sends alerts for any issues detected.
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import boto3
from botocore.exceptions import ClientError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SageMakerEndpointMonitor:
    """Monitor SageMaker endpoints for health and performance."""
    
    def __init__(self, region: str = None, endpoints: List[str] = None):
        """
        Initialize the SageMaker endpoint monitor.
        
        Args:
            region: AWS region name (defaults to environment variable or 'us-east-1')
            endpoints: List of endpoint names to monitor (defaults to all endpoints)
        """
        self.region = region or os.environ.get('AWS_REGION', 'us-east-1')
        self.endpoints = endpoints
        
        # Initialize AWS clients
        self.sagemaker_client = boto3.client('sagemaker', region_name=self.region)
        self.cloudwatch_client = boto3.client('cloudwatch', region_name=self.region)
        self.sns_client = boto3.client('sns', region_name=self.region)
        
        # SNS topic for alerts
        self.sns_topic_arn = os.environ.get(
            'ALERT_SNS_TOPIC_ARN', 
            f"arn:aws:sns:{self.region}:{boto3.client('sts').get_caller_identity()['Account']}:sagemaker-model-alerts"
        )
    
    def get_endpoints(self) -> List[Dict[str, Any]]:
        """
        Get a list of SageMaker endpoints.
        
        Returns:
            List of endpoint information dictionaries
        """
        try:
            if self.endpoints:
                # Get specific endpoints
                endpoints = []
                for endpoint_name in self.endpoints:
                    try:
                        response = self.sagemaker_client.describe_endpoint(
                            EndpointName=endpoint_name
                        )
                        endpoints.append(response)
                    except ClientError as e:
                        logger.error(f"Error getting endpoint {endpoint_name}: {e}")
                return endpoints
            else:
                # Get all endpoints
                response = self.sagemaker_client.list_endpoints()
                return response.get('Endpoints', [])
        except ClientError as e:
            logger.error(f"Error listing endpoints: {e}")
            return []
    
    def check_endpoint_status(self, endpoint_name: str) -> Dict[str, Any]:
        """
        Check the status of a SageMaker endpoint.
        
        Args:
            endpoint_name: Name of the SageMaker endpoint
            
        Returns:
            Dictionary with endpoint status information
        """
        try:
            response = self.sagemaker_client.describe_endpoint(
                EndpointName=endpoint_name
            )
            
            status = response.get('EndpointStatus')
            creation_time = response.get('CreationTime')
            last_modified_time = response.get('LastModifiedTime')
            failure_reason = response.get('FailureReason', '')
            
            return {
                'endpoint_name': endpoint_name,
                'status': status,
                'creation_time': creation_time,
                'last_modified_time': last_modified_time,
                'failure_reason': failure_reason,
                'healthy': status == 'InService'
            }
        except ClientError as e:
            logger.error(f"Error checking endpoint {endpoint_name}: {e}")
            return {
                'endpoint_name': endpoint_name,
                'status': 'Unknown',
                'error': str(e),
                'healthy': False
            }
    
    def get_endpoint_metrics(self, endpoint_name: str, hours: int = 1) -> Dict[str, Any]:
        """
        Get CloudWatch metrics for a SageMaker endpoint.
        
        Args:
            endpoint_name: Name of the SageMaker endpoint
            hours: Number of hours to look back for metrics
            
        Returns:
            Dictionary with endpoint metrics
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        
        metrics = {}
        
        # Define metrics to retrieve
        metric_names = [
            'Invocations',
            'InvocationErrors',
            'ModelLatency',
            'OverheadLatency',
            'Invocation4XXErrors',
            'Invocation5XXErrors',
            'CPUUtilization',
            'MemoryUtilization',
            'GPUUtilization',
            'GPUMemoryUtilization',
            'DiskUtilization'
        ]
        
        for metric_name in metric_names:
            try:
                response = self.cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/SageMaker',
                    MetricName=metric_name,
                    Dimensions=[
                        {
                            'Name': 'EndpointName',
                            'Value': endpoint_name
                        },
                        {
                            'Name': 'VariantName',
                            'Value': 'AllTraffic'
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=300,  # 5-minute periods
                    Statistics=['Average', 'Maximum', 'Sum']
                )
                
                datapoints = response.get('Datapoints', [])
                if datapoints:
                    # Sort datapoints by timestamp
                    datapoints.sort(key=lambda x: x['Timestamp'])
                    
                    # Get the most recent datapoint
                    latest = datapoints[-1]
                    
                    metrics[metric_name] = {
                        'average': latest.get('Average', 0),
                        'maximum': latest.get('Maximum', 0),
                        'sum': latest.get('Sum', 0),
                        'timestamp': latest.get('Timestamp')
                    }
                else:
                    metrics[metric_name] = {
                        'average': 0,
                        'maximum': 0,
                        'sum': 0,
                        'timestamp': None
                    }
            except ClientError as e:
                logger.warning(f"Error getting metric {metric_name} for endpoint {endpoint_name}: {e}")
                metrics[metric_name] = {
                    'error': str(e)
                }
        
        return metrics
    
    def check_endpoint_health(self, endpoint_name: str) -> Dict[str, Any]:
        """
        Check the health of a SageMaker endpoint.
        
        Args:
            endpoint_name: Name of the SageMaker endpoint
            
        Returns:
            Dictionary with endpoint health information
        """
        # Get endpoint status
        status_info = self.check_endpoint_status(endpoint_name)
        
        # Get endpoint metrics
        metrics = self.get_endpoint_metrics(endpoint_name)
        
        # Calculate health score based on metrics
        health_score = 100
        health_issues = []
        
        # Check for invocation errors
        invocation_errors = metrics.get('InvocationErrors', {}).get('sum', 0)
        if invocation_errors > 0:
            health_score -= min(50, invocation_errors * 5)  # Deduct up to 50 points
            health_issues.append(f"Invocation errors detected: {invocation_errors}")
        
        # Check for 4XX errors
        errors_4xx = metrics.get('Invocation4XXErrors', {}).get('sum', 0)
        if errors_4xx > 0:
            health_score -= min(30, errors_4xx * 3)  # Deduct up to 30 points
            health_issues.append(f"4XX errors detected: {errors_4xx}")
        
        # Check for 5XX errors
        errors_5xx = metrics.get('Invocation5XXErrors', {}).get('sum', 0)
        if errors_5xx > 0:
            health_score -= min(40, errors_5xx * 4)  # Deduct up to 40 points
            health_issues.append(f"5XX errors detected: {errors_5xx}")
        
        # Check for high latency
        model_latency = metrics.get('ModelLatency', {}).get('average', 0)
        if model_latency > 5000:  # 5 seconds
            health_score -= min(20, (model_latency - 5000) / 1000)  # Deduct up to 20 points
            health_issues.append(f"High model latency: {model_latency:.2f} ms")
        
        # Check for high resource utilization
        cpu_utilization = metrics.get('CPUUtilization', {}).get('average', 0)
        if cpu_utilization > 85:
            health_score -= min(10, (cpu_utilization - 85))  # Deduct up to 10 points
            health_issues.append(f"High CPU utilization: {cpu_utilization:.2f}%")
        
        memory_utilization = metrics.get('MemoryUtilization', {}).get('average', 0)
        if memory_utilization > 85:
            health_score -= min(10, (memory_utilization - 85))  # Deduct up to 10 points
            health_issues.append(f"High memory utilization: {memory_utilization:.2f}%")
        
        gpu_utilization = metrics.get('GPUUtilization', {}).get('average', 0)
        if gpu_utilization > 90:
            health_score -= min(10, (gpu_utilization - 90) * 2)  # Deduct up to 10 points
            health_issues.append(f"High GPU utilization: {gpu_utilization:.2f}%")
        
        # Ensure health score is between 0 and 100
        health_score = max(0, min(100, health_score))
        
        # Determine health status
        if health_score >= 90:
            health_status = 'Healthy'
        elif health_score >= 70:
            health_status = 'Warning'
        else:
            health_status = 'Unhealthy'
        
        return {
            'endpoint_name': endpoint_name,
            'status': status_info['status'],
            'health_score': health_score,
            'health_status': health_status,
            'health_issues': health_issues,
            'metrics': metrics
        }
    
    def send_alert(self, subject: str, message: str) -> bool:
        """
        Send an alert to the SNS topic.
        
        Args:
            subject: Alert subject
            message: Alert message
            
        Returns:
            True if the alert was sent successfully, False otherwise
        """
        try:
            self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Subject=subject,
                Message=message
            )
            logger.info(f"Alert sent: {subject}")
            return True
        except ClientError as e:
            logger.error(f"Error sending alert: {e}")
            return False
    
    def monitor_endpoints(self) -> Dict[str, Any]:
        """
        Monitor all SageMaker endpoints.
        
        Returns:
            Dictionary with monitoring results for all endpoints
        """
        endpoints = self.get_endpoints()
        results = {}
        
        for endpoint in endpoints:
            endpoint_name = endpoint.get('EndpointName')
            if not endpoint_name:
                continue
            
            # Check endpoint health
            health_info = self.check_endpoint_health(endpoint_name)
            results[endpoint_name] = health_info
            
            # Send alerts for unhealthy endpoints
            if health_info['health_status'] != 'Healthy':
                subject = f"SageMaker Endpoint Alert: {endpoint_name} - {health_info['health_status']}"
                message = (
                    f"SageMaker Endpoint: {endpoint_name}\n"
                    f"Status: {health_info['status']}\n"
                    f"Health Score: {health_info['health_score']}\n"
                    f"Health Status: {health_info['health_status']}\n\n"
                    f"Issues:\n"
                )
                for issue in health_info['health_issues']:
                    message += f"- {issue}\n"
                
                self.send_alert(subject, message)
        
        return results


def main():
    """Main function to run the SageMaker endpoint monitor."""
    parser = argparse.ArgumentParser(description='Monitor SageMaker endpoints')
    parser.add_argument('--region', help='AWS region name')
    parser.add_argument('--endpoints', nargs='+', help='List of endpoint names to monitor')
    parser.add_argument('--output', help='Output file for monitoring results (JSON format)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    monitor = SageMakerEndpointMonitor(
        region=args.region,
        endpoints=args.endpoints
    )
    
    results = monitor.monitor_endpoints()
    
    # Print summary
    print("\nSageMaker Endpoint Monitoring Summary:")
    print("=====================================")
    for endpoint_name, info in results.items():
        print(f"Endpoint: {endpoint_name}")
        print(f"Status: {info['status']}")
        print(f"Health Score: {info['health_score']}")
        print(f"Health Status: {info['health_status']}")
        if info['health_issues']:
            print("Issues:")
            for issue in info['health_issues']:
                print(f"  - {issue}")
        print("-------------------------------------")
    
    # Write results to output file if specified
    if args.output:
        try:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"Results written to {args.output}")
        except Exception as e:
            logger.error(f"Error writing results to {args.output}: {e}")
    
    # Return non-zero exit code if any endpoint is unhealthy
    for info in results.values():
        if info['health_status'] == 'Unhealthy':
            return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())