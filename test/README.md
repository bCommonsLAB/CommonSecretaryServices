# Topic-Erstellung aus Session-Cache

Diese Scripts lesen die Session-Cache-Einträge aus der MongoDB-Datenbank und erstellen daraus Topic-Einträge in der Topics-Collection.

## Voraussetzungen

1. Eine Python-Umgebung mit virtualenv (venv)
2. MongoDB-Zugriff (entweder über mongosh oder über die Python-Anwendung)
3. Eine konfigurierte .env-Datei im Hauptverzeichnis mit einer MONGODB_URI-Variable

## Verfügbare Skripte

Es stehen zwei Varianten zur Verfügung:

1. **MongoDB Shell (mongosh) Version**:
   - `create_topics.js` - MongoDB-JavaScript zur Topic-Erstellung
   - `run_create_topics.bat` / `run_create_topics.sh` - Ausführungsskripte 

2. **Python Version** (empfohlen, ohne mongosh-Abhängigkeit):
   - `create_topics.py` - Python-Skript zur Topic-Erstellung
   - `run_create_topics_py.bat` / `run_create_topics_py.sh` - Ausführungsskripte

## Funktionsweise

Die Skripte führen folgende Operationen durch:
1. Aktivieren der virtuellen Python-Umgebung
2. Setzen des PYTHONPATH auf das Stammverzeichnis
3. Laden der MongoDB-Verbindungsdaten aus der .env-Datei
4. Ausführen des Scripts zur Topic-Erstellung (JavaScript oder Python)
5. Optional: Starten der Python-Anwendung zur Überprüfung der Daten

## Anleitung

### 1. Konfiguration prüfen

Die Skripte lesen die Datenbank-Verbindungsinformationen automatisch aus der .env-Datei im Hauptverzeichnis des Projekts. Stellen Sie sicher, dass die Variable MONGODB_URI in der .env-Datei korrekt definiert ist:

```
# Beispiel für einen Eintrag in .env
MONGODB_URI=mongodb://localhost:27017/your_database_name
```

Wenn keine .env-Datei gefunden wird oder die Variable nicht definiert ist, wird eine Standard-Verbindung verwendet:
```
mongodb://localhost:27017/common-secretary-db
```

### 2. Skript ausführen

#### Python-Version (empfohlen)

##### Windows
Doppelklick auf `run_create_topics_py.bat` oder führe es in der Kommandozeile aus:
```
cd test
run_create_topics_py.bat
```

##### Linux/Mac
Mache das Skript ausführbar und starte es:
```
cd test
chmod +x run_create_topics_py.sh
./run_create_topics_py.sh
```

#### MongoDB Shell Version

Erfordert die Installation von MongoDB Shell (mongosh).

##### Windows
Doppelklick auf `run_create_topics.bat` oder führe es in der Kommandozeile aus:
```
cd test
run_create_topics.bat
```

##### Linux/Mac
Mache das Skript ausführbar und starte es:
```
cd test
chmod +x run_create_topics.sh
./run_create_topics.sh
```

### 3. Ergebnisse überprüfen

Beide Skriptvarianten bieten zwei Möglichkeiten zur Überprüfung der Ergebnisse:

1. **Direkte Ausgabe**: Die Skripte zeigen die gefundenen und erstellten Topics direkt in der Konsole an.
2. **Über die Python-Anwendung**: Am Ende des Skripts wird angeboten, die Python-Anwendung zu starten, um die erstellten Daten zu überprüfen.

## Aktionen der Scripts

Die Scripts führen folgende Aktionen durch:
1. Verbindung zur MongoDB-Datenbank mit der aus der .env-Datei gelesenen URI herstellen
2. Session-Cache-Einträge mit vorhandenen Topics suchen
3. Einzigartige Topics extrahieren
4. Neue Topics in der `topics`-Collection erstellen
5. Zielgruppen in der `target_groups`-Collection erstellen, falls diese noch nicht existieren

## Konfiguration und Anpassung

### Topic-Vorlagen

In den Scripts sind einige Vorlagen für bekannte Ecosocial-Themen definiert. Diese werden verwendet, wenn ein Topic-Name mit einem der vordefinierten Namen übereinstimmt. Für alle anderen Topics wird eine generische Vorlage erstellt.

Wenn du weitere Vorlagen hinzufügen möchtest, kannst du die entsprechenden Definitionen in den Scripts erweitern:
- JavaScript: `ecosocialTopics`-Objekt in `create_topics.js`
- Python: `ECOSOCIAL_TOPICS`-Dictionary in `create_topics.py`

### Fehlerbehandlung

- Wenn die virtuelle Python-Umgebung nicht aktiviert werden kann, bricht das Skript mit einer Fehlermeldung ab.
- Die Python-Version installiert automatisch fehlende Abhängigkeiten (pymongo, python-dotenv).
- Wenn die mongosh nicht verfügbar ist (bei der MongoDB-Shell-Version), wird automatisch die Python-Anwendung gestartet.
- Wenn die ObjectId nicht erstellt werden kann oder kein Eintrag mit der angegebenen ID gefunden wird, versucht das Script, Einträge mit dem Topic "offenes Design" zu finden. Falls auch das fehlschlägt, werden alle Einträge mit vorhandenen Topics gesucht.

## Hinweise

- Die Scripts überspringen bereits existierende Topics und erstellen nur neue Einträge.
- Standardmäßig wird als Event "FOSDEM 2025" verwendet, wenn kein Event aus den Session-Daten extrahiert werden kann.
- Alle erstellten Topics verwenden "technical" als primäre Zielgruppe und haben ein Relevanz-Threshold von 0.6. 