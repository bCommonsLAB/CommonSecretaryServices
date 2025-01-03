"""
Transformer test route handler
"""
from flask import render_template, request
import requests
import json
import traceback
import os
import socket
from datetime import datetime
from pathlib import Path
from flask import jsonify

from src.utils.logger import get_logger
from src.processors.transformer_processor import TransformerProcessor
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

def run_transformer_test():
    """
    Handle transformer processing test requests.
    Sends text to the transform-text API endpoint for processing.
    Parameters:
    - text: The input text to transform
    - target_language: Target language for translation (e.g. 'en', 'de')
    - summarize: Whether to generate a summary (boolean)
    """
    logger.info("Starting transformer test procedure", 
                endpoint="run_transformer_test",
                method=request.method)
    
    try:
        # Get parameters from form
        text = request.form.get('input_text')
        target_language = request.form.get('target_language', 'de')
        summarize = request.form.get('model_type') == 'summarize'
        
        if not text:
            return render_template('test_procedures.html', test_results={
                'success': False,
                'message': 'Missing required parameter',
                'details': {'error': 'Input text is required'}
            })

        # Use container IP for API URL
        container_ip = get_container_ip()
        api_port = config.get('server.api_port', 5001)  # Fallback auf 5001
        api_base_url = os.getenv('API_URL', f'http://{container_ip}:{api_port}')
        api_url = f"{api_base_url}/api/transform-text"
        
        # Log the IP and URL being used
        logger.debug("Using API endpoint", 
                    container_ip=container_ip,
                    api_url=api_url)

        params = {
            'text': text,
            'target_language': target_language,
            'summarize': summarize
        }

        # Log request details
        logger.debug("Sending transformer API request", 
                    api_url=api_url,
                    params=params)

        # Call the transformer API endpoint
        response = requests.post(api_url, json=params)
        
        logger.info("Received API response", 
                   status_code=response.status_code,
                   response_headers=dict(response.headers))

        if response.status_code != 200:
            try:
                error_data = response.json()
                error_msg = error_data.get('error', 'Unknown error')
            except json.JSONDecodeError:
                error_msg = f"Invalid JSON response (Status {response.status_code}): {response.text}"
            
            logger.error("API request failed", 
                        status_code=response.status_code,
                        error_message=error_msg)
            raise ValueError(f"API request failed: {error_msg}")

        api_data = response.json()

        # Prepare test results
        details = {
            'test_type': 'transformer_processing',
            'original_text': text,
            'transformed_text': api_data.get('text', ''),
            'original_length': len(text),
            'transformed_length': len(api_data.get('text', '')),
            'target_language': target_language,
            'summarize': summarize,
            'token_count': api_data.get('token_count', 0),
            'model': api_data.get('model', '')
        }

        test_results = {
            'success': True,
            'message': 'Text transformation completed successfully',
            'details': details
        }

        return render_template('test_procedures.html', test_results=test_results)

    except Exception as e:
        logger.error("Transformer test failed", 
                    error=str(e),
                    error_type=type(e).__name__,
                    stack_trace=traceback.format_exc())
        return render_template('test_procedures.html', test_results={
            'success': False,
            'message': f'Text transformation failed: {str(e)}',
            'details': {
                'error': str(e),
                'error_type': type(e).__name__,
                'stack_trace': traceback.format_exc()
            }
        })