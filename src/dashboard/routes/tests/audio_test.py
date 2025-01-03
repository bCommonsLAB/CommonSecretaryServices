"""
Audio test route handler
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
from src.processors.audio_processor import AudioProcessor
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

def run_audio_test():
    """
    Run a test for audio processing by calling the API endpoint
    """
    logger.info("Starting Audio test procedure", 
                endpoint="run_audio_test",
                method=request.method)
    
    try:
        if 'audio_file' not in request.files:
            return render_template('test_procedures.html', test_results={
                'success': False,
                'message': 'No audio file provided',
                'details': {'error': 'Missing audio file in request'}
            })
            
        audio_file = request.files['audio_file']
        if audio_file.filename == '':
            raise ValueError("No selected file")
        
        # Get language and summarize parameters
        target_language = request.form.get('target_language', 'en')
        template = request.form.get('template', 'youtube')        
        # Log form data for debugging
        logger.debug("Form data received", 
                    target_language=target_language, 
                    template=template,
                    filename=audio_file.filename)

        # Prepare the multipart form data
        files = {'file': (audio_file.filename, audio_file.stream, audio_file.content_type)}
        data = {
            'target_language': target_language,
            'template': str(template)
        }

        # Use container IP for API URL
        container_ip = get_container_ip()
        api_port = config.get('server.api_port', 5001)  # Fallback auf 5001
        api_base_url = os.getenv('API_URL', f'http://{container_ip}:{api_port}')
        api_url = f"{api_base_url}/api/process-audio"

        # Log request details before sending
        logger.debug("Sending API request", 
                    api_url=api_url,
                    container_ip=container_ip,
                    file_name=audio_file.filename,
                    data=data)

        # Call the audio processing API endpoint
        response = requests.post(api_url, files=files, data=data)
        
        logger.info("Received API response", 
                   status_code=response.status_code,
                   response_headers=dict(response.headers),
                   content_type=response.headers.get('content-type'))

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
            'message': 'Audio processing test completed successfully',
            'details': {
                'filename': audio_file.filename,
                'test_type': 'audio_processing',
                'api_response': api_data
            }
        }

        # Create response object to set cookies
        response = make_response(render_template('test_procedures.html', test_results=test_results))
        
        # Set cookies with form values (expire in 30 days)
        max_age = 30 * 24 * 60 * 60  # 30 days in seconds
        response.set_cookie('audio_last_language', target_language, max_age=max_age)
        
        return response
        
    except requests.RequestException as e:
        logger.error("HTTP Request failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    stack_trace=traceback.format_exc())
        raise ValueError(f"HTTP Request failed: {str(e)}")
    
    except Exception as e:
        logger.error("Audio test failed", 
                    error=str(e),
                    error_type=type(e).__name__,
                    stack_trace=traceback.format_exc())
        test_results = {
            'success': False,
            'message': f'Audio processing test failed: {str(e)}',
            'details': {
                'error': str(e),
                'error_type': type(e).__name__,
                'stack_trace': traceback.format_exc()
            }
        }
        return render_template('test_procedures.html', test_results=test_results) 