"""
@fileoverview Configuration Utilities - Helper functions for configuration processing

@description
Utility functions for configuration management. This file provides functions used
in processing configuration files.

Main functionality:
- replace_env_vars: Replaces ${ENV_VAR} placeholders in configuration values with
  actual environment variable values
- load_dotenv: Loads environment variables from .env file

The replace_env_vars function supports nested dictionaries and lists and recursively
replaces all environment variable references.

@module core.config_utils

@exports
- replace_env_vars(): Union[Dict, List, str, Any] - Replaces environment variables in configuration
- load_dotenv(): None - Loads .env file

@usedIn
- src.core.config: Uses replace_env_vars for configuration processing
- All modules loading configuration: Use replace_env_vars

@dependencies
- External: dotenv - Loading .env file
- System: os.environ - Environment variable access
- Standard: re - Regular expressions for pattern matching
"""
import os
import re
from typing import Dict, List, Union, Any, overload, cast
from dotenv import load_dotenv

# .env-Datei laden
load_dotenv()

NestedConfig = Union[Dict[str, Any], List[Any]]

@overload
def replace_env_vars(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    ...

@overload
def replace_env_vars(config_dict: List[Any]) -> List[Any]:
    ...

@overload
def replace_env_vars(config_dict: str) -> str:  # pragma: no cover - für Typing-Präzisierung
    ...

@overload
def replace_env_vars(config_dict: Any) -> Any:  # pragma: no cover - Fallback
    ...

def replace_env_vars(config_dict: Union[Dict[str, Any], List[Any], str, Any]) -> Union[Dict[str, Any], List[Any], str, Any]:
    """
    Ersetzt Variablen im Format ${ENV_VAR} durch Umgebungsvariablen.
    
    Args:
        config_dict: Dictionary oder Liste, in der Umgebungsvariablenreferenzen ersetzt werden sollen
        
    Returns:
        Das modifizierte Dictionary oder die Liste mit ersetzten Umgebungsvariablen
    """
    if isinstance(config_dict, dict):
        dict_obj: Dict[str, Any] = cast(Dict[str, Any], config_dict)
        for key, value in list(dict_obj.items()):
            if isinstance(value, (dict, list)):
                dict_obj[key] = replace_env_vars(value)  # type: ignore[assignment]
            elif isinstance(value, str):
                # Suche nach ${ENV_VAR} Pattern
                env_var_pattern = r'\${([A-Za-z0-9_]+)}'
                new_value = value
                matches = re.finditer(env_var_pattern, value)
                for match in matches:
                    env_var = match.group(1)
                    env_value = os.environ.get(env_var)
                    if env_value is not None:
                        # Ersetze nur den gefundenen Teil
                        new_value = new_value.replace(f'${{{env_var}}}', env_value)
                dict_obj[key] = new_value
        return dict_obj
    elif isinstance(config_dict, list):
        list_obj: List[Any] = []
        for item in config_dict:
            processed_item: Union[Dict[str, Any], List[Any], str, Any] = replace_env_vars(
                cast(Union[Dict[str, Any], List[Any], str, Any], item)
            )
            list_obj.append(cast(Any, processed_item))
        return list_obj
    
    return config_dict