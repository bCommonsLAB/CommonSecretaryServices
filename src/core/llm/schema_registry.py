"""
@fileoverview Schema Registry - Verwaltung bekannter JSON Schemas

@description
Zentrale Registry für bekannte JSON Schemas, die über schema_id referenziert werden können.
Für MVP: Einfaches Dictionary im Code. Später kann dies in MongoDB oder config.yaml migriert werden.

@module core.llm.schema_registry

@exports
- KNOWN_SCHEMAS: Dictionary mit bekannten Schemas
- get_schema: Funktion zum Abrufen eines Schemas
"""

from typing import Dict, Any, Optional


# Bekannte JSON Schemas
# Später kann dies in MongoDB oder config.yaml migriert werden
KNOWN_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "metadata": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "author": {"type": "string"},
            "description": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "date": {"type": "string"},
            "language": {"type": "string"}
        },
        "required": []
    },
    "meeting_minutes": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "participants": {"type": "array", "items": {"type": "string"}},
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "assignee": {"type": "string"},
                        "due_date": {"type": "string"}
                    },
                    "required": ["task"]
                }
            },
            "date": {"type": "string"}
        },
        "required": ["summary"]
    }
}


def get_schema(schema_id: str) -> Optional[Dict[str, Any]]:
    """
    Ruft ein Schema aus der Registry ab.
    
    Args:
        schema_id: ID des Schemas (z.B. "metadata", "meeting_minutes")
        
    Returns:
        Optional[Dict[str, Any]]: Schema-Dictionary oder None wenn nicht gefunden
    """
    return KNOWN_SCHEMAS.get(schema_id)

