# Session ZIP-Archiv Funktion

## Übersicht

Der SessionProcessor erstellt ab sofort automatisch ein ZIP-Archiv mit dem generierten Markdown und allen referenzierten Bildern, wenn eine Session mit Anhängen verarbeitet wird.

## Funktionsweise

### Automatische ZIP-Erstellung

- Das ZIP wird automatisch erstellt, wenn `attachments_url` vorhanden ist und Bilder gefunden werden
- Das ZIP enthält die komplette originale Verzeichnisstruktur:
  - Die generierte Markdown-Datei mit ursprünglichen Pfaden
  - Alle Asset-Dateien in der originalen Ordnerstruktur
  - Eine `README.md` mit Nutzungshinweisen

### ZIP-Archiv-Struktur

Das ZIP behält die vollständige Verzeichnisstruktur bei:

```
session_name.zip
├── sessions/                        # Basis-Verzeichnis
│   └── Event_Name/                  # Event-spezifisches Verzeichnis  
│       ├── assets/                  # Gemeinsame Assets für alle Sprachen
│       │   └── session_name/        # Session-spezifische Assets
│       │       ├── slide_01.png
│       │       └── slide_02.png
│       └── LANGUAGE/                # Zielsprache (EN, DE, etc.)
│           └── Track_Name/          # Track-spezifisches Verzeichnis
│               └── session_name.md  # Session Markdown
└── README.md                       # Nutzungshinweise
```

**Vorteile dieser Struktur:**
- **Mehrsprachigkeit**: Verschiedene Sprachen können gemeinsame Assets verwenden
- **Skalierbarkeit**: Unterstützt große Events mit vielen Sessions und Tracks
- **Relative Pfade**: Markdown-Dateien funktionieren sofort nach dem Entpacken
- **Organisation**: Klare Trennung zwischen Content und Assets

### API-Parameter

Der neue optionale Parameter `create_archive` steuert die ZIP-Erstellung:

```json
{
  "event": "FOSDEM 2025",
  "session": "Welcome to FOSDEM",
  "url": "https://fosdem.org/2025/schedule/event/welcome/",
  "filename": "welcome_fosdem.md",
  "track": "Main Track",
  "attachments_url": "https://fosdem.org/2025/schedule/event/welcome/attachments/slides.pdf",
  "create_archive": true  // Optional, Standard: true
}
```

### Response-Struktur

Das ZIP-Archiv wird im Response als Base64-kodierte Daten zurückgegeben:

```json
{
  "status": "success",
  "data": {
    "output": {
      "markdown_content": "# Welcome to FOSDEM\n...",
      "archive_data": "UEsDBBQACAgIAOxPbFkAAA...",  // Base64-kodierte ZIP-Daten
      "archive_filename": "welcome_fosdem.zip",
      "attachments": ["FOSDEM_2025/assets/welcome_fosdem/slide_01.png", ...]
    }
  }
}
```

## Client-Nutzung

### Worker-Pipeline Verständnis

Der Session Worker verarbeitet Jobs asynchron in folgenden Phasen:

1. **Job Creation**: Job wird in MongoDB gespeichert (`status: "pending"`)
2. **Worker Processing**: Worker nimmt Job auf (`status: "processing"`)
3. **Session Processing**: SessionProcessor verarbeitet die Session
4. **Archive Creation**: ZIP-Archiv wird erstellt (falls aktiviert)
5. **Result Storage**: Alle Ergebnisse werden in MongoDB gespeichert (`status: "completed"`)
6. **Client Access**: Client kann Ergebnisse abrufen und Archive herunterladen

### Asynchrone Job-Verarbeitung (Empfohlen)

Für die produktive Nutzung wird die asynchrone Job-Verarbeitung über MongoDB empfohlen:

#### 1. Job erstellen

```javascript
const response = await fetch('/api/event-job/jobs', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    job_type: "session_processing",
    parameters: {
      event: "FOSDEM 2025",
      session: "Welcome to FOSDEM",
      url: "https://fosdem.org/2025/schedule/event/welcome/",
      filename: "welcome_fosdem.md",
      track: "Main Track",
      attachments_url: "https://fosdem.org/2025/slides.pdf",
      create_archive: true  // ZIP-Archiv aktivieren
    }
  })
});

const jobResponse = await response.json();
const jobId = jobResponse.job.job_id;
```

