"""
@fileoverview LLM Test Case Loader - Loads test cases from JSON files

@description
Loads LLM test cases from JSON files in the config/tests/ directory.
Validates the JSON structure and returns LLMTestCase instances.

@module core.llm.test_case_loader

@exports
- load_test_cases: Function - Loads all test cases for a use case
- load_test_case: Function - Loads a specific test case
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..models.llm_test import LLMTestCase
from ..exceptions import ProcessingError


def get_tests_directory() -> Path:
    """
    Gibt das Verzeichnis für Test-Cases zurück.
    
    Returns:
        Path: Pfad zum tests-Verzeichnis (config/tests/)
    """
    # Gehe vom Projekt-Root aus (wo config/ liegt)
    project_root = Path(__file__).parents[3]  # Von src/core/llm/ zu Projekt-Root
    tests_dir = project_root / 'config' / 'tests'
    return tests_dir


def load_test_case(use_case: str, size: str) -> Optional[LLMTestCase]:
    """
    Lädt einen spezifischen Test-Case aus einer JSON-Datei.
    
    Args:
        use_case: Name des Use-Cases (z.B. 'chat_completion')
        size: Größe des Tests ('small', 'medium', 'large')
        
    Returns:
        Optional[LLMTestCase]: Test-Case oder None wenn nicht gefunden
        
    Raises:
        ProcessingError: Bei Fehlern beim Laden oder Validieren
    """
    tests_dir = get_tests_directory()
    filename = f"{use_case}_{size}.json"
    file_path = tests_dir / filename
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validiere, dass use_case und size übereinstimmen
        if data.get('use_case') != use_case:
            raise ProcessingError(
                f"Test-Case in {filename} hat falschen use_case: "
                f"erwartet '{use_case}', gefunden '{data.get('use_case')}'"
            )
        if data.get('size') != size:
            raise ProcessingError(
                f"Test-Case in {filename} hat falsche size: "
                f"erwartet '{size}', gefunden '{data.get('size')}'"
            )
        
        return LLMTestCase.from_dict(data)
        
    except json.JSONDecodeError as e:
        raise ProcessingError(
            f"Ungültiges JSON in Test-Case-Datei {filename}: {str(e)}"
        ) from e
    except Exception as e:
        raise ProcessingError(
            f"Fehler beim Laden des Test-Cases {filename}: {str(e)}"
        ) from e


def load_test_cases(use_case: str) -> Dict[str, LLMTestCase]:
    """
    Lädt alle Test-Cases für einen Use-Case.
    
    Args:
        use_case: Name des Use-Cases (z.B. 'chat_completion')
        
    Returns:
        Dict[str, LLMTestCase]: Dictionary mit size -> Test-Case Mapping
        
    Raises:
        ProcessingError: Bei Fehlern beim Laden
    """
    test_cases: Dict[str, LLMTestCase] = {}
    
    # Versuche alle drei Größen zu laden
    for size in ['small', 'medium', 'large']:
        test_case = load_test_case(use_case, size)
        if test_case:
            test_cases[size] = test_case
    
    return test_cases


def list_available_test_cases() -> Dict[str, List[str]]:
    """
    Listet alle verfügbaren Test-Cases auf.
    
    Returns:
        Dict[str, List[str]]: Dictionary mit use_case -> Liste von verfügbaren sizes
    """
    tests_dir = get_tests_directory()
    
    if not tests_dir.exists():
        return {}
    
    available: Dict[str, List[str]] = {}
    
    # Durchsuche alle JSON-Dateien im tests-Verzeichnis
    for file_path in tests_dir.glob('*.json'):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            use_case = data.get('use_case')
            size = data.get('size')
            
            if use_case and size:
                if use_case not in available:
                    available[use_case] = []
                if size not in available[use_case]:
                    available[use_case].append(size)
        except Exception:
            # Überspringe ungültige Dateien
            continue
    
    return available

