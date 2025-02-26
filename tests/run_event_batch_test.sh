#!/bin/bash
# Ausführungsskript für den Event-Processor Batch-Test

# Standardwerte
MAX_EVENTS=3
VERBOSE=true

# Hilfe-Funktion
show_help() {
    echo "Verwendung: $0 [Optionen]"
    echo ""
    echo "Optionen:"
    echo "  -h, --help           Diese Hilfe anzeigen"
    echo "  -e, --events ANZAHL  Anzahl der zu verarbeitenden Events (Standard: 3)"
    echo "  -q, --quiet          Minimale Ausgabe (ohne Vorschau der Inhalte)"
    echo "  -l, --log-level LVL  Logging-Level setzen (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    echo ""
}

# Parameter verarbeiten
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -e|--events)
            MAX_EVENTS="$2"
            shift 2
            ;;
        -q|--quiet)
            VERBOSE=false
            shift
            ;;
        -l|--log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        *)
            echo "Unbekannte Option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Wechsle ins Hauptverzeichnis des Projekts
cd "$(dirname "$0")/.."

# Setze PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Setze Logging-Level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export LOG_LEVEL=${LOG_LEVEL:-INFO}

# Erstelle Logs-Verzeichnis, falls es nicht existiert
mkdir -p logs

# Aktuelles Datum und Zeit für den Logfile-Namen
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/event_batch_test_${TIMESTAMP}.log"

echo "Starte Event-Processor Batch-Test..."
echo "Verarbeite $MAX_EVENTS Events mit ${VERBOSE} Ausgabe"
echo "Logging-Level: $LOG_LEVEL"
echo "Logs werden in $LOG_FILE gespeichert"

# Führe den Test aus und leite Ausgabe in Logfile um, zeige aber auch in der Konsole an
python tests/test_event_processor_batch.py "$MAX_EVENTS" "$VERBOSE" 2>&1 | tee "$LOG_FILE"

echo "Test abgeschlossen."
echo "Vollständige Logs in: $LOG_FILE"

# Alternativ mit pytest
# python -m pytest -xvs tests/test_event_processor_batch.py

echo "Test abgeschlossen." 