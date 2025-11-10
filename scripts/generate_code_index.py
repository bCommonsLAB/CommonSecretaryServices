#!/usr/bin/env python3
"""
Script zur automatischen Generierung eines Code-Index aus JSDoc-Header-Dokumentation.

Dieses Script scannt alle Python-Dateien in src/ und extrahiert die JSDoc-Header-Dokumentation,
um einen strukturierten Index zu erstellen.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

@dataclass
class FileInfo:
    """Informationen über eine Datei aus der Header-Dokumentation."""
    path: str
    module: str = ""
    fileoverview: str = ""
    description: str = ""
    exports: List[str] = field(default_factory=list)
    used_in: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    category: str = ""

def parse_jsdoc_header(file_path: Path) -> Optional[FileInfo]:
    """
    Parst die JSDoc-Header-Dokumentation aus einer Python-Datei.
    
    Args:
        file_path: Pfad zur Python-Datei
        
    Returns:
        FileInfo-Objekt mit extrahierten Informationen oder None
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None
    
    # Suche nach dem Docstring am Anfang der Datei
    docstring_match = re.search(r'^"""(.*?)"""', content, re.DOTALL | re.MULTILINE)
    if not docstring_match:
        return None
    
    docstring = docstring_match.group(1)
    
    # Extrahiere @fileoverview
    fileoverview_match = re.search(r'@fileoverview\s+(.+?)(?=\n@|\n\n|$)', docstring, re.DOTALL)
    fileoverview = fileoverview_match.group(1).strip() if fileoverview_match else ""
    
    # Extrahiere @description
    desc_match = re.search(r'@description\s+(.+?)(?=\n@|\n\n|$)', docstring, re.DOTALL)
    description = desc_match.group(1).strip() if desc_match else ""
    
    # Extrahiere @module
    module_match = re.search(r'@module\s+(.+?)(?=\n@|\n\n|$)', docstring, re.DOTALL)
    module = module_match.group(1).strip() if module_match else ""
    
    # Extrahiere @exports
    exports_match = re.search(r'@exports\s+(.+?)(?=\n@|\n\n|$)', docstring, re.DOTALL)
    exports_text = exports_match.group(1).strip() if exports_match else ""
    exports = [line.strip().lstrip('- ') for line in exports_text.split('\n') if line.strip()]
    
    # Extrahiere @usedIn
    used_in_match = re.search(r'@usedIn\s+(.+?)(?=\n@|\n\n|$)', docstring, re.DOTALL)
    used_in_text = used_in_match.group(1).strip() if used_in_match else ""
    used_in = [line.strip().lstrip('- ') for line in used_in_text.split('\n') if line.strip()]
    
    # Extrahiere @dependencies
    deps_match = re.search(r'@dependencies\s+(.+?)(?=\n@|\n\n|$)', docstring, re.DOTALL)
    deps_text = deps_match.group(1).strip() if deps_match else ""
    dependencies = [line.strip().lstrip('- ') for line in deps_text.split('\n') if line.strip()]
    
    # Bestimme Kategorie basierend auf Pfad
    path_str = str(file_path)
    if 'main.py' in path_str or 'app.py' in path_str:
        category = "Entry Points"
    elif 'core/config' in path_str:
        category = "Core - Configuration"
    elif 'core/exceptions' in path_str:
        category = "Core - Exceptions"
    elif 'core/validation' in path_str:
        category = "Core - Validation"
    elif 'core/models' in path_str:
        category = "Core - Models"
    elif 'core/mongodb' in path_str:
        category = "Core - MongoDB"
    elif 'processors/base' in path_str:
        category = "Processors - Base"
    elif 'processors/' in path_str:
        category = "Processors"
    elif 'api/routes' in path_str:
        category = "API - Routes"
    elif 'dashboard/routes' in path_str:
        category = "Dashboard - Routes"
    elif 'utils/' in path_str:
        category = "Utilities"
    else:
        category = "Other"
    
    return FileInfo(
        path=str(file_path.relative_to(Path('src').parent)),
        module=module,
        fileoverview=fileoverview,
        description=description,
        exports=exports,
        used_in=used_in,
        dependencies=dependencies,
        category=category
    )

