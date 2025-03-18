@echo off
echo Starte Topic-Erstellung mit Python...

REM Aktiviere die virtuelle Python-Umgebung
echo Aktiviere virtuelle Python-Umgebung...
call ..\venv\Scripts\activate
if %ERRORLEVEL% neq 0 (
    echo Fehler beim Aktivieren der virtuellen Umgebung.
    echo Bitte stellen Sie sicher, dass 'venv' korrekt eingerichtet ist.
    exit /b 1
)

REM Setze PYTHONPATH
echo Setze PYTHONPATH auf aktuelles Verzeichnis...
set PYTHONPATH=..

REM Prüfe, ob die benötigten Python-Pakete installiert sind
echo Prüfe benötigte Python-Pakete...
python -c "import pymongo; import dotenv" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installiere benötigte Python-Pakete...
    pip install pymongo python-dotenv
)

REM Führe das Python-Skript zur Topic-Erstellung aus
echo Führe Python-Skript zur Topic-Erstellung aus...
python create_topics.py

echo.
echo Topic-Erstellung abgeschlossen.
echo.

REM Frage, ob die Anwendung gestartet werden soll
echo Möchten Sie die Python-Anwendung starten, um die Datenbank zu prüfen? (J/N)
set /p choice=Eingabe: 
if /i "%choice%"=="J" (
    echo Starte Python-Anwendung...
    cd ..
    python src/main.py
    cd test
) else (
    echo Python-Anwendung wird nicht gestartet.
)

echo.
echo Prozess abgeschlossen.
pause 