#### 2. Job-Status überwachen und Ergebnisse verarbeiten

```javascript
const pollJobStatus = async (jobId, onProgress = null) => {
  const startTime = Date.now();
  let lastStatus = null;
  
  while (true) {
    const response = await fetch(`/api/event-job/jobs/${jobId}`);
    const result = await response.json();
    const job = result.job;
    
    // Status-Änderung loggen
    if (job.status !== lastStatus) {
      console.log(`Job ${jobId}: ${lastStatus} → ${job.status}`);
      lastStatus = job.status;
      
      // Progress-Callback aufrufen
      if (onProgress) {
        onProgress({
          status: job.status,
          progress: job.progress,
          duration: Date.now() - startTime
        });
      }
    }
    
    // Verarbeitung abgeschlossen
    if (job.status === 'completed') {
      return job;
    } 
    
    // Fehlerbehandlung
    if (job.status === 'failed') {
      const error = job.error || {};
      throw new Error(`Job failed: ${error.message || 'Unknown error'}`);
    }
    
    // Fortschritt anzeigen (falls verfügbar)
    if (job.progress) {
      console.log(`Progress: ${job.progress.percent}% - ${job.progress.message}`);
    }
    
    // Warte 2 Sekunden vor nächster Abfrage
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
};

// Verwendung mit Progress-Callback
const completedJob = await pollJobStatus(jobId, (progress) => {
  console.log(`Status: ${progress.status}, ${progress.progress?.percent || 0}%`);
  updateUI(progress);
});
```

#### 3. Worker-Ergebnisse verarbeiten

```javascript
const processJobResults = async (completedJob) => {
  const results = completedJob.results;
  
  if (!results) {
    throw new Error('Job has no results');
  }
  
  // 1. Session-Metadaten extrahieren
  const sessionData = {
    markdown: results.markdown_content,
    webText: results.web_text,
    videoTranscript: results.video_transcript,
    structuredData: results.structured_data,
    assets: results.assets || [],
    pageTexts: results.page_texts || [],
    targetDir: results.target_dir
  };
  
  console.log('Session processed:', {
    hasMarkdown: !!sessionData.markdown,
    hasVideo: !!sessionData.videoTranscript,
    assetCount: sessionData.assets.length,
    pageCount: sessionData.pageTexts.length
  });
  
  // 2. Strukturierte Daten für weitere Verarbeitung
  if (sessionData.structuredData) {
    const { topic, relevance, speakers, duration } = sessionData.structuredData;
    console.log(`Topic: ${topic}, Relevance: ${relevance}`);
    
    // Beispiel: Kategorisierung basierend auf strukturierten Daten
    const category = categorizeSession(sessionData.structuredData);
    console.log(`Categorized as: ${category}`);
  }
  
  // 3. Archive-Verfügbarkeit prüfen
  const hasArchive = !!(results.archive_data && results.archive_filename);
  
  return {
    sessionData,
    hasArchive,
    archiveFilename: results.archive_filename,
    jobId: completedJob.job_id
  };
};

// Helper-Funktion für Kategorisierung
const categorizeSession = (structuredData) => {
  const topic = structuredData.topic?.toLowerCase() || '';
  
  if (topic.includes('security') || topic.includes('crypto')) return 'security';
  if (topic.includes('ai') || topic.includes('machine learning')) return 'ai';
  if (topic.includes('web') || topic.includes('frontend')) return 'web';
  if (topic.includes('database') || topic.includes('storage')) return 'data';
  
  return 'general';
};
```

#### 4. ZIP-Archive herunterladen und verarbeiten