def scan_src_directory(src_dir: Path = Path('src')) -> List[FileInfo]:
    """
    Scannt das src-Verzeichnis nach Python-Dateien und extrahiert Header-Dokumentation.
    
    Args:
        src_dir: Pfad zum src-Verzeichnis
        
    Returns:
        Liste von FileInfo-Objekten
    """
    file_infos: List[FileInfo] = []
    
    for py_file in src_dir.rglob('*.py'):
        # Überspringe __pycache__ und andere spezielle Verzeichnisse
        if '__pycache__' in str(py_file) or '.pyc' in str(py_file):
            continue
        
        file_info = parse_jsdoc_header(py_file)
        if file_info:
            file_infos.append(file_info)
    
    return file_infos

def generate_markdown_index(file_infos: List[FileInfo]) -> str:
    """
    Generiert Markdown-Index aus FileInfo-Objekten.
    
    Args:
        file_infos: Liste von FileInfo-Objekten
        
    Returns:
        Markdown-String mit Index-Tabelle
    """
    # Gruppiere nach Kategorien
    categories: Dict[str, List[FileInfo]] = {}
    for file_info in file_infos:
        if file_info.category not in categories:
            categories[file_info.category] = []
        categories[file_info.category].append(file_info)
    
    # Sortiere Kategorien
    category_order = [
        "Entry Points",
        "Core - Configuration",
        "Core - Exceptions",
        "Core - Validation",
        "Core - Models",
        "Core - MongoDB",
        "Processors - Base",
        "Processors",
        "API - Routes",
        "Dashboard - Routes",
        "Utilities",
        "Other"
    ]
    
    markdown = "# Code-Index\n\n"
    markdown += "Automatisch generierter Index aller dokumentierten Python-Dateien.\n\n"
    markdown += "## Übersicht\n\n"
    markdown += f"Gesamt: {len(file_infos)} dokumentierte Dateien\n\n"
    
    # Generiere Tabelle pro Kategorie
    for category in category_order:
        if category not in categories:
            continue
        
        files = sorted(categories[category], key=lambda x: x.path)
        markdown += f"## {category}\n\n"
        markdown += "| Datei | Modul | Beschreibung | Exports |\n"
        markdown += "|-------|-------|--------------|----------|\n"
        
        for file_info in files:
            # Kürze Beschreibung auf 100 Zeichen
            desc = file_info.fileoverview[:100] + "..." if len(file_info.fileoverview) > 100 else file_info.fileoverview
            # Kürze Exports auf 3 Einträge
            exports_str = ", ".join(file_info.exports[:3])
            if len(file_info.exports) > 3:
                exports_str += f" (+{len(file_info.exports) - 3} weitere)"
            
            markdown += f"| `{file_info.path}` | {file_info.module} | {desc} | {exports_str} |\n"
        
        markdown += "\n"
    
    # Füge nicht-kategorisierte Dateien hinzu
    other_categories = [cat for cat in categories.keys() if cat not in category_order]
    if other_categories:
        markdown += "## Weitere Kategorien\n\n"
        for category in sorted(other_categories):
            files = sorted(categories[category], key=lambda x: x.path)
            markdown += f"### {category}\n\n"
            markdown += "| Datei | Modul | Beschreibung | Exports |\n"
            markdown += "|-------|-------|--------------|----------|\n"
            
            for file_info in files:
                desc = file_info.fileoverview[:100] + "..." if len(file_info.fileoverview) > 100 else file_info.fileoverview
                exports_str = ", ".join(file_info.exports[:3])
                if len(file_info.exports) > 3:
                    exports_str += f" (+{len(file_info.exports) - 3} weitere)"
                
                markdown += f"| `{file_info.path}` | {file_info.module} | {desc} | {exports_str} |\n"
            
            markdown += "\n"
    
    return markdown

def main():
    """Hauptfunktion zum Generieren des Index."""
    src_dir = Path('src')
    if not src_dir.exists():
        print(f"Fehler: {src_dir} existiert nicht!")
        return
    
    print("Scanne src-Verzeichnis nach Python-Dateien...")
    file_infos = scan_src_directory(src_dir)
    
    print(f"Gefunden: {len(file_infos)} dokumentierte Dateien")
    
    # Generiere Markdown
    markdown = generate_markdown_index(file_infos)
    
    # Speichere Index
    output_path = Path('docs/reference/code-index.md')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown)
    
    print(f"Index gespeichert: {output_path}")

if __name__ == '__main__':
    main()

