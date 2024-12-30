"""
Configuration routes for the dashboard application.
Handles configuration management functionality.
"""
from flask import Blueprint, render_template, request, jsonify
import json
import os
import pkg_resources

# Create the blueprint
config = Blueprint('config', __name__)

def get_system_info():
    """
    Get system information including version and other relevant details
    
    Returns:
        dict: Dictionary containing system information
    """
    try:
        version = pkg_resources.get_distribution('anonymous-processing-services').version
    except pkg_resources.DistributionNotFound:
        version = "Development"
    
    return {
        'version': version,
    }

def load_config():
    """
    Load configuration from config file
    """
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'config.yaml')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def save_config(config_data):
    """
    Save configuration to config file
    """
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'config.yaml')
    try:
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

@config.route('/config', methods=['GET', 'POST'])
def manage_config():
    """
    Configuration management page
    """
    if request.method == 'POST':
        config_data = request.get_json()
        if save_config(config_data):
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error'})
    
    return render_template('config.html', 
                         config=load_config(),
                         system_info=get_system_info()) 