```javascript
const downloadAndProcessArchive = async (jobId, archiveFilename) => {
  const downloadUrl = `/api/event-job/jobs/${jobId}/download-archive`;
  
  try {
    // Option A: Direkter Download für Benutzer
    const triggerUserDownload = () => {
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = archiveFilename;
      link.click();
    };
    
    // Option B: Programmatischer Download für weitere Verarbeitung
    const downloadForProcessing = async () => {
      const response = await fetch(downloadUrl);
      
      if (!response.ok) {
        const error = await response.json();
        throw new Error(`Download failed: ${error.error}`);
      }
      
      const blob = await response.blob();
      const arrayBuffer = await blob.arrayBuffer();
      
      console.log(`Archive downloaded: ${blob.size} bytes`);
      
      return {
        blob,
        arrayBuffer,
        filename: archiveFilename,
        size: blob.size
      };
    };
    
    // Option C: Archive in lokalen Storage speichern (für Offline-Zugriff)
    const storeArchiveLocally = async () => {
      const archiveData = await downloadForProcessing();
      
      // IndexedDB für große Dateien verwenden
      const request = indexedDB.open('SessionArchives', 1);
      
      request.onsuccess = (event) => {
        const db = event.target.result;
        const transaction = db.transaction(['archives'], 'readwrite');
        const store = transaction.objectStore('archives');
        
        store.put({
          jobId,
          filename: archiveFilename,
          data: archiveData.arrayBuffer,
          timestamp: Date.now(),
          size: archiveData.size
        });
        
        console.log(`Archive stored locally: ${archiveFilename}`);
      };
    };
    
    return {
      triggerUserDownload,
      downloadForProcessing,
      storeArchiveLocally
    };
    
  } catch (error) {
    console.error('Archive download error:', error);
    throw error;
  }
};
```

#### 5. Vollständiger Session-Workflow

```javascript
const processSessionComplete = async (sessionParams) => {
  try {
    // 1. Job erstellen
    console.log('Creating job for session:', sessionParams.session);
    const jobResponse = await fetch('/api/event-job/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_type: "session_processing",
        parameters: { ...sessionParams, create_archive: true }
      })
    });
    
    const { job } = await jobResponse.json();
    console.log('Job created:', job.job_id);
    
    // 2. Status überwachen mit UI-Updates
    const completedJob = await pollJobStatus(job.job_id, (progress) => {
      updateProgressBar(progress.progress?.percent || 0);
      updateStatusText(progress.status);
    });
    
    // 3. Ergebnisse verarbeiten
    const processedResults = await processJobResults(completedJob);
    console.log('Results processed:', processedResults);
    
    // 4. Session-Daten in lokale Datenstruktur speichern
    const sessionEntry = {
      id: job.job_id,
      title: sessionParams.session,
      event: sessionParams.event,
      track: sessionParams.track,
      processedAt: new Date().toISOString(),
      category: categorizeSession(processedResults.sessionData.structuredData),
      hasArchive: processedResults.hasArchive,
      archiveFilename: processedResults.archiveFilename,
      data: processedResults.sessionData
    };
    
    // 5. In lokaler Datenbank speichern
    await storeSessionData(sessionEntry);
    
    // 6. Archive herunterladen (falls vorhanden)
    if (processedResults.hasArchive) {
      const archiveHandler = await downloadAndProcessArchive(
        job.job_id, 
        processedResults.archiveFilename
      );
      
      // Verschiedene Download-Optionen anbieten
      return {
        sessionEntry,
        downloadArchive: archiveHandler.triggerUserDownload,
        processArchive: archiveHandler.downloadForProcessing,
        storeOffline: archiveHandler.storeArchiveLocally
      };
    }
    
    return { sessionEntry };
    
  } catch (error) {
    console.error('Session processing failed:', error);
    throw error;
  }
};

// Lokale Datenspeicherung
const storeSessionData = async (sessionEntry) => {
  const sessions = JSON.parse(localStorage.getItem('processedSessions') || '[]');
  sessions.push(sessionEntry);
  localStorage.setItem('processedSessions', JSON.stringify(sessions));
  
  console.log(`Session ${sessionEntry.title} stored locally`);
};

// UI-Update-Funktionen
const updateProgressBar = (percent) => {
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) {
    progressBar.style.width = `${percent}%`;
    progressBar.textContent = `${percent}%`;
  }
};

const updateStatusText = (status) => {
  const statusText = document.getElementById('status-text');
  if (statusText) {
    statusText.textContent = `Status: ${status}`;
  }
};
```

#### 6. Batch-Verarbeitung mit Worker-Ergebnissen

