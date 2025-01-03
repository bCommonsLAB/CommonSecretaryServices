"""
Youtube test route handler
"""
from flask import render_template, request, make_response
import requests
import json
import traceback
import os
import asyncio
import socket
from datetime import datetime
from pathlib import Path
from flask import jsonify

from src.utils.logger import get_logger
from src.processors.youtube_processor import YoutubeProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.config import Config

# Initialize logger
logger = get_logger(process_id="dashboard")
config = Config()

def get_container_ip():
    """Get the container's IP address"""
    try:
        # Get the container's hostname
        hostname = socket.gethostname()
        # Get the IP address
        ip_address = socket.gethostbyname(hostname)
        return ip_address
    except Exception:
        return "localhost"  # Fallback to localhost if IP detection fails

def run_youtube_test():
    """
    Run a test for Youtube processing by calling the API endpoint
    """
    logger.info("Starting Youtube test procedure", 
                endpoint="run_youtube_test",
                method=request.method)
    
    try:
        # Get all parameters from the form
        url = request.form.get('youtube_url')
        target_language = request.form.get('target_language', 'en')
        template = request.form.get('template', 'youtube')
        
        if not url:
            logger.error("Youtube URL missing in form data")
            raise ValueError("Youtube URL is required")

        # Prepare the request parameters
        params = {
            'url': url,
            'target_language': target_language,
            'template': template
        }

        # Use container IP for API URL
        container_ip = get_container_ip()
        api_port = config.get('server.api_port', 5001)  # Fallback auf 5001
        api_base_url = os.getenv('API_URL', f'http://{container_ip}:{api_port}')
        api_url = f"{api_base_url}/api/process-youtube"
        
        logger.info("Calling Youtube API endpoint", 
                   api_url=api_url,
                   container_ip=container_ip,
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
            'message': 'Youtube processing test completed successfully',
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
        logger.error("Youtube test failed", 
                    error=str(e),
                    error_type=type(e).__name__,
                    stack_trace=traceback.format_exc())
        test_results = {
            'success': False,
            'message': f'Youtube processing test failed: {str(e)}',
            'details': {
                'error': str(e),
                'error_type': type(e).__name__,
                'stack_trace': traceback.format_exc()
            }
        }
        return render_template('test_procedures.html', test_results=test_results) 