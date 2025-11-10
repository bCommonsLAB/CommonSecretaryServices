"""
@fileoverview Validation Utilities - Decorators and functions for dataclass validation

@description
Validation utilities for dataclasses. This file provides decorators and functions
used for validating dataclass fields.

Validation is performed via __post_init__ methods that are automatically called
after dataclass initialization.

Features:
- validate_field: Decorator for single field validation
- validate_fields: Decorator for multiple field validations
- Various validation functions (URL, Email, etc.)

@module core.validation

@exports
- validate_field(): Callable - Decorator for field validation
- validate_fields(): Callable - Decorator for multiple field validations
- Various validation functions

@usedIn
- src.core.models.*: Dataclass models use validation decorators
- All model definitions: Validate fields on initialization

@dependencies
- Standard: dataclasses - Dataclass functionality
- Standard: typing - Type annotations and Protocols
- Standard: re - Regular expressions for validation
"""

from typing import (
    TypeVar, Callable, Any, Union, Type, Protocol, Dict, 
    ClassVar, runtime_checkable
)
from dataclasses import Field, fields, is_dataclass
from datetime import datetime
import re

T = TypeVar('T')
ValidatorFunc = Callable[[Any], bool]

@runtime_checkable
class DataclassInstance(Protocol):
    """Protocol für Dataclass-Instanzen."""
    __dataclass_fields__: ClassVar[Dict[str, Field[Any]]]

def validate_field(validation_func: ValidatorFunc, error_msg: str):
    """
    Dekorator für die Validierung einzelner Felder.
    
    Args:
        validation_func: Funktion die den Wert validiert
        error_msg: Fehlermeldung bei ungültigem Wert
    """
    def decorator(cls: Type[T]) -> Type[T]:
        if not is_dataclass(cls):
            raise TypeError(f"{cls.__name__} muss eine Dataclass sein")
            
        original_post_init = getattr(cls, '__post_init__', None)
        
        def __post_init__(self: DataclassInstance) -> None:
            if original_post_init:
                original_post_init(self)
            for field_obj in fields(self):
                value = getattr(self, field_obj.name)
                if not validation_func(value):
                    raise ValueError(f"{field_obj.name}: {error_msg}")
        
        setattr(cls, '__post_init__', __post_init__)
        return cls
    return decorator

def validate_fields(**validators: tuple[ValidatorFunc, str]):
    """
    Dekorator für die Validierung mehrerer Felder.
    
    Args:
        validators: Dict mit Feldnamen und (Validator, Fehlermeldung) Tupeln
    """
    def decorator(cls: Type[T]) -> Type[T]:
        if not is_dataclass(cls):
            raise TypeError(f"{cls.__name__} muss eine Dataclass sein")
            
        original_post_init = getattr(cls, '__post_init__', None)
        
        def __post_init__(self: DataclassInstance) -> None:
            if original_post_init:
                original_post_init(self)
            for field_name, (validator, error_msg) in validators.items():
                if not hasattr(self, field_name):
                    raise ValueError(f"Feld {field_name} existiert nicht in {cls.__name__}")
                value = getattr(self, field_name)
                if not validator(value):
                    raise ValueError(f"{field_name}: {error_msg}")
        
        setattr(cls, '__post_init__', __post_init__)
        return cls
    return decorator

# Validierungs-Funktionen
def is_non_empty_str(value: Any) -> bool:
    """Prüft ob ein Wert ein nicht-leerer String ist."""
    return isinstance(value, str) and bool(value.strip())

def is_positive(value: Union[int, float]) -> bool:
    """Prüft ob ein Wert positiv ist."""
    return value > 0

def is_non_negative(value: Union[int, float]) -> bool:
    """Prüft ob ein Wert nicht negativ ist."""
    return value >= 0

def matches_pattern(pattern: str) -> ValidatorFunc:
    """
    Erstellt einen Validator für reguläre Ausdrücke.
    
    Args:
        pattern: Regex-Pattern für die Validierung
    """
    regex = re.compile(pattern)
    return lambda value: isinstance(value, str) and bool(regex.match(value))

def is_valid_iso_date(value: Any) -> bool:
    """Prüft ob ein String ein gültiges ISO-Datum ist."""
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False

def is_valid_email(value: Any) -> bool:
    """Prüft ob ein String eine gültige E-Mail-Adresse ist."""
    if not isinstance(value, str):
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, value))

def is_valid_url(value: Any) -> bool:
    """Prüft ob ein String eine gültige URL ist."""
    if not isinstance(value, str):
        return False
    pattern = r'^https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&\/=]*)$'
    return bool(re.match(pattern, value))

# Beispiel für die Verwendung:
"""
@validate_fields(
    name=(is_non_empty_str, "Name darf nicht leer sein"),
    age=(is_positive, "Alter muss positiv sein"),
    email=(is_valid_email, "Ungültige E-Mail-Adresse")
)
@dataclass
class User:
    name: str
    age: int
    email: str
""" 