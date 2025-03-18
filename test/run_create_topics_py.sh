#!/bin/bash

echo "Starte Topic-Erstellung mit Python..."

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

# Prüfe, ob die benötigten Python-Pakete installiert sind
echo "Prüfe benötigte Python-Pakete..."
python -c "import pymongo; import dotenv" &>/dev/null
if [ $? -ne 0 ]; then
    echo "Installiere benötigte Python-Pakete..."
    pip install pymongo python-dotenv
fi

# Führe das Python-Skript zur Topic-Erstellung aus
echo "Führe Python-Skript zur Topic-Erstellung aus..."
python create_topics.py

echo
echo "Topic-Erstellung abgeschlossen."
echo

# Frage, ob die Anwendung gestartet werden soll
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