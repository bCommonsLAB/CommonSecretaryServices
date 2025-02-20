"""
Configuration routes for the dashboard application.
Handles configuration management functionality.
"""
from flask import Blueprint, render_template, request, jsonify
import os
import pkg_resources
from openai import OpenAI
from openai import OpenAIError
import yaml
from typing import Dict, Any, Tuple, Union
from src.core.config_keys import ConfigKeys
from src.utils.logger import get_logger

# Create the blueprint
config = Blueprint('config', __name__)

# Initialize logger
logger = get_logger(process_id="dashboard-config")

def get_system_info() -> Dict[str, str]:
    """
    Get system information including version and other relevant details
    
    Returns:
        Dict[str, str]: Dictionary containing system information
    """
    try:
        version = pkg_resources.get_distribution('anonymous-processing-services').version
    except pkg_resources.DistributionNotFound:
        version = "Development"
    
    return {
        'version': version,
    }

def load_config() -> Dict[str, Any]:
    """
    Load configuration from config file
    
    Returns:
        Dict[str, Any]: The loaded configuration
    """
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'config.yaml')
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Error loading config", error=e)
        return {}

def save_config(config_data: Union[str, Dict[str, Any]]) -> bool:
    """
    Save configuration to config file
    
    Args:
        config_data: Configuration data to save, either as YAML string or dictionary
        
    Returns:
        bool: True if save was successful, False otherwise
    """
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'config.yaml')
    try:
        # Konvertiere String zu YAML wenn nötig
        if isinstance(config_data, str):
            config_data = yaml.safe_load(config_data)
        
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        logger.info("Konfiguration erfolgreich gespeichert", config_path=config_path)
        return True
    except Exception as e:
        logger.error("Fehler beim Speichern der Konfiguration", error=e)
        return False

def test_openai_api_key(api_key: str) -> Tuple[bool, str]:
    """
    Test if the provided OpenAI API key is valid
    
    Args:
        api_key: The OpenAI API key to test
        
    Returns:
        Tuple[bool, str]: (Success status, Message)
    """
    if not api_key:
        return False, "Kein API Key angegeben"
    
    try:
        # Temporärer OpenAI Client nur für den Test
        client = OpenAI(api_key=api_key)
        # Führe einen einfachen API-Aufruf durch
        _ = client.models.list()
        logger.info("OpenAI API Key erfolgreich validiert")
        return True, "API Key ist gültig"
    except OpenAIError as e:
        logger.error("OpenAI API Fehler", error=e)
        return False, f"API Fehler: {str(e)}"
    except Exception as e:
        logger.error("Unerwarteter Fehler bei API Key Test", error=e)
        return False, f"Unerwarteter Fehler: {str(e)}"

@config.route('/config', methods=['GET'])
def config_page() -> str:
    """
    Configuration management page
    
    Returns:
        str: Rendered template
    """
    # Lade aktuelle Konfiguration
    current_config = load_config()
    
    # Hole den API Key aus ConfigKeys
    config_keys = ConfigKeys()
    try:
        raw_api_key = config_keys.openai_api_key
        masked_api_key = f"{raw_api_key[:7]}...{raw_api_key[-5:]}" if raw_api_key and len(raw_api_key) >= 12 else ""
    except ValueError:
        masked_api_key = ""
    
    # Konvertiere zu YAML String für die Anzeige
    config_yaml = yaml.dump(current_config, default_flow_style=False, allow_unicode=True)
    
    # Erstelle Template-Kontext
    context = {
        'config': config_yaml,
        'api_key': masked_api_key,
        'system_info': get_system_info()
    }
    
    return render_template('config.html', **context)

@config.route('/config/api-key', methods=['GET', 'POST'])
def handle_api_key():
    """
    Handle API key operations
    
    Returns:
        Response: JSON response with API key status
    """
    config_keys = ConfigKeys()
    
    if request.method == 'GET':
        try:
            raw_api_key = config_keys.openai_api_key
            # Erstelle maskierten Key
            masked_api_key = f"{raw_api_key[:7]}...{raw_api_key[-5:]}" if len(raw_api_key) >= 12 else raw_api_key
            return jsonify({
                'status': 'success',
                'api_key': masked_api_key
            })
        except ValueError as e:
            logger.error("Fehler beim Laden des API Keys", error=e)
            return jsonify({
                'status': 'error',
                'message': str(e)
            })
        
    # POST request
    try:
        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        
        # Validiere und teste den API Key
        success, message = test_openai_api_key(api_key)
        if not success:
            return jsonify({'status': 'error', 'message': message})
        
        # Speichere den API Key über ConfigKeys
        config_keys.set_openai_api_key(api_key)
        logger.info("OpenAI API Key erfolgreich gespeichert")
        
        return jsonify({
            'status': 'success',
            'message': 'API Key wurde erfolgreich gespeichert und validiert'
        })
    except ValueError as e:
        logger.error("Fehler beim Speichern des API Keys", error=e)
        return jsonify({'status': 'error', 'message': str(e)})
    except Exception as e:
        logger.error("Unerwarteter Fehler beim Speichern des API Keys", error=e)
        return jsonify({'status': 'error', 'message': f'Fehler beim Speichern des API Keys: {str(e)}'})

@config.route('/config/yaml', methods=['POST'])
def update_yaml_config():
    """
    Update the YAML configuration
    
    Returns:
        Response: JSON response indicating success or failure
    """
    try:
        data = request.get_json()
        yaml_content = data.get('config', '')
        
        # Parse YAML um sicherzustellen, dass es gültig ist
        config_data = yaml.safe_load(yaml_content)
        
        # Speichere die Konfiguration
        if save_config(config_data):
            logger.info("YAML Konfiguration erfolgreich aktualisiert")
            return jsonify({
                'status': 'success',
                'message': 'Konfiguration wurde erfolgreich gespeichert'
            })
        return jsonify({
            'status': 'error',
            'message': 'Fehler beim Speichern der Konfiguration'
        })
    except yaml.YAMLError as e:
        logger.error("Ungültiges YAML Format", error=e)
        return jsonify({
            'status': 'error',
            'message': f'Ungültiges YAML Format: {str(e)}'
        })
    except Exception as e:
        logger.error("Fehler beim Aktualisieren der YAML Konfiguration", error=e)
        return jsonify({
            'status': 'error',
            'message': f'Fehler: {str(e)}'
        }) 