```javascript
const processBatchSessions = async (sessions) => {
  // 1. Batch erstellen
  const batchResponse = await fetch('/api/event-job/batches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      total_jobs: sessions.length,
      jobs: sessions.map(session => ({
        job_type: "session_processing",
        parameters: { ...session, create_archive: true }
      }))
    })
  });

  const batch = await batchResponse.json();
  console.log(`Batch created: ${batch.batch.batch_id}`);
  
  // 2. Batch-Status überwachen
  const completedJobs = await monitorBatchProgress(batch.batch.batch_id);
  
  // 3. Alle Ergebnisse sammeln und verarbeiten
  const processedSessions = [];
  
  for (const job of completedJobs) {
    if (job.status === 'completed') {
      try {
        const results = await processJobResults(job);
        processedSessions.push({
          jobId: job.job_id,
          sessionData: results.sessionData,
          hasArchive: results.hasArchive,
          archiveFilename: results.archiveFilename
        });
      } catch (error) {
        console.error(`Failed to process job ${job.job_id}:`, error);
      }
    }
  }
  
  // 4. Bulk-Archive-Download anbieten
  const downloadAllArchives = async () => {
    const archivesToDownload = processedSessions.filter(s => s.hasArchive);
    
    for (const session of archivesToDownload) {
      const downloadUrl = `/api/event-job/jobs/${session.jobId}/download-archive`;
      
      // Sequenzieller Download mit Delay
      setTimeout(() => {
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = session.archiveFilename;
        link.click();
      }, archivesToDownload.indexOf(session) * 1000); // 1s Delay zwischen Downloads
    }
  };
  
  return {
    processedSessions,
    downloadAllArchives,
    batchId: batch.batch.batch_id
  };
};

const monitorBatchProgress = async (batchId) => {
  while (true) {
    const response = await fetch(`/api/event-job/batches/${batchId}`);
    const result = await response.json();
    const batch = result.batch;
    
    console.log(`Batch progress: ${batch.completed_jobs}/${batch.total_jobs} completed`);
    
    if (batch.status === 'completed' || batch.status === 'failed') {
      // Alle Jobs des Batches abrufen
      const jobsResponse = await fetch(`/api/event-job/jobs?batch_id=${batchId}`);
      const jobsResult = await jobsResponse.json();
      return jobsResult.jobs;
    }
    
    await new Promise(resolve => setTimeout(resolve, 5000)); // 5s Intervall
  }
};
```

### Synchrone Verarbeitung (für kleine Sessions)

#### 1. ZIP-Daten extrahieren

```javascript
const response = await fetch('/api/session/process', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(sessionData)
});

const result = await response.json();
const archiveData = result.data.output.archive_data;
const archiveFilename = result.data.output.archive_filename;
```

### 2. ZIP herunterladen (Browser)

```javascript
if (archiveData) {
  // Base64 zu Blob konvertieren
  const byteCharacters = atob(archiveData);
  const byteNumbers = new Array(byteCharacters.length);
  
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i);
  }
  
  const byteArray = new Uint8Array(byteNumbers);
  const blob = new Blob([byteArray], { type: 'application/zip' });
  
  // Download triggern
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = archiveFilename;
  link.click();
}
```

### 3. ZIP speichern (Node.js)

```javascript
const fs = require('fs');
const buffer = Buffer.from(archiveData, 'base64');
fs.writeFileSync(archiveFilename, buffer);
```

## ZIP-Archiv-Struktur (Vollständige Verzeichniserhaltung)

```
welcome_fosdem.zip
├── sessions/                        # Basis-Verzeichnis (vollständig erhalten)
│   └── Event_Name/                  # Event-spezifisches Verzeichnis  
│       ├── assets/                  # Gemeinsame Assets für alle Sprachen
│       │   └── session_name/        # Session-spezifische Assets
│       │       ├── slide_01.png
│       │       └── slide_02.png
│       └── LANGUAGE/                # Zielsprache (EN, DE, etc.)
│           └── Track_Name/          # Track-spezifisches Verzeichnis
│               └── session_name.md  # Session Markdown
└── README.md                       # Nutzungshinweise
```

## Pfad-Beibehaltung (Keine Anpassung)

Die Bildpfade im Markdown werden **NICHT** angepasst und bleiben original erhalten:

**Original UND im ZIP-Archiv (unverändert):**
```markdown
![[Event_Name/assets/session_name/slide_01.png|300]]
```

**Vorteile:**
- ✅ 1:1 Wiederherstellung der lokalen Verzeichnisstruktur
- ✅ Mehrsprachige Sessions können gemeinsame Assets verwenden
- ✅ Sofort funktionsfähig nach dem Entpacken
- ✅ Keine Pfadkonvertierung erforderlich

