# Test-Skript für LLM-OCR API mit PowerShell/cURL
# Testet die neuen LLM-basierten Extraktionsmethoden

$API_BASE = "http://localhost:8000"
$TEST_PDF = "tests/samples/sample.pdf"
$TEST_IMAGE = "tests/samples/diagramm.jpg"

Write-Host "🚀 Starte LLM-OCR API Tests mit PowerShell/cURL" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green

# Überprüfe Server-Verfügbarkeit
Write-Host "🔍 Überprüfe Server-Verfügbarkeit..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$API_BASE/health" -Method Get -TimeoutSec 5
    Write-Host "✅ Server ist erreichbar" -ForegroundColor Green
} catch {
    Write-Host "❌ Server nicht erreichbar. Starte den Server mit: python src/main.py" -ForegroundColor Red
    exit 1
}

# Teste PDF LLM-OCR
Write-Host ""
Write-Host "📄 Teste PDF LLM-OCR..." -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan

if (Test-Path $TEST_PDF) {
    Write-Host "🧪 Teste PDF mit LLM-Extraktion..." -ForegroundColor Yellow
    
    # Test 1: Reine LLM-Extraktion
    Write-Host "🔄 Test 1: Reine LLM-Extraktion (llm)" -ForegroundColor Yellow
    try {
        $form = @{
            file = Get-Item $TEST_PDF
            extraction_method = "llm"
            useCache = "false"
            context = '{"document_type":"technical","language":"de"}'
        }
        $result = Invoke-RestMethod -Uri "$API_BASE/api/pdf/process" -Method Post -Form $form
        if ($result.status -eq "success") {
            Write-Host "✅ PDF LLM-Extraktion erfolgreich" -ForegroundColor Green
            if ($result.data.pages -and $result.data.pages[0].llm_text) {
                $preview = $result.data.pages[0].llm_text.Substring(0, [Math]::Min(200, $result.data.pages[0].llm_text.Length))
                Write-Host "📝 LLM-Text Vorschau: $preview..." -ForegroundColor White
            }
        } else {
            Write-Host "❌ PDF LLM-Extraktion fehlgeschlagen: $($result.error.message)" -ForegroundColor Red
        }
    } catch {
        Write-Host "❌ Fehler bei PDF LLM-Test: $($_.Exception.Message)" -ForegroundColor Red
    }
    
    # Test 2: LLM + Native Text
    Write-Host ""
    Write-Host "🔄 Test 2: LLM + Native Text (llm_and_native)" -ForegroundColor Yellow
    try {
        $form = @{
            file = Get-Item $TEST_PDF
            extraction_method = "llm_and_native"
            useCache = "false"
            context = '{"document_type":"scientific","language":"de"}'
        }
        $result = Invoke-RestMethod -Uri "$API_BASE/api/pdf/process" -Method Post -Form $form
        Write-Host "✅ Status: $($result.status)" -ForegroundColor Green
        if ($result.process.llm_info) {
            Write-Host "📊 LLM Info: $($result.process.llm_info | ConvertTo-Json -Compress)" -ForegroundColor White
        }
    } catch {
        Write-Host "❌ Fehler bei LLM+Native Test: $($_.Exception.Message)" -ForegroundColor Red
    }
    
} else {
    Write-Host "❌ Test-PDF nicht gefunden: $TEST_PDF" -ForegroundColor Red
}

# Teste Image LLM-OCR
Write-Host ""
Write-Host "🖼️  Teste Image LLM-OCR..." -ForegroundColor Cyan
Write-Host "==========================" -ForegroundColor Cyan

if (Test-Path $TEST_IMAGE) {
    Write-Host "🧪 Teste Bild mit LLM-Extraktion..." -ForegroundColor Yellow
    
    # Test 1: Reine LLM-Extraktion
    Write-Host "🔄 Test 1: Reine LLM-Extraktion (llm)" -ForegroundColor Yellow
    try {
        $form = @{
            file = Get-Item $TEST_IMAGE
            extraction_method = "llm"
            useCache = "false"
            context = '{"document_type":"diagram","language":"de"}'
        }
        $result = Invoke-RestMethod -Uri "$API_BASE/api/imageocr/process" -Method Post -Form $form
        if ($result.status -eq "success") {
            Write-Host "✅ Image LLM-Extraktion erfolgreich" -ForegroundColor Green
            if ($result.data.llm_text) {
                $preview = $result.data.llm_text.Substring(0, [Math]::Min(200, $result.data.llm_text.Length))
                Write-Host "📝 LLM-Text Vorschau: $preview..." -ForegroundColor White
            }
        } else {
            Write-Host "❌ Image LLM-Extraktion fehlgeschlagen: $($result.error.message)" -ForegroundColor Red
        }
    } catch {
        Write-Host "❌ Fehler bei Image LLM-Test: $($_.Exception.Message)" -ForegroundColor Red
    }
    
    # Test 2: LLM + OCR
    Write-Host ""
    Write-Host "🔄 Test 2: LLM + OCR (llm_and_ocr)" -ForegroundColor Yellow
    try {
        $form = @{
            file = Get-Item $TEST_IMAGE
            extraction_method = "llm_and_ocr"
            useCache = "false"
            context = '{"document_type":"technical","language":"de"}'
        }
        $result = Invoke-RestMethod -Uri "$API_BASE/api/imageocr/process" -Method Post -Form $form
        Write-Host "✅ Status: $($result.status)" -ForegroundColor Green
    } catch {
        Write-Host "❌ Fehler bei LLM+OCR Test: $($_.Exception.Message)" -ForegroundColor Red
    }
    
} else {
    Write-Host "❌ Test-Bild nicht gefunden: $TEST_IMAGE" -ForegroundColor Red
}

# Teste URL-basierte Image-OCR
Write-Host ""
Write-Host "🌐 Teste URL-basierte Image LLM-OCR..." -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

Write-Host "🔄 Test: LLM-Extraktion von URL" -ForegroundColor Yellow
try {
    $form = @{
        url = "https://via.placeholder.com/600x400/000000/FFFFFF?text=Test+Diagram"
        extraction_method = "llm"
        useCache = "false"
        context = '{"document_type":"diagram","language":"de"}'
    }
    $result = Invoke-RestMethod -Uri "$API_BASE/api/imageocr/process-url" -Method Post -Form $form
    if ($result.status -eq "success") {
        Write-Host "✅ URL LLM-Extraktion erfolgreich" -ForegroundColor Green
        if ($result.data.llm_text) {
            Write-Host "📝 LLM-Text: $($result.data.llm_text)" -ForegroundColor White
        }
    } else {
        Write-Host "❌ URL LLM-Extraktion fehlgeschlagen: $($result.error.message)" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Fehler bei URL LLM-Test: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "✅ Tests abgeschlossen!" -ForegroundColor Green
Write-Host ""
Write-Host "💡 Tipps:" -ForegroundColor Yellow
Write-Host "   - Überprüfe die Logs mit: Get-Content logs/app.log -Tail 20" -ForegroundColor White
Write-Host "   - Verwende -Verbose für detaillierte Ausgabe" -ForegroundColor White
Write-Host ""
Write-Host "🔧 Erweiterte Tests:" -ForegroundColor Yellow
Write-Host "   python tests/test_llm_ocr_integration.py" -ForegroundColor White 