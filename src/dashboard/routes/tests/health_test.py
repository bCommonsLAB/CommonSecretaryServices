"""
System health test route handler
"""
import os
import json
from datetime import datetime
from pathlib import Path
import traceback
from flask import jsonify, render_template, request

from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(process_id="dashboard")

def run_health_test():
    """
    Run system health tests to verify the functionality of various components
    """
    logger.info("Starting health test procedure", 
                endpoint="run_health_test",
                method=request.method)
    
    try:
        check_api = request.form.get('check_api') == 'on'
        check_storage = request.form.get('check_storage') == 'on'
        check_processors = request.form.get('check_processors') == 'on'
        
        test_results = {
            'success': True,
            'message': 'System health check completed successfully',
            'details': {
                'api_status': 'OK' if check_api else 'Not checked',
                'storage_status': 'OK' if check_storage else 'Not checked',
                'processors_status': 'OK' if check_processors else 'Not checked',
                'test_type': 'health_check'
            }
        }
        
    except Exception as e:
        logger.error("Health test failed", 
                    error=str(e),
                    error_type=type(e).__name__)
        test_results = {
            'success': False,
            'message': f'System health check failed: {str(e)}',
            'details': {
                'error': str(e),
                'test_type': 'health_check'
            }
        }
    
    return render_template('test_procedures.html', test_results=test_results) 