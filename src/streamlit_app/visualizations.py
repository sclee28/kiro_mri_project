"""
Visualization utilities for displaying analysis results.

This module provides functions for creating visualizations of analysis results
including charts, graphs, and image overlays.
"""

import json
import logging
from typing import Dict, Any, List, Optional

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import altair as alt

# Configure logging
logger = logging.getLogger(__name__)


def plot_confidence_scores(confidence_scores: Dict[str, float]):
    """
    Create a bar chart of confidence scores.
    
    Args:
        confidence_scores: Dictionary of model names and confidence scores
        
    Returns:
        plotly.graph_objects.Figure: The plotly figure
    """
    if not confidence_scores:
        st.warning("No confidence scores available")
        return None
    
    # Convert to DataFrame
    if isinstance(confidence_scores, str):
        try:
            confidence_scores = json.loads(confidence_scores)
        except json.JSONDecodeError:
            st.error("Invalid confidence scores format")
            return None
    
    df = pd.DataFrame({
        'Model': list(confidence_scores.keys()),
        'Confidence': list(confidence_scores.values())
    })
    
    # Create bar chart
    fig = px.bar(
        df,
        x='Model',
        y='Confidence',
        title='Model Confidence Scores',
        color='Confidence',
        color_continuous_scale='Viridis',
        range_y=[0, 1]
    )
    
    # Customize layout
    fig.update_layout(
        xaxis_title="Model",
        yaxis_title="Confidence Score",
        yaxis=dict(tickformat=".0%"),
        plot_bgcolor='rgba(240, 240, 240, 0.8)'
    )
    
    return fig


def plot_processing_times(processing_metrics: Dict[str, Any]):
    """
    Create a bar chart of processing times.
    
    Args:
        processing_metrics: Dictionary of processing metrics
        
    Returns:
        plotly.graph_objects.Figure: The plotly figure
    """
    if not processing_metrics:
        st.warning("No processing metrics available")
        return None
    
    # Convert to DataFrame
    if isinstance(processing_metrics, str):
        try:
            processing_metrics = json.loads(processing_metrics)
        except json.JSONDecodeError:
            st.error("Invalid processing metrics format")
            return None
    
    # Extract time metrics (those ending with _time_ms)
    time_metrics = {k: v for k, v in processing_metrics.items() if k.endswith('_time_ms')}
    
    if not time_metrics:
        st.warning("No time metrics available")
        return None
    
    # Convert to seconds for better readability
    time_metrics_sec = {k.replace('_time_ms', ''): v / 1000 for k, v in time_metrics.items()}
    
    df = pd.DataFrame({
        'Stage': list(time_metrics_sec.keys()),
        'Time (seconds)': list(time_metrics_sec.values())
    })
    
    # Create bar chart
    fig = px.bar(
        df,
        x='Stage',
        y='Time (seconds)',
        title='Processing Time by Stage',
        color='Time (seconds)',
        color_continuous_scale='Thermal'
    )
    
    # Customize layout
    fig.update_layout(
        xaxis_title="Processing Stage",
        yaxis_title="Time (seconds)",
        plot_bgcolor='rgba(240, 240, 240, 0.8)'
    )
    
    return fig


def create_job_status_chart(jobs: List[Dict[str, Any]]):
    """
    Create a pie chart of job statuses.
    
    Args:
        jobs: List of job dictionaries
        
    Returns:
        plotly.graph_objects.Figure: The plotly figure
    """
    if not jobs:
        st.warning("No jobs available")
        return None
    
    # Count jobs by status
    status_counts = {}
    for job in jobs:
        status = job.get('status', 'unknown').lower()
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Create DataFrame
    df = pd.DataFrame({
        'Status': list(status_counts.keys()),
        'Count': list(status_counts.values())
    })
    
    # Define colors for each status
    status_colors = {
        'uploaded': '#f0f2f6',
        'segmenting': '#ffffd0',
        'converting': '#d0ffff',
        'enhancing': '#d0d0ff',
        'completed': '#d0ffd0',
        'failed': '#ffd0d0',
        'unknown': '#cccccc'
    }
    
    # Create pie chart
    fig = px.pie(
        df,
        values='Count',
        names='Status',
        title='Job Status Distribution',
        color='Status',
        color_discrete_map=status_colors
    )
    
    # Customize layout
    fig.update_layout(
        legend_title="Status",
        plot_bgcolor='rgba(240, 240, 240, 0.8)'
    )
    
    return fig


def create_job_timeline(jobs: List[Dict[str, Any]]):
    """
    Create a timeline of job creation dates.
    
    Args:
        jobs: List of job dictionaries
        
    Returns:
        altair.Chart: The Altair chart
    """
    if not jobs:
        st.warning("No jobs available")
        return None
    
    # Extract creation dates
    job_dates = []
    for job in jobs:
        created_at = job.get('created_at')
        if created_at:
            try:
                # Convert to datetime if it's a string
                if isinstance(created_at, str):
                    import datetime
                    created_at = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                
                job_dates.append({
                    'date': created_at.date().isoformat(),
                    'status': job.get('status', 'unknown').lower()
                })
            except (ValueError, AttributeError):
                continue
    
    if not job_dates:
        st.warning("No valid job dates available")
        return None
    
    # Create DataFrame
    df = pd.DataFrame(job_dates)
    
    # Count jobs by date and status
    df_count = df.groupby(['date', 'status']).size().reset_index(name='count')
    
    # Define colors for each status
    status_colors = {
        'uploaded': '#f0f2f6',
        'segmenting': '#ffffd0',
        'converting': '#d0ffff',
        'enhancing': '#d0d0ff',
        'completed': '#d0ffd0',
        'failed': '#ffd0d0',
        'unknown': '#cccccc'
    }
    
    # Create stacked bar chart
    chart = alt.Chart(df_count).mark_bar().encode(
        x=alt.X('date:T', title='Date'),
        y=alt.Y('count:Q', title='Number of Jobs'),
        color=alt.Color('status:N', scale=alt.Scale(
            domain=list(status_colors.keys()),
            range=list(status_colors.values())
        )),
        tooltip=['date', 'status', 'count']
    ).properties(
        title='Jobs Created by Date',
        width=600,
        height=300
    )
    
    return chart