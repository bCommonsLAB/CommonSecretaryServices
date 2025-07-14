"""
Test-Skript für die LLM-basierte OCR-Integration.
Testet sowohl PDF- als auch Image-OCR mit verschiedenen Extraktionsmethoden.
"""

import os
import sys
import json
import requests
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Füge src-Verzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_pdf_llm_ocr(api_base_url: str = "http://localhost:8000", 
                     test_file: str = "tests/samples/sample.pdf") -> Dict[str, Any]:
    """
    Testet die LLM-basierte OCR für PDF-Dateien.
    
    Args:
        api_base_url: Basis-URL der API
        test_file: Pfad zur Test-PDF-Datei
        
    Returns:
        Dict mit Testergebnissen
    """
    print("🧪 Teste PDF LLM-OCR Integration...")
    
    # Überprüfe, ob die Testdatei existiert
    if not os.path.exists(test_file):
        print(f"❌ Testdatei nicht gefunden: {test_file}")
        return {"error": "Test file not found"}
    
    # Teste verschiedene LLM-Extraktionsmethoden
    extraction_methods = ["llm", "llm_and_native", "llm_and_ocr"]
    results = {}
    
    for method in extraction_methods:
        print(f"\n📄 Teste PDF-Verarbeitung mit Methode: {method}")
        
        try:
            # Bereite die API-Anfrage vor
            url = f"{api_base_url}/api/pdf/process"
            
            with open(test_file, 'rb') as f:
                files = {'file': f}
                data = {
                    'extraction_method': method,
                    'useCache': 'false',  # Für Tests Cache deaktivieren
                    'context': json.dumps({
                        'document_type': 'technical',
                        'language': 'de',
                        'expected_content': 'mixed_text_and_images'
                    })
                }
                
                # Sende die Anfrage
                print(f"🔄 Sende Anfrage an: {url}")
                response = requests.post(url, files=files, data=data, timeout=300)
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"✅ Erfolgreich verarbeitet mit {method}")
                    
                    # Analysiere das Ergebnis
                    if 'data' in result and 'pages' in result['data']:
                        pages = result['data']['pages']
                        print(f"📊 Verarbeitete Seiten: {len(pages)}")
                        
                        # Überprüfe, ob LLM-Text extrahiert wurde
                        llm_text_found = False
                        for page in pages:
                            if 'llm_text' in page and page['llm_text']:
                                llm_text_found = True
                                print(f"📝 LLM-Text gefunden auf Seite {page.get('page_number', '?')}")
                                print(f"   Textlänge: {len(page['llm_text'])} Zeichen")
                                # Zeige ersten Teil des Texts
                                preview = page['llm_text'][:200] + "..." if len(page['llm_text']) > 200 else page['llm_text']
                                print(f"   Vorschau: {preview}")
                                break
                        
                        if not llm_text_found:
                            print("⚠️  Kein LLM-Text gefunden")
                    
                    results[method] = {
                        'status': 'success',
                        'response': result,
                        'processing_time': result.get('process', {}).get('completed', 'unknown')
                    }
                    
                else:
                    print(f"❌ Fehler: {response.status_code} - {response.text}")
                    results[method] = {
                        'status': 'error',
                        'error': response.text,
                        'status_code': response.status_code
                    }
                    
        except Exception as e:
            print(f"❌ Exception bei {method}: {str(e)}")
            results[method] = {
                'status': 'exception',
                'error': str(e)
            }
    
    return results

def test_image_llm_ocr(api_base_url: str = "http://localhost:8000", 
                       test_file: str = "tests/samples/diagramm.jpg") -> Dict[str, Any]:
    """
    Testet die LLM-basierte OCR für Bilddateien.
    
    Args:
        api_base_url: Basis-URL der API
        test_file: Pfad zur Test-Bilddatei
        
    Returns:
        Dict mit Testergebnissen
    """
    print("\n🧪 Teste Image LLM-OCR Integration...")
    
    # Überprüfe, ob die Testdatei existiert
    if not os.path.exists(test_file):
        print(f"❌ Testdatei nicht gefunden: {test_file}")
        return {"error": "Test file not found"}
    
    # Teste verschiedene LLM-Extraktionsmethoden
    extraction_methods = ["llm", "llm_and_ocr"]
    results = {}
    
    for method in extraction_methods:
        print(f"\n🖼️  Teste Bild-Verarbeitung mit Methode: {method}")
        
        try:
            # Bereite die API-Anfrage vor
            url = f"{api_base_url}/api/imageocr/process"
            
            with open(test_file, 'rb') as f:
                files = {'file': f}
                data = {
                    'extraction_method': method,
                    'useCache': 'false',  # Für Tests Cache deaktivieren
                    'context': json.dumps({
                        'document_type': 'diagram',
                        'language': 'de',
                        'expected_content': 'technical_diagram'
                    })
                }
                
                # Sende die Anfrage
                print(f"🔄 Sende Anfrage an: {url}")
                response = requests.post(url, files=files, data=data, timeout=300)
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"✅ Erfolgreich verarbeitet mit {method}")
                    
                    # Analysiere das Ergebnis
                    if 'data' in result:
                        data_result = result['data']
                        
                        # Überprüfe verschiedene Texttypen
                        text_types = ['llm_text', 'extracted_text', 'formatted_text']
                        for text_type in text_types:
                            if text_type in data_result and data_result[text_type]:
                                print(f"📝 {text_type} gefunden:")
                                print(f"   Textlänge: {len(data_result[text_type])} Zeichen")
                                # Zeige ersten Teil des Texts
                                preview = data_result[text_type][:200] + "..." if len(data_result[text_type]) > 200 else data_result[text_type]
                                print(f"   Vorschau: {preview}")
                    
                    results[method] = {
                        'status': 'success',
                        'response': result,
                        'processing_time': result.get('process', {}).get('completed', 'unknown')
                    }
                    
                else:
                    print(f"❌ Fehler: {response.status_code} - {response.text}")
                    results[method] = {
                        'status': 'error',
                        'error': response.text,
                        'status_code': response.status_code
                    }
                    
        except Exception as e:
            print(f"❌ Exception bei {method}: {str(e)}")
            results[method] = {
                'status': 'exception',
                'error': str(e)
            }
    
    return results

def test_llm_service_directly():
    """
    Testet den Image2TextService direkt, ohne API.
    """
    print("\n🧪 Teste Image2TextService direkt...")
    
    try:
        from src.utils.image2text_utils import Image2TextService
        from src.core.config import Config
        
        # Initialisiere den Service
        config = Config()
        service = Image2TextService(config=config.get_config(), processor_name="test")
        
        # Teste mit einem einfachen Bild
        test_image = "tests/samples/diagramm.jpg"
        if os.path.exists(test_image):
            print(f"🔄 Verarbeite Bild: {test_image}")
            
            # Teste die Bildkonvertierung
            result = service.convert_image_to_text(
                image_path=test_image,
                custom_prompt="Beschreibe dieses Diagramm detailliert in deutscher Sprache."
            )
            
            if result:
                print(f"✅ Direkter Service-Test erfolgreich")
                print(f"📝 Ergebnis: {result[:300]}...")
                return {"status": "success", "result": result}
            else:
                print("❌ Kein Ergebnis vom Service erhalten")
                return {"status": "error", "error": "No result"}
                
        else:
            print(f"❌ Testbild nicht gefunden: {test_image}")
            return {"status": "error", "error": "Test image not found"}
            
    except Exception as e:
        print(f"❌ Fehler beim direkten Service-Test: {str(e)}")
        return {"status": "exception", "error": str(e)}

def main():
    """
    Hauptfunktion für die LLM-OCR-Tests.
    """
    print("🚀 Starte LLM-OCR Integration Tests")
    print("=" * 60)
    
    # Überprüfe, ob der Server läuft
    api_base_url = "http://localhost:8000"
    try:
        response = requests.get(f"{api_base_url}/health", timeout=5)
        if response.status_code != 200:
            print(f"❌ Server nicht erreichbar: {api_base_url}")
            return
    except Exception as e:
        print(f"❌ Server-Verbindung fehlgeschlagen: {str(e)}")
        print("💡 Stelle sicher, dass der Server läuft: python src/main.py")
        return
    
    print(f"✅ Server erreichbar: {api_base_url}")
    
    # Teste direkten Service
    direct_result = test_llm_service_directly()
    
    # Teste PDF LLM-OCR
    pdf_results = test_pdf_llm_ocr(api_base_url)
    
    # Teste Image LLM-OCR
    image_results = test_image_llm_ocr(api_base_url)
    
    # Zusammenfassung
    print("\n" + "=" * 60)
    print("📊 Test-Zusammenfassung:")
    print("=" * 60)
    
    print(f"🔧 Direkter Service-Test: {direct_result.get('status', 'unknown')}")
    
    print(f"📄 PDF LLM-OCR Tests:")
    for method, result in pdf_results.items():
        status = result.get('status', 'unknown')
        print(f"   {method}: {status}")
    
    print(f"🖼️  Image LLM-OCR Tests:")
    for method, result in image_results.items():
        status = result.get('status', 'unknown')
        print(f"   {method}: {status}")
    
    print("\n✅ Tests abgeschlossen!")

if __name__ == "__main__":
    main() 