## Deaktivierung der ZIP-Erstellung

Falls das ZIP-Archiv nicht benötigt wird (z.B. für bessere Performance):

```json
{
  "event": "FOSDEM 2025",
  "session": "Welcome to FOSDEM",
  "create_archive": false
}
```

## Fehlerbehebung

### Häufige Probleme

1. **ZIP ist leer**: Keine Anhänge vorhanden oder Bilder konnten nicht gefunden werden
2. **Base64-Dekodierung fehlgeschlagen**: Prüfen, ob `archive_data` vollständig übertragen wurde
3. **Bilder fehlen im ZIP**: Lokale Bildpfade im Cache waren nicht zugänglich

### Logs prüfen

```bash
# Session-Verarbeitung verfolgen
tail -f logs/session_processor.log | grep -i "zip\|archive"
```

#### 7. Fehlerbehandlung und Retry-Strategien

```javascript
class SessionProcessingError extends Error {
  constructor(message, jobId, status, retryable = false) {
    super(message);
    this.name = 'SessionProcessingError';
    this.jobId = jobId;
    this.status = status;
    this.retryable = retryable;
  }
}

const processSessionWithRetry = async (sessionParams, maxRetries = 3) => {
  let lastError;
  
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`Attempt ${attempt}/${maxRetries} for session: ${sessionParams.session}`);
      
      const result = await processSessionComplete(sessionParams);
      console.log(`Success on attempt ${attempt}`);
      return result;
      
    } catch (error) {
      lastError = error;
      console.error(`Attempt ${attempt} failed:`, error.message);
      
      // Prüfe ob Retry sinnvoll ist
      if (!isRetryableError(error) || attempt === maxRetries) {
        break;
      }
      
      // Exponential backoff
      const delay = Math.pow(2, attempt) * 1000;
      console.log(`Waiting ${delay}ms before retry...`);
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }
  
  throw new SessionProcessingError(
    `Failed after ${maxRetries} attempts: ${lastError.message}`,
    null,
    'failed',
    false
  );
};

const isRetryableError = (error) => {
  // Network-Fehler und temporäre Server-Fehler sind retry-fähig
  if (error.name === 'TypeError' && error.message.includes('fetch')) return true;
  if (error.message.includes('timeout')) return true;
  if (error.message.includes('503')) return true;
  if (error.message.includes('502')) return true;
  
  // Job-spezifische Fehler meist nicht retry-fähig
  if (error.message.includes('validation')) return false;
  if (error.message.includes('not found')) return false;
  
  return false;
};

// Fehlerbehandlung mit User-Feedback
const handleSessionProcessingError = (error, sessionParams) => {
  console.error('Session processing error:', error);
  
  // User-freundliche Fehlermeldungen
  let userMessage = 'Die Session konnte nicht verarbeitet werden.';
  let actions = [];
  
  if (error.message.includes('timeout')) {
    userMessage = 'Die Verarbeitung dauert länger als erwartet.';
    actions.push({
      label: 'Erneut versuchen',
      action: () => processSessionWithRetry(sessionParams)
    });
  } else if (error.message.includes('not found')) {
    userMessage = 'Die Session-URL konnte nicht gefunden werden.';
    actions.push({
      label: 'URL überprüfen',
      action: () => console.log('Please check the session URL')
    });
  } else if (error.retryable) {
    userMessage = 'Ein temporärer Fehler ist aufgetreten.';
    actions.push({
      label: 'Erneut versuchen',
      action: () => processSessionWithRetry(sessionParams)
    });
  }
  
  // UI-Benachrichtigung anzeigen
  showErrorNotification(userMessage, actions);
};

const showErrorNotification = (message, actions = []) => {
  // Beispiel-Implementierung für Error-UI
  const notification = document.createElement('div');
  notification.className = 'error-notification';
  notification.innerHTML = `
    <div class="error-message">${message}</div>
    <div class="error-actions">
      ${actions.map(action => 
        `<button onclick="handleAction('${action.label}')">${action.label}</button>`
      ).join('')}
    </div>
  `;
  
  document.body.appendChild(notification);
  
  // Auto-remove nach 10 Sekunden
  setTimeout(() => {
    notification.remove();
  }, 10000);
};
```

## Integration in die Job-Pipeline

### Worker-Client Integration

