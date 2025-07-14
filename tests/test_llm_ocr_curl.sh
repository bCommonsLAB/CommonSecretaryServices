#!/bin/bash

# Test-Skript für LLM-OCR API mit cURL
# Testet die neuen LLM-basierten Extraktionsmethoden

API_BASE="http://localhost:8000"
TEST_PDF="tests/samples/sample.pdf"
TEST_IMAGE="tests/samples/diagramm.jpg"

echo "🚀 Starte LLM-OCR API Tests mit cURL"
echo "===================================="

# Überprüfe Server-Verfügbarkeit
echo "🔍 Überprüfe Server-Verfügbarkeit..."
if curl -s -f "$API_BASE/health" > /dev/null; then
    echo "✅ Server ist erreichbar"
else
    echo "❌ Server nicht erreichbar. Starte den Server mit: python src/main.py"
    exit 1
fi

# Teste PDF LLM-OCR
echo ""
echo "📄 Teste PDF LLM-OCR..."
echo "========================"

if [ -f "$TEST_PDF" ]; then
    echo "🧪 Teste PDF mit LLM-Extraktion..."
    
    # Test 1: Reine LLM-Extraktion
    echo "🔄 Test 1: Reine LLM-Extraktion (llm)"
    curl -X POST "$API_BASE/api/pdf/process" \
        -F "file=@$TEST_PDF" \
        -F "extraction_method=llm" \
        -F "useCache=false" \
        -F "context={\"document_type\":\"technical\",\"language\":\"de\"}" \
        -H "Accept: application/json" \
        -w "\n⏱️  Response Time: %{time_total}s\n" \
        -s | jq '.data.pages[0].llm_text' 2>/dev/null || echo "❌ Fehler oder jq nicht installiert"
    
    echo ""
    echo "🔄 Test 2: LLM + Native Text (llm_and_native)"
    curl -X POST "$API_BASE/api/pdf/process" \
        -F "file=@$TEST_PDF" \
        -F "extraction_method=llm_and_native" \
        -F "useCache=false" \
        -F "context={\"document_type\":\"scientific\",\"language\":\"de\"}" \
        -H "Accept: application/json" \
        -w "\n⏱️  Response Time: %{time_total}s\n" \
        -s | jq '.status' 2>/dev/null || echo "❌ Fehler oder jq nicht installiert"
    
    echo ""
    echo "🔄 Test 3: LLM + OCR (llm_and_ocr)"
    curl -X POST "$API_BASE/api/pdf/process" \
        -F "file=@$TEST_PDF" \
        -F "extraction_method=llm_and_ocr" \
        -F "useCache=false" \
        -F "context={\"document_type\":\"presentation\",\"language\":\"de\"}" \
        -H "Accept: application/json" \
        -w "\n⏱️  Response Time: %{time_total}s\n" \
        -s | jq '.process.llm_info' 2>/dev/null || echo "❌ Fehler oder jq nicht installiert"
        
else
    echo "❌ Test-PDF nicht gefunden: $TEST_PDF"
fi

# Teste Image LLM-OCR
echo ""
echo "🖼️  Teste Image LLM-OCR..."
echo "=========================="

if [ -f "$TEST_IMAGE" ]; then
    echo "🧪 Teste Bild mit LLM-Extraktion..."
    
    # Test 1: Reine LLM-Extraktion
    echo "🔄 Test 1: Reine LLM-Extraktion (llm)"
    curl -X POST "$API_BASE/api/imageocr/process" \
        -F "file=@$TEST_IMAGE" \
        -F "extraction_method=llm" \
        -F "useCache=false" \
        -F "context={\"document_type\":\"diagram\",\"language\":\"de\"}" \
        -H "Accept: application/json" \
        -w "\n⏱️  Response Time: %{time_total}s\n" \
        -s | jq '.data.llm_text' 2>/dev/null || echo "❌ Fehler oder jq nicht installiert"
    
    echo ""
    echo "🔄 Test 2: LLM + OCR (llm_and_ocr)"
    curl -X POST "$API_BASE/api/imageocr/process" \
        -F "file=@$TEST_IMAGE" \
        -F "extraction_method=llm_and_ocr" \
        -F "useCache=false" \
        -F "context={\"document_type\":\"technical\",\"language\":\"de\"}" \
        -H "Accept: application/json" \
        -w "\n⏱️  Response Time: %{time_total}s\n" \
        -s | jq '.status' 2>/dev/null || echo "❌ Fehler oder jq nicht installiert"
        
else
    echo "❌ Test-Bild nicht gefunden: $TEST_IMAGE"
fi

# Teste URL-basierte Image-OCR
echo ""
echo "🌐 Teste URL-basierte Image LLM-OCR..."
echo "======================================"

echo "🔄 Test: LLM-Extraktion von URL"
curl -X POST "$API_BASE/api/imageocr/process-url" \
    -F "url=https://via.placeholder.com/600x400/000000/FFFFFF?text=Test+Diagram" \
    -F "extraction_method=llm" \
    -F "useCache=false" \
    -F "context={\"document_type\":\"diagram\",\"language\":\"de\"}" \
    -H "Accept: application/json" \
    -w "\n⏱️  Response Time: %{time_total}s\n" \
    -s | jq '.data.llm_text' 2>/dev/null || echo "❌ Fehler oder jq nicht installiert"

echo ""
echo "✅ Tests abgeschlossen!"
echo ""
echo "💡 Tipps:"
echo "   - Installiere jq für bessere JSON-Ausgabe: sudo apt install jq"
echo "   - Verwende -v Flag für detaillierte cURL-Ausgabe"
echo "   - Überprüfe die Logs mit: tail -f logs/app.log"
echo ""
echo "🔧 Erweiterte Tests:"
echo "   python tests/test_llm_ocr_integration.py" 