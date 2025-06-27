"""
Transformer test route handler
"""
from flask import render_template, request
import requests
import json
import traceback
import os
import socket
from typing import Dict, Any, Union
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
    Supports both text and URL inputs with optional templates.
    Parameters:
    - input_text: The input text or URL to transform
    - target_language: Target language for translation (e.g. 'en', 'de')
    - template: Optional template name
    - model_type: Whether to translate or summarize
    """
    logger.info("Starting transformer test procedure", 
                endpoint="run_transformer_test",
                method=request.method)
    
    try:
        # Get parameters from form
        input_text: str = request.form.get('input_text', '').strip()
        target_language: str = request.form.get('target_language', 'de')
        template: str = request.form.get('template', '')
        model_type: str = request.form.get('model_type', 'translate')
        
        if not input_text:
            return render_template('test_procedures.html', test_results={
                'success': False,
                'message': 'Missing required parameter',
                'details': {'error': 'Input text or URL is required'}
            })

        # Determine if input is a URL
        is_url: bool = input_text.startswith(('http://', 'https://'))
        
        # Use container IP for API URL
        container_ip: str = get_container_ip()
        api_port: int = config.get('server.api_port', 5001)  # Fallback auf 5001
        api_base_url: str = os.getenv('API_URL', f'http://{container_ip}:{api_port}')
        
        # Choose appropriate API endpoint
        if template:
            # Template-based transformation
            api_url: str = f"{api_base_url}/api/transformer/template"
            params: Dict[str, Any] = {
                'template': template,
                'source_language': 'de',
                'target_language': target_language,
                'use_cache': True
            }
            
            if is_url:
                params['url'] = input_text
            else:
                params['text'] = input_text
                
        else:
            # Simple text transformation
            api_url = f"{api_base_url}/api/transformer/text"
            params = {
                'text': input_text,
                'source_language': 'de',
                'target_language': target_language,
                'summarize': model_type == 'summarize',
                'use_cache': True
            }
        
        # Log the IP and URL being used
        logger.debug("Using API endpoint", 
                    container_ip=container_ip,
                    api_url=api_url,
                    is_url=is_url,
                    template=template)

        # Log request details
        logger.debug("Sending transformer API request", 
                    api_url=api_url,
                    params=params)

        # Call the transformer API endpoint
        response: requests.Response = requests.post(api_url, json=params)
        
        logger.info("Received API response", 
                   status_code=response.status_code,
                   response_headers=dict(response.headers))

        if response.status_code != 200:
            try:
                error_data: Dict[str, Any] = response.json()
                error_msg: str = error_data.get('error', {}).get('message', 'Unknown error')
            except json.JSONDecodeError:
                error_msg = f"Invalid JSON response (Status {response.status_code}): {response.text}"
            
            logger.error("API request failed", 
                        status_code=response.status_code,
                        error_message=error_msg)
            raise ValueError(f"API request failed: {error_msg}")

        api_data: Dict[str, Any] = response.json()

        # Extract result data
        result_data: Any = api_data.get('data', {})
        transformed_text: str = ""
        structured_data: Any = None
        
        if isinstance(result_data, dict):
            # New response format
            output_data: Dict[str, Any] = result_data.get('output', {})
            transformed_text = output_data.get('text', '')
            structured_data = output_data.get('structured_data')
        else:
            # Legacy response format
            transformed_text = result_data.get('transformed_text', '')
            structured_data = None

        # Prepare test results
        details: Dict[str, Any] = {
            'test_type': 'transformer_processing',
            'input_type': 'URL' if is_url else 'Text',
            'input': input_text[:100] + '...' if len(input_text) > 100 else input_text,
            'transformed_text': transformed_text[:200] + '...' if len(transformed_text) > 200 else transformed_text,
            'original_length': len(input_text),
            'transformed_length': len(transformed_text),
            'target_language': target_language,
            'template': template if template else 'None',
            'model_type': model_type,
            'process_id': api_data.get('process', {}).get('id', ''),
            'duration': api_data.get('process', {}).get('duration_ms', 0),
            'is_from_cache': api_data.get('process', {}).get('is_from_cache', False)
        }
        
        if structured_data:
            details['has_structured_data'] = True
            details['structured_fields'] = list(structured_data.keys()) if isinstance(structured_data, dict) else 'Yes'

        test_results: Dict[str, Any] = {
            'success': api_data.get('status') == 'success',
            'message': f'{"URL" if is_url else "Text"} transformation completed successfully',
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
            'message': f'Transformation failed: {str(e)}',
            'details': {
                'error': str(e),
                'error_type': type(e).__name__,
                'stack_trace': traceback.format_exc()
            }
        })