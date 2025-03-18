@echo off
echo Starte Ausfuehrung der Topic-Erstellung...

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

REM Lese die MongoDB-Verbindung aus der .env-Datei
FOR /F "tokens=*" %%i IN ('findstr /B "MONGODB_URI" ..\.env') DO SET %%i
echo MONGODB_URI aus .env-Datei geladen.

REM Wenn keine MONGODB_URI gefunden wurde, verwende einen Standard-Wert
IF "%MONGODB_URI%"=="" (
    echo WARNUNG: MONGODB_URI nicht in .env-Datei gefunden.
    echo Verwende Standard-Verbindung: mongodb://localhost:27017/common-secretary-db
    SET MONGODB_URI=mongodb://localhost:27017/common-secretary-db
)

REM Pruefe, ob mongosh installiert ist
where mongosh >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo MongoDB Shell (mongosh) ist nicht installiert oder nicht im PATH.
    echo Fuehre stattdessen die Python-Anwendung zum Überprüfen der Datenbank aus...
    
    REM Starte Python-Anwendung
    echo Starte Python-Anwendung...
    cd ..
    python src/main.py
    cd test
    
    echo Anwendung gestartet. Bitte pruefen Sie die MongoDB-Inhalte ueber die Anwendung.
    pause
    exit /b 0
)

echo Verbinde mit: %MONGODB_URI%
mongosh "%MONGODB_URI%" --file create_topics.js

echo.
echo Script abgeschlossen. MongoDB-Topics wurden erstellt oder aktualisiert.

REM Starte Python-Anwendung zur Überprüfung
echo.
echo Moechten Sie die Python-Anwendung starten, um die Datenbank zu pruefen? (J/N)
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