```javascript
class SessionWorkerClient {
  constructor(baseUrl = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
    this.activeJobs = new Map();
    this.completedSessions = new Map();
  }
  
  async processSession(sessionParams) {
    // Session verarbeiten und lokal tracken
    const result = await processSessionWithRetry(sessionParams);
    
    if (result.sessionEntry) {
      this.completedSessions.set(result.sessionEntry.id, result.sessionEntry);
      this.notifySessionComplete(result.sessionEntry);
    }
    
    return result;
  }
  
  async processBatch(sessions) {
    const results = await processBatchSessions(sessions);
    
    // Batch-Ergebnisse verwalten
    results.processedSessions.forEach(session => {
      this.completedSessions.set(session.jobId, session);
    });
    
    this.notifyBatchComplete(results);
    return results;
  }
  
  // Event-basierte Benachrichtigungen
  notifySessionComplete(sessionEntry) {
    const event = new CustomEvent('sessionComplete', {
      detail: { session: sessionEntry }
    });
    window.dispatchEvent(event);
  }
  
  notifyBatchComplete(batchResults) {
    const event = new CustomEvent('batchComplete', {
      detail: { batch: batchResults }
    });
    window.dispatchEvent(event);
  }
  
  // Lokale Session-Verwaltung
  getCompletedSessions(filter = {}) {
    const sessions = Array.from(this.completedSessions.values());
    
    return sessions.filter(session => {
      if (filter.event && session.event !== filter.event) return false;
      if (filter.track && session.track !== filter.track) return false;
      if (filter.category && session.category !== filter.category) return false;
      if (filter.hasArchive !== undefined && session.hasArchive !== filter.hasArchive) return false;
      
      return true;
    });
  }
  
  async downloadSessionArchive(sessionId) {
    const session = this.completedSessions.get(sessionId);
    if (!session || !session.hasArchive) {
      throw new Error('No archive available for this session');
    }
    
    const downloadUrl = `/api/event-job/jobs/${sessionId}/download-archive`;
    window.open(downloadUrl, '_blank');
  }
}

// Verwendung
const client = new SessionWorkerClient();

// Event-Listener für Session-Updates
window.addEventListener('sessionComplete', (event) => {
  const session = event.detail.session;
  console.log('Session completed:', session.title);
  updateSessionList();
});

window.addEventListener('batchComplete', (event) => {
  const batch = event.detail.batch;
  console.log(`Batch completed: ${batch.processedSessions.length} sessions`);
  updateBatchStatus();
});
```

### MongoDB-Speicherung

Die ZIP-Archive werden vollständig in der MongoDB als Teil der Job-Ergebnisse gespeichert:

```json
{
  "job_id": "job-abc123",
  "status": "completed",
  "results": {
    "markdown_content": "# Session content...",
    "archive_data": "UEsDBBQACAgIAOxPbFkAAA...",  // Base64-ZIP
    "archive_filename": "welcome_fosdem.zip",
    "structured_data": {...},
    "assets": ["image1.png", "image2.png"]
  }
}
```

### Performance-Optimierung

- **Asynchrone Verarbeitung**: ZIP-Erstellung läuft im Hintergrund
- **Einmalige Speicherung**: ZIP wird bei Job-Erstellung generiert und gespeichert
- **Effiziente Übertragung**: Direkter Download ohne Re-Processing
- **Skalierbarkeit**: Worker können parallel ZIP-Archive erstellen

### Fehlerbehandlung

```javascript
// Prüfung auf verfügbare Archive
const checkArchiveAvailability = async (jobId) => {
  const response = await fetch(`/api/event-job/jobs/${jobId}`);
  const job = await response.json();
  
  return {
    hasArchive: !!job.job.results?.archive_data,
    filename: job.job.results?.archive_filename,
    size: job.job.results?.archive_data ? 
           Math.ceil(job.job.results.archive_data.length * 0.75) : 0 // Base64 zu Bytes
  };
};
```

## Best Practices für Worker-Client-Integration

### 1. Job-Management
- **Asynchrone Verarbeitung bevorzugen**: Nutze die Worker-API für alle produktiven Anwendungen
- **Job-IDs tracken**: Speichere Job-IDs lokal für späteren Zugriff auf Ergebnisse
- **Status-Polling optimieren**: Verwende angemessene Polling-Intervalle (2-5 Sekunden)
- **Timeout-Strategien**: Implementiere Client-seitige Timeouts für lange laufende Jobs

