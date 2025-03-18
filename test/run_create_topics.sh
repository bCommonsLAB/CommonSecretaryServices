#!/bin/bash

echo "Starte Ausfuehrung der Topic-Erstellung..."

# Aktiviere die virtuelle Python-Umgebung
echo "Aktiviere virtuelle Python-Umgebung..."
source ../venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Fehler beim Aktivieren der virtuellen Umgebung."
    echo "Bitte stellen Sie sicher, dass 'venv' korrekt eingerichtet ist."
    exit 1
fi

# Setze PYTHONPATH
echo "Setze PYTHONPATH auf aktuelles Verzeichnis..."
export PYTHONPATH=..

# Lese die MongoDB-Verbindung aus der .env-Datei
if [ -f "../.env" ]; then
    # Extrahiere MONGODB_URI aus der .env-Datei
    export $(grep -v '^#' ../.env | grep MONGODB_URI)
    echo "MONGODB_URI aus .env-Datei geladen."
else
    echo "WARNUNG: .env-Datei nicht gefunden."
fi

# Wenn keine MONGODB_URI gefunden wurde, verwende einen Standard-Wert
if [ -z "$MONGODB_URI" ]; then
    echo "WARNUNG: MONGODB_URI nicht in .env-Datei gefunden."
    echo "Verwende Standard-Verbindung: mongodb://localhost:27017/common-secretary-db"
    MONGODB_URI="mongodb://localhost:27017/common-secretary-db"
fi

# Prüfe, ob mongosh installiert ist
if ! command -v mongosh &> /dev/null; then
    echo "MongoDB Shell (mongosh) ist nicht installiert."
    echo "Fuehre stattdessen die Python-Anwendung zum Überprüfen der Datenbank aus..."
    
    # Starte Python-Anwendung
    echo "Starte Python-Anwendung..."
    cd ..
    python src/main.py
    cd test
    
    echo "Anwendung gestartet. Bitte pruefen Sie die MongoDB-Inhalte ueber die Anwendung."
    read -p "Drücke Enter zum Beenden..." key
    exit 0
fi

echo "Verbinde mit: $MONGODB_URI"
mongosh "$MONGODB_URI" --file create_topics.js

echo
echo "Script abgeschlossen. MongoDB-Topics wurden erstellt oder aktualisiert."

# Starte Python-Anwendung zur Überprüfung
echo
echo "Möchten Sie die Python-Anwendung starten, um die Datenbank zu prüfen? (j/N)"
read -p "Eingabe: " choice
if [[ "$choice" =~ ^[Jj]$ ]]; then
    echo "Starte Python-Anwendung..."
    cd ..
    python src/main.py
    cd test
else
    echo "Python-Anwendung wird nicht gestartet."
fi

echo
echo "Prozess abgeschlossen."
read -p "Drücke Enter zum Beenden..." key 