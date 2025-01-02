"""
YouTube test route handler
"""
from flask import render_template, request, make_response
import requests
import json
import traceback
import os
import asyncio
from datetime import datetime
from pathlib import Path
from flask import jsonify

from src.utils.logger import get_logger
from src.processors.youtube_processor import YoutubeProcessor
from src.core.resource_tracking import ResourceCalculator

# Initialize logger
logger = get_logger(process_id="dashboard")

def run_youtube_test():
    """
    Run a test for YouTube processing by calling the API endpoint
    """
    logger.info("Starting YouTube test procedure", 
                endpoint="run_youtube_test",
                method=request.method)
    
    try:
        # Get all parameters from the form
        url = request.form.get('youtube_url')
        target_language = request.form.get('target_language', 'en')
        template = request.form.get('template', 'youtube')
        
        if not url:
            logger.error("YouTube URL missing in form data")
            raise ValueError("YouTube URL is required")

        # Prepare the request parameters
        params = {
            'url': url,
            'target_language': target_language,
            'template': template
        }

        # Use the container's own IP address since we're calling ourselves
        host = request.host.split(':')[0]  # Get the host without port
        api_url = f'http://{host}:5000/api/process-youtube'
        logger.info("Calling YouTube API endpoint", 
                   api_url=api_url,
                   params=params)
                   
        response = requests.post(api_url, json=params)
        
        logger.info("Received API response", 
                   status_code=response.status_code,
                   response_headers=dict(response.headers),
                   content_type=response.headers.get('content-type'))

        # Log raw response content for debugging

        if response.status_code != 200:
            try:
                error_data = response.json()
                error_msg = error_data.get('error', 'Unknown error')
            except json.JSONDecodeError as je:
                error_msg = f"Invalid JSON response (Status {response.status_code}): {response.text}"
            
            logger.error("API request failed", 
                        status_code=response.status_code,
                        error_message=error_msg,
                        response_content=response.text[:1000])
            raise ValueError(f"API request failed: {error_msg}")

        api_data = response.json()
        
        test_results = {
            'success': True,
            'message': 'YouTube processing test completed successfully',
            'details': {
                'url': url,
                'test_type': 'youtube_processing',
                'api_response': api_data
            }
        }

        # Create response object to set cookies
        response = make_response(render_template('test_procedures.html', test_results=test_results))
        
        # Set cookies with form values (expire in 30 days)
        max_age = 30 * 24 * 60 * 60  # 30 days in seconds
        response.set_cookie('youtube_last_url', url, max_age=max_age)
        response.set_cookie('youtube_last_language', target_language, max_age=max_age)
        response.set_cookie('youtube_last_template', template, max_age=max_age)
        
        return response
        
    except requests.RequestException as e:
        logger.error("HTTP Request failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    stack_trace=traceback.format_exc())
        raise ValueError(f"HTTP Request failed: {str(e)}")
    
    except Exception as e:
        logger.error("YouTube test failed", 
                    error=str(e),
                    error_type=type(e).__name__,
                    stack_trace=traceback.format_exc())
        test_results = {
            'success': False,
            'message': f'YouTube processing test failed: {str(e)}',
            'details': {
                'error': str(e),
                'error_type': type(e).__name__,
                'stack_trace': traceback.format_exc()
            }
        }
        return render_template('test_procedures.html', test_results=test_results) 