```javascript
// Gutes Beispiel: Job-Tracking mit lokalem State
const jobTracker = {
  activeJobs: new Set(),
  completedJobs: new Map(),
  
  addJob(jobId) {
    this.activeJobs.add(jobId);
  },
  
  completeJob(jobId, results) {
    this.activeJobs.delete(jobId);
    this.completedJobs.set(jobId, results);
  }
};
```

### 2. Archive-Management
- **Selective Downloads**: Nur Archive herunterladen, die tatsächlich benötigt werden
- **Batch-Downloads**: Bei vielen Archiven sequenziell mit Delays herunterladen
- **Local Storage**: Große Archive in IndexedDB für Offline-Zugriff speichern
- **Cache-Strategien**: Bereits heruntergeladene Archive lokal verwalten

```javascript
// Archive-Cache-Strategie
const archiveCache = {
  async getArchive(jobId) {
    // 1. Prüfe lokalen Cache
    const cached = await this.getFromIndexedDB(jobId);
    if (cached) return cached;
    
    // 2. Falls nicht vorhanden, von API laden
    const archive = await downloadArchive(jobId);
    await this.storeInIndexedDB(jobId, archive);
    
    return archive;
  }
};
```

### 3. Error Handling
- **Retry-Strategien**: Implementiere intelligente Retry-Logic für temporäre Fehler
- **Graceful Degradation**: Stelle sicher, dass die App auch ohne Archive funktioniert
- **User Feedback**: Gib klare Fehlermeldungen und Lösungsvorschläge
- **Fallback-Optionen**: Biete alternative Wege für fehlgeschlagene Operationen

### 4. Performance-Optimierung
- **Parallel Processing**: Nutze Promise.all für unabhängige Operationen
- **Progressive Loading**: Lade Ergebnisse schrittweise für bessere UX
- **Memory Management**: Entferne nicht mehr benötigte Archive aus dem Speicher
- **Network Optimization**: Batch ähnliche API-Calls zusammen

```javascript
// Parallel Archive-Downloads
const downloadMultipleArchives = async (jobIds) => {
  const batchSize = 3; // Nicht mehr als 3 gleichzeitig
  const results = [];
  
  for (let i = 0; i < jobIds.length; i += batchSize) {
    const batch = jobIds.slice(i, i + batchSize);
    const batchResults = await Promise.all(
      batch.map(jobId => downloadArchive(jobId))
    );
    results.push(...batchResults);
    
    // Kurze Pause zwischen Batches
    if (i + batchSize < jobIds.length) {
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  
  return results;
};
```

### 5. User Experience
- **Progress Indicators**: Zeige Fortschritt für lange laufende Operationen
- **Background Processing**: Verarbeite Jobs im Hintergrund ohne UI-Blockierung
- **Notifications**: Benachrichtige Benutzer über abgeschlossene Verarbeitungen
- **State Persistence**: Behalte den Verarbeitungsstand auch nach Seitenreload

### 6. Monitoring und Debugging
- **Detailed Logging**: Logge alle wichtigen Schritte für Debugging
- **Performance Metrics**: Tracke Verarbeitungszeiten und Erfolgsraten
- **Error Analytics**: Sammle Fehlerstatistiken für Verbesserungen
- **Health Checks**: Überwache Worker-Verfügbarkeit

```javascript
// Monitoring-Beispiel
const sessionMetrics = {
  totalProcessed: 0,
  successRate: 0,
  averageProcessingTime: 0,
  errors: [],
  
  recordSuccess(duration) {
    this.totalProcessed++;
    this.updateAverageTime(duration);
    this.updateSuccessRate();
  },
  
  recordError(error) {
    this.errors.push({
      message: error.message,
      timestamp: new Date().toISOString(),
      retryable: error.retryable
    });
    this.updateSuccessRate();
  }
};
```

### 7. Sicherheit und Datenschutz
- **Secure Downloads**: Prüfe Download-Integrität bei kritischen Archiven
- **Data Validation**: Validiere Worker-Ergebnisse vor der Verwendung
- **Access Control**: Respektiere Job-Zugriffsrechte auf Client-Seite
- **Sensitive Data**: Behandle Session-Inhalte entsprechend ihrer Sensitivität 