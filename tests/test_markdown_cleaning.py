"""
Test für die Markdown-Bereinigungsfunktion der Image2TextService.
"""

import sys
import os

# Füge src-Verzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.utils.image2text_utils import Image2TextService

def test_markdown_cleaning():
    """
    Testet die clean_markdown_response Funktion mit verschiedenen Eingaben.
    """
    print("🧪 Teste Markdown-Bereinigungsfunktion...")
    
    # Erstelle eine Service-Instanz für Tests
    service = Image2TextService(processor_name="test")
    
    # Testfälle
    test_cases = [
        {
            "input": "```markdown\n# Titel\n\nText hier\n```",
            "expected": "# Titel\n\nText hier",
            "description": "Markdown-Codeblock mit ```markdown"
        },
        {
            "input": "```\n# Titel\n\nText hier\n```",
            "expected": "# Titel\n\nText hier",
            "description": "Markdown-Codeblock mit ```"
        },
        {
            "input": "# Titel\n\nText hier",
            "expected": "# Titel\n\nText hier",
            "description": "Normaler Markdown-Text ohne Codeblock"
        },
        {
            "input": "```markdown\n# ALLGEMEINER TEIL\n\n## NATURRÄUMLICHE VORAUSSETZUNGEN\n\nText hier...\n```",
            "expected": "# ALLGEMEINER TEIL\n\n## NATURRÄUMLICHE VORAUSSETZUNGEN\n\nText hier...",
            "description": "Beispiel aus deinem Test"
        },
        {
            "input": "",
            "expected": "",
            "description": "Leerer String"
        },
        {
            "input": "```markdown\n```",
            "expected": "",
            "description": "Nur Codeblock-Markierungen"
        },
        {
            "input": "   ```markdown\n# Titel\n```   ",
            "expected": "# Titel",
            "description": "Mit Whitespace"
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📝 Test {i}: {test_case['description']}")
        print(f"   Input: {repr(test_case['input'])}")
        
        # Führe Bereinigung durch
        result = service.clean_markdown_response(test_case['input'])
        
        print(f"   Result: {repr(result)}")
        print(f"   Expected: {repr(test_case['expected'])}")
        
        # Überprüfe Ergebnis
        if result == test_case['expected']:
            print("   ✅ PASSED")
            passed += 1
        else:
            print("   ❌ FAILED")
            failed += 1
    
    print(f"\n📊 Test-Zusammenfassung:")
    print(f"   ✅ Bestanden: {passed}")
    print(f"   ❌ Fehlgeschlagen: {failed}")
    print(f"   📈 Erfolgsrate: {passed/(passed+failed)*100:.1f}%")
    
    if failed == 0:
        print("\n🎉 Alle Tests bestanden!")
        return True
    else:
        print(f"\n⚠️  {failed} Test(s) fehlgeschlagen!")
        return False

def test_real_world_example():
    """
    Testet mit dem realen Beispiel aus deiner Anfrage.
    """
    print("\n🧪 Teste reales Beispiel...")
    
    service = Image2TextService(processor_name="test")
    
    # Dein Beispiel
    input_text = "```markdown\n# ALLGEMEINER TEIL\n\n## NATURRÄUMLICHE VORAUSSETZUNGEN, LEBENSRÄUME\n\n![Die weltberühmten Dolomiten entstanden im Laufe von Millionen von Jahren aus Sedimenten des ehemaligen Meeresbodens.]vulkanischen Gestein dominiert, dem durch seine rötliche Färbung auffallenden Bozner Quarzporphyr. Er\n```\n"
    
    expected = "# ALLGEMEINER TEIL\n\n## NATURRÄUMLICHE VORAUSSETZUNGEN, LEBENSRÄUME\n\n![Die weltberühmten Dolomiten entstanden im Laufe von Millionen von Jahren aus Sedimenten des ehemaligen Meeresbodens.]vulkanischen Gestein dominiert, dem durch seine rötliche Färbung auffallenden Bozner Quarzporphyr. Er"
    
    result = service.clean_markdown_response(input_text)
    
    print(f"Input: {repr(input_text)}")
    print(f"Result: {repr(result)}")
    print(f"Expected: {repr(expected)}")
    
    if result == expected:
        print("✅ Real-World Test bestanden!")
        return True
    else:
        print("❌ Real-World Test fehlgeschlagen!")
        return False

if __name__ == "__main__":
    print("🚀 Starte Markdown-Bereinigungs-Tests")
    print("=" * 50)
    
    # Führe Tests aus
    basic_tests_passed = test_markdown_cleaning()
    real_world_passed = test_real_world_example()
    
    if basic_tests_passed and real_world_passed:
        print("\n🎉 Alle Tests erfolgreich!")
        print("Die Markdown-Bereinigung funktioniert korrekt.")
    else:
        print("\n⚠️  Einige Tests fehlgeschlagen!")
        print("Die Markdown-Bereinigung muss überprüft werden.") 