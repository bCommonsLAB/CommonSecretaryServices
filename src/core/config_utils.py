"""
Utility-Funktionen für die Konfigurationsverwaltung.
"""
import os
import re
from typing import Dict, List, Union, Any
from dotenv import load_dotenv

# .env-Datei laden
load_dotenv()

def replace_env_vars(config_dict: Union[Dict[str, Any], List[Any], str, Any]) -> Union[Dict[str, Any], List[Any], str, Any]:
    """
    Ersetzt Variablen im Format ${ENV_VAR} durch Umgebungsvariablen.
    
    Args:
        config_dict: Dictionary oder Liste, in der Umgebungsvariablenreferenzen ersetzt werden sollen
        
    Returns:
        Das modifizierte Dictionary oder die Liste mit ersetzten Umgebungsvariablen
    """
    if isinstance(config_dict, dict):
        for key, value in config_dict.items():
            if isinstance(value, (dict, list)):
                config_dict[key] = replace_env_vars(value)  # type: ignore
            elif isinstance(value, str):
                # Suche nach ${ENV_VAR} Pattern
                env_var_pattern = r'\${([A-Za-z0-9_]+)}'
                matches = re.finditer(env_var_pattern, value)
                for match in matches:
                    env_var = match.group(1)
                    env_value = os.environ.get(env_var)
                    if env_value is not None:
                        # Ersetze nur den gefundenen Teil
                        value = value.replace(f'${{{env_var}}}', env_value)
                config_dict[key] = value
    elif isinstance(config_dict, list):
        for i, item in enumerate(config_dict):
            config_dict[i] = replace_env_vars(item)  # type: ignore
    
    return config_dict 