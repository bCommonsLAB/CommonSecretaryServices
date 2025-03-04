/**
 * Event-Monitor JavaScript-Funktionen
 */

// Debug-Logging-System für Event-Monitor
const DEBUG_LOG = {
  // Logging aktivieren/deaktivieren
  enabled: false, // Logging standardmäßig deaktivieren
  
  // Zeitstempel für die Startzeit
  startTime: performance.now(),
  
  // Speicher für alle Logs - begrenze Anzahl der Logs
  logs: [],
  maxLogs: 100, // Maximal 100 Logs speichern
  
  // Logging-Levels
  LEVELS: {
    INFO: 'INFO',
    DEBUG: 'DEBUG',
    ERROR: 'ERROR',
    API: 'API',
    EVENT: 'EVENT',
    LOAD: 'LOAD',
    DECISION: 'DECISION'
  },
  
  // Farbcodes für die verschiedenen Levels in der Konsole
  COLORS: {
    INFO: 'color: #0066cc',
    DEBUG: 'color: #666666',
    ERROR: 'color: #cc0000',
    API: 'color: #cc00cc',
    EVENT: 'color: #009900',
    LOAD: 'color: #ff6600',
    DECISION: 'color: #9900cc'
  },
  
  // Hauptlogging-Funktion
  log: function(level, message, data = null) {
    if (!this.enabled) return;
    
    const now = performance.now();
    const timeSinceStart = (now - this.startTime).toFixed(2);
    
    const logEntry = {
      level,
      time: new Date().toISOString(),
      timeSinceStart: `+${timeSinceStart}ms`,
      message,
      data
    };
    
    // Begrenze die Anzahl der Logs
    if (this.logs.length >= this.maxLogs) {
      this.logs.shift(); // Entferne ältesten Log
    }
    
    this.logs.push(logEntry);
    
    // In Konsole ausgeben für Entwickler
    console.log(`[${level}][${logEntry.timeSinceStart}] ${message}`);
    
    return logEntry;
  },
  
  // Hilfsfunktionen für die verschiedenen Levels
  info: function(message, data) {
    return this.log(this.LEVELS.INFO, message, data);
  },
  
  debug: function(message, data) {
    return this.log(this.LEVELS.DEBUG, message, data);
  },
  
  error: function(message, data) {
    return this.log(this.LEVELS.ERROR, message, data);
  },
  
  api: function(message, data) {
    return this.log(this.LEVELS.API, message, data);
  },
  
  event: function(message, data) {
    return this.log(this.LEVELS.EVENT, message, data);
  },
  
  load: function(message, data) {
    return this.log(this.LEVELS.LOAD, message, data);
  },
  
  decision: function(message, data) {
    return this.log(this.LEVELS.DECISION, message, data);
  },
  
  // Log-Bericht generieren
  getReport: function() {
    return {
      startTime: new Date(this.startTime).toISOString(),
      totalEntries: this.logs.length,
      logs: this.logs
    };
  },
  
  // Log-Bericht in der Konsole ausgeben
  printReport: function() {
    console.group('Debug-Log-Bericht');
    console.log(`Gesamtanzahl der Log-Einträge: ${this.logs.length}`);
    console.table(this.logs.map(log => ({
      level: log.level,
      timeSinceStart: log.timeSinceStart,
      message: log.message
    })));
    console.groupEnd();
  },
  
  // Alle Logs zurücksetzen
  reset: function() {
    this.logs = [];
    this.startTime = performance.now();
    this.info('Logging zurückgesetzt');
  },
  
  // Speichern des Log-Berichts in der Console als JSON
  saveToConsole: function() {
    const reportObj = this.getReport();
    console.log('%cDEBUG-LOG-BERICHT', 'font-size: 16px; font-weight: bold; color: #0066cc');
    console.log('Um den vollständigen Bericht zu erhalten, kopiere den folgenden Befehl in die Konsole:');
    console.log('copy(DEBUG_LOG.getReport())');
    console.log('Oder klicke auf das nebenstehende Objekt, um es zu expandieren:', reportObj);
    return reportObj;
  }
};

// Initialen Start-Log erstellen
DEBUG_LOG.info('Event-Monitor-Script initialisiert');

// Globale Variable für Batch-Ladezustand
let initialBatchLoaded = false;

// Funktion zum Öffnen von Batches mit aktiven Jobs
function openBatchesWithActiveJobs() {
  // Diese Funktion wurde deaktiviert, um die Ladezeit zu verbessern
  // Keine automatische Erkennung von Batches mit aktiven Jobs mehr
  return;
}

// Funktion zum Aktualisieren aller Batch-Daten
function updateAllBatchData(shouldOpenNewActiveBatches = false) {
  // Einfacher Seitenreload statt komplexer dynamischer Updates
  if (confirm('Möchten Sie die Seite aktualisieren, um die neuesten Daten anzuzeigen?')) {
    location.reload();
  }
}

// Funktion zum Aktualisieren der Jobs für einen Batch
function updateJobsForBatch(batchId, batchIndex, isArchive = false) {
  DEBUG_LOG.load(`updateJobsForBatch aufgerufen für Batch ${batchId}, Index ${batchIndex}, isArchive=${isArchive}`);
  
  const prefix = isArchive ? 'archive-' : '';
  const tableSelector = `#batch-jobs-${prefix}${batchIndex}`;
  const table = document.querySelector(tableSelector);
  
  if (!table || table.classList.contains('d-none')) {
    DEBUG_LOG.decision(`Überspringe Job-Update für Batch ${batchId}, da Tabelle nicht sichtbar ist`);
    return Promise.resolve(false);
  }
  
  DEBUG_LOG.api(`API-Anfrage für Jobs von Batch ${batchId} wird gesendet`);
  return fetch(`/api/dashboard/event-monitor/jobs?batch_id=${batchId}`)
    .then(response => {
      if (!response.ok) {
        DEBUG_LOG.error(`API-Fehler für Jobs von Batch ${batchId}: ${response.status}`);
        throw new Error(`Netzwerkantwort war nicht ok für Jobs von Batch ${batchId}`);
      }
      return response.json();
    })
    .then(data => {
      let jobs = [];
      
      // Versuche, Jobs aus verschiedenen Strukturen zu extrahieren
      if (data.data && data.data.jobs) {
        DEBUG_LOG.info(`Jobs gefunden in data.data.jobs: ${data.data.jobs.length} Jobs`);
        jobs = data.data.jobs;
      } else if (data.jobs) {
        DEBUG_LOG.info(`Jobs gefunden in data.jobs: ${data.jobs.length} Jobs`);
        jobs = data.jobs;
      } else {
        DEBUG_LOG.error(`Keine Jobs in der Antwort gefunden!`, data);
        return false;
      }
      
      if (!jobs.length) {
        DEBUG_LOG.info(`Keine Jobs für Batch ${batchId} gefunden`);
        return false;
      }
      
      // Jobs nach IDs gruppieren für schnelleren Vergleich
      const existingJobElements = table.querySelectorAll('tr.job-row');
      const existingJobMap = new Map();
      
      existingJobElements.forEach(element => {
        const jobId = element.getAttribute('data-job-id');
        if (jobId) existingJobMap.set(jobId, element);
      });
      
      DEBUG_LOG.info(`${existingJobElements.length} existierende Jobs im DOM gefunden`);
      
      let hasChanges = false;
      
      // Für jeden Job prüfen, ob Aktualisierung nötig ist
      jobs.forEach(job => {
        const existingElement = existingJobMap.get(job.job_id);
        
        if (existingElement) {
          // Prüfen, ob sich der Status geändert hat
          const statusBadge = existingElement.querySelector('.status-badge');
          const currentStatus = statusBadge ? statusBadge.textContent.trim().toLowerCase() : '';
          const newStatus = job.status.toLowerCase();
          
          if (currentStatus !== newStatus) {
            DEBUG_LOG.info(`Status für Job ${job.job_id} hat sich geändert: ${currentStatus} -> ${newStatus}`);
            
            // Status-Badge aktualisieren
            statusBadge.className = `status-badge ${getStatusBadgeClass(job.status)}`;
            statusBadge.textContent = job.status.charAt(0).toUpperCase() + job.status.slice(1);
            
            // Element hervorheben
            highlightUpdatedElement(existingElement);
            
            hasChanges = true;
          }
          
          // Fortschritt prüfen und aktualisieren
          const progressTd = existingElement.querySelector('td:nth-child(5)');
          if (progressTd && job.progress !== undefined) {
            const newProgressHTML = job.progress ? getProgressHTML(job.progress) : '-';
            
            if (progressTd.innerHTML !== newProgressHTML) {
              DEBUG_LOG.info(`Fortschritt für Job ${job.job_id} hat sich geändert`);
              progressTd.innerHTML = newProgressHTML;
              highlightUpdatedElement(existingElement);
              hasChanges = true;
            }
          }
          
          // Abschlussdatum prüfen und aktualisieren
          const completedTd = existingElement.querySelector('td:nth-child(4)');
          if (completedTd) {
            const newCompletedText = job.completed_at ? formatDateTime(job.completed_at) : '-';
            
            if (completedTd.textContent !== newCompletedText) {
              DEBUG_LOG.info(`Abschlussdatum für Job ${job.job_id} hat sich geändert`);
              completedTd.textContent = newCompletedText;
              highlightUpdatedElement(existingElement);
              hasChanges = true;
            }
          }
        } else {
          DEBUG_LOG.info(`Neuer Job ${job.job_id} gefunden, wird nicht automatisch hinzugefügt`);
          // Hier könnten wir neue Jobs hinzufügen, aber das würde die UI unnötig verändern
        }
      });
      
      if (hasChanges) {
        DEBUG_LOG.info(`Jobs für Batch ${batchId} wurden aktualisiert`);
      } else {
        DEBUG_LOG.info(`Keine Änderungen an Jobs für Batch ${batchId} notwendig`);
      }
      
      return hasChanges;
    })
    .catch(error => {
      DEBUG_LOG.error(`Fehler beim Aktualisieren der Jobs für Batch ${batchId}`, error);
      return false;
    });
}

// Funktion zum Aktualisieren der Daten
function refreshData() {
  DEBUG_LOG.event(`refreshData aufgerufen`);
  
  // Immer Seite neu laden für einfachsten und zuverlässigsten Refresh
  location.reload();
}

// Helper Funktionen
function getStatusBadgeClass(status) {
  switch(status) {
    case 'completed': return 'status-completed';
    case 'failed': return 'status-failed';
    case 'processing': return 'status-processing';
    case 'pending': return 'status-pending';
    default: return 'bg-secondary';
  }
}

function getProgressHTML(progress) {
  if (!progress || !progress.percent) return '-';
  return `
    <div>
      <div class="progress" style="width: 100px;">
        <div class="progress-bar" role="progressbar" style="width: ${progress.percent}%;" 
             aria-valuenow="${progress.percent}" aria-valuemin="0" aria-valuemax="100"></div>
      </div>
      <span class="small text-muted">${progress.percent}%</span>
    </div>
  `;
}

function formatDateTime(dateString) {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return date.toLocaleString('de-DE');
}

// Performance-Logging-Funktion
function logPerformance(operation, details) {
  const perfData = {
    operation,
    timestamp: new Date().toISOString(),
    ...details
  };
  console.log(`PERFORMANCE: ${operation}`, perfData);
  
  // In Produktionsumgebung könnte hier ein Logging-Service verwendet werden
  // sendToAnalytics(perfData);
}

// Hilfsfunktion zum Hervorheben aktualisierter Elemente
function highlightUpdatedElement(element) {
  // Klasse hinzufügen/entfernen für Animation
  element.classList.add('highlight-update');
  
  // Falls es bereits einen Timer für dieses Element gibt, löschen
  if (element._highlightTimeout) {
    clearTimeout(element._highlightTimeout);
  }
  
  // Neuen Timer setzen
  element._highlightTimeout = setTimeout(() => {
    element.classList.remove('highlight-update');
    element._highlightTimeout = null;
  }, 1500);
}

// Als globale Funktion definieren, damit sie über onclick aufrufbar ist
window.loadJobsForBatch = function(batchId, batchIndex, isAutoOpen = false) {
  console.log(`loadJobsForBatch aufgerufen für Batch ${batchId}, Index ${batchIndex}`);
  
  // Überprüfe, ob wir es mit einem Archiv-Batch zu tun haben
  const isArchive = typeof batchIndex === 'string' && batchIndex.startsWith('archive-');
  
  // Bestimme die korrekten Container-IDs basierend auf Typ (normal oder archiv)
  let jobsContainerId, tableContainerId, loadingSpinnerId, toggleButtonId;
  
  if (isArchive) {
    // Format für Archiv-Batches
    const archiveIndex = batchIndex.replace('archive-', '');
    jobsContainerId = `archive-jobs-container-${archiveIndex}`;
    tableContainerId = `table-container-archive-${archiveIndex}`;
    loadingSpinnerId = `jobs-loading-archive-${archiveIndex}`;
    toggleButtonId = `jobs-toggle-text-archive-${archiveIndex}`;
  } else {
    // Format für normale Batches
    jobsContainerId = `jobs-container-${batchIndex}`;
    tableContainerId = `table-container-${batchIndex}`;
    loadingSpinnerId = `jobs-loading-${batchIndex}`;
    toggleButtonId = `jobs-toggle-text-${batchIndex}`;
  }
  
  // Hole die DOM-Elemente mit den korrekten IDs
  const jobsContainer = document.getElementById(jobsContainerId);
  const tableContainer = document.getElementById(tableContainerId);
  const loadingSpinner = document.getElementById(loadingSpinnerId);
  const toggleButton = document.getElementById(toggleButtonId);
  
  // Sicherheitsprüfung: Wenn Container nicht gefunden wurden
  if (!jobsContainer || !tableContainer) {
    console.error(`Container nicht gefunden: jobs=${jobsContainerId}, table=${tableContainerId}`);
    return;
  }
  
  // Prüfen, ob der Klick zum Schließen oder Öffnen gedacht ist
  const isOpening = tableContainer.classList.contains('d-none');
  
  // Toggle der Sichtbarkeit
  if (isOpening) {
    // Tabelle anzeigen
      tableContainer.classList.remove('d-none');
      if (toggleButton) {
        toggleButton.textContent = 'Jobs verstecken';
    }
    
    // Prüfen ob Daten bereits geladen wurden
    if (jobsContainer.getAttribute('data-loaded') === 'true') {
      console.log(`Jobs für Batch ${batchId} wurden bereits geladen, zeige aus Cache an`);
    return;
  }
  
    // Benutzer-Feedback während des Ladens anzeigen
    jobsContainer.innerHTML = `<tr><td colspan="6" class="text-center py-3">
      <div class="spinner-border spinner-border-sm text-primary me-2" role="status"></div>
      <span>Lade Jobs...</span>
    </td></tr>`;
  
  // API-Anfrage an den Batch-Jobs-Endpunkt
    console.log(`API-Anfrage für Jobs von Batch ${batchId} wird gesendet`);
  fetch(`/api/dashboard/event-monitor/jobs?batch_id=${batchId}`)
      .then(response => {
        if (!response.ok) {
          throw new Error(`Netzwerkantwort war nicht ok für Jobs von Batch ${batchId}`);
        }
        return response.json();
      })
    .then(data => {
      // Versuche, die Jobs aus der Antwort zu extrahieren
      let jobs = [];
      
      // Prüfe verschiedene mögliche Strukturen
      if (data.data && data.data.jobs) {
          console.log(`Jobs gefunden in data.data.jobs: ${data.data.jobs.length} Jobs`);
        jobs = data.data.jobs;
      } else if (data.jobs) {
          console.log(`Jobs gefunden in data.jobs: ${data.jobs.length} Jobs`);
        jobs = data.jobs;
      } else {
          console.error(`Keine Jobs in der Antwort gefunden!`, data);
      }
      
      if (loadingSpinner) {
        loadingSpinner.classList.add('d-none');
      }
      
      if (jobs && jobs.length > 0) {
        console.log(`Verarbeite ${jobs.length} Jobs für Batch ${batchId}`);
        
        // Jobs markieren als geladen
        jobsContainer.setAttribute('data-loaded', 'true');
        // HTML für die Jobs generieren
          const jobsHTML = jobs.map((job) => {
            // Bestimme Button-Klasse und Tooltip basierend auf Status
            let reloadButtonClass = 'btn-outline-warning';  // Standard für failed
            let reloadButtonTooltip = 'Job neu starten';
            let reloadButtonDisabled = '';
            
            switch(job.status) {
              case 'completed':
                reloadButtonClass = 'btn-outline-secondary';
                reloadButtonTooltip = 'Abgeschlossenen Job neu starten';
                break;
              case 'processing':
                reloadButtonClass = 'btn-outline-secondary';
                reloadButtonTooltip = 'Laufender Job kann nicht neu gestartet werden';
                break;
              case 'failed':
                reloadButtonClass = 'btn-outline-warning';
                reloadButtonTooltip = 'Fehlgeschlagenen Job neu starten';
                break;
              default:
                reloadButtonClass = 'btn-outline-secondary';
                reloadButtonTooltip = 'Job neu starten';
            }

            return `<tr class="job-row" data-job-id="${job.job_id}" data-batch-id="${batchId}">
              <td>
                <span class="status-badge ${getStatusBadgeClass(job.status)}">
                  ${job.status.charAt(0).toUpperCase() + job.status.slice(1)}
                </span>
              </td>
              <td>
                <a href="#" onclick="showJobDetails('${job.job_id}'); return false;" class="text-decoration-none">
                  <strong>${job.job_name || job.job_id}</strong>
                </a>
              </td>
              <td>${formatDateTime(job.created_at)}</td>
              <td>${job.completed_at ? formatDateTime(job.completed_at) : '-'}</td>
              <td>
                ${job.progress ? getProgressHTML(job.progress) : '-'}
              </td>
              <td>
                <div class="btn-group btn-group-sm" role="group">
                  <button type="button" class="btn btn-outline-primary" title="Details anzeigen" 
                          onclick="showJobDetails('${job.job_id}'); return false;">
                    <i class="fas fa-info-circle"></i>
                </button>
                  <button type="button" class="btn ${reloadButtonClass}" title="${reloadButtonTooltip}" 
                          onclick="restartJob('${job.job_id}', '${job.job_type}'); return false;" ${reloadButtonDisabled}>
                    <i class="fas fa-redo-alt"></i>
                  </button>
                  <button type="button" class="btn btn-outline-danger" title="Job löschen" 
                          onclick="deleteJob('${job.job_id}'); return false;">
                    <i class="fas fa-trash-alt"></i>
                  </button>
              </div>
            </td>
            </tr>`;
          }).join('');
          
          // Jobs in den Container einfügen
          jobsContainer.innerHTML = jobsHTML;
          
          console.log(`Jobs für Batch ${batchId} erfolgreich geladen und gerendert`);
      } else {
        // Keine Jobs gefunden
        jobsContainer.innerHTML = `
          <tr>
              <td colspan="6" class="text-center py-3">
              <div class="alert alert-info mb-0">
                  <i class="fas fa-info-circle me-2"></i> Keine Jobs für diesen Batch gefunden.
              </div>
            </td>
          </tr>
        `;
          console.log(`Keine Jobs für Batch ${batchId} gefunden`);
      }
    })
    .catch(error => {
        // Fehlerbehandlung
      jobsContainer.innerHTML = `
        <tr>
            <td colspan="6" class="text-center py-3">
            <div class="alert alert-danger mb-0">
                <i class="fas fa-exclamation-circle me-2"></i> 
              Fehler beim Laden der Jobs: ${error.message}
            </div>
          </td>
        </tr>
      `;
        console.error('Fehler beim Laden der Jobs:', error);
      });
  } else {
    // Schließe den Batch
    tableContainer.classList.add('d-none');
    if (toggleButton) {
      toggleButton.textContent = 'Jobs anzeigen';
    }
  }
};

// Dokument geladen
document.addEventListener('DOMContentLoaded', function() {
  DEBUG_LOG.event('DOMContentLoaded Event ausgelöst');
  
  // Auto-Refresh-Switch - deaktiviert
  const autoRefreshSwitch = document.getElementById('autoRefreshSwitch');
  if (autoRefreshSwitch) {
    DEBUG_LOG.info('Auto-Refresh-Switch gefunden, wird deaktiviert');
    autoRefreshSwitch.checked = false;
    autoRefreshSwitch.disabled = true;
  }
  
  // Manueller Refresh-Button
  const refreshButton = document.getElementById('manualRefreshButton');
  if (refreshButton) {
    DEBUG_LOG.info('Manueller Refresh-Button gefunden, Initialisierung');
    refreshButton.addEventListener('click', function() {
      DEBUG_LOG.event('Manueller Refresh-Button geklickt');
      refreshData();
    });
  }
  
  // Archiv-Tab wechseln
  const archiveTab = document.getElementById('archive-tab');
  if (archiveTab) {
    DEBUG_LOG.info('Archiv-Tab gefunden, Initialisierung');
    archiveTab.addEventListener('click', function() {
      DEBUG_LOG.event('Archiv-Tab geklickt');
      loadArchive();
    });
  }
  
  // Logge, dass die Initialisierung abgeschlossen ist
  DEBUG_LOG.info('Event-Monitor Initialisierung abgeschlossen');
});

// Funktion zum Umschalten des Aktiv-Status eines Batches als globale Funktion definieren
window.toggleBatchActive = function(batchId, button) {
  if (!batchId) return;
  
  // Status vor Anfrage umschalten (optimistische UI-Aktualisierung)
  const isCurrentlyActive = button.classList.contains('btn-success');
  const card = button.closest('.card');
  
  // UI aktualisieren (optimistisch)
  if (isCurrentlyActive) {
    button.classList.remove('btn-success');
    button.classList.add('btn-outline-secondary');
    button.innerHTML = '<i class="fas fa-toggle-off"></i>';
    button.title = "Batch aktivieren";
    card.classList.remove('batch-active');
    card.classList.add('batch-inactive');
    const activeBadge = card.querySelector('.active-badge');
    if (activeBadge) {
      activeBadge.classList.remove('active-badge');
      activeBadge.classList.add('inactive-badge');
      activeBadge.textContent = "Inaktiv";
    }
  } else {
    button.classList.remove('btn-outline-secondary');
    button.classList.add('btn-success');
    button.innerHTML = '<i class="fas fa-toggle-on"></i>';
    button.title = "Batch deaktivieren";
    card.classList.remove('batch-inactive');
    card.classList.add('batch-active');
    const inactiveBadge = card.querySelector('.inactive-badge');
    if (inactiveBadge) {
      inactiveBadge.classList.remove('inactive-badge');
      inactiveBadge.classList.add('active-badge');
      inactiveBadge.textContent = "Aktiv";
    }
  }
  
  // Element hervorheben
  highlightUpdatedElement(card);
  
  // API-Anfrage zum Umschalten des Status
  fetch(`/api/dashboard/event-monitor/batches/${batchId}/toggle-active`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      isActive: !isCurrentlyActive
    })
  })
  .then(response => response.json())
  .then(data => {
    if (data.status !== 'success') {
      // Bei Fehler UI zurücksetzen und Fehler anzeigen
      console.error('Fehler beim Ändern des Aktiv-Status:', data.message);
      alert(`Fehler: ${data.message}`);
      
      // UI zurücksetzen
      toggleBatchActive(batchId, button);
    } else {
      console.log('Aktiv-Status erfolgreich geändert:', data);
    }
  })
  .catch(error => {
    console.error('Fehler bei der API-Anfrage:', error);
    alert('Fehler bei der Anfrage: ' + error.message);
    
    // UI zurücksetzen
    toggleBatchActive(batchId, button);
  });
};

// Funktionen für Aktionen, die in der HTML-Datei aufgerufen werden, als globale Funktionen definieren
window.showJobDetails = function(jobId, batchId) {
  console.log(`Job-Details für Job ${jobId} von Batch ${batchId} anzeigen`);
  
  // Modal vorbereiten und anzeigen
  const modalElement = document.getElementById('jobDetailsModal');
  const modalContent = modalElement.querySelector('.modal-body');
  modalContent.innerHTML = `
    <div class="text-center py-4">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Laden...</span>
      </div>
    </div>
  `;
  
  // Bootstrap-Modal-Objekt erstellen und anzeigen
  const bsModal = new bootstrap.Modal(modalElement);
  bsModal.show();

  // API-Anfrage für Jobdetails
  fetch(`/api/dashboard/event-monitor/job/${jobId}`)
    .then(response => {
      // Prüfen, ob die Antwort erfolgreich war
      if (!response.ok) {
        throw new Error(`HTTP Fehler: ${response.status} ${response.statusText}`);
      }
      
      // Prüfen, ob die Antwort ein JSON-Format hat
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Die API-Antwort enthält kein gültiges JSON-Format. Möglicherweise fehlt die API-Route für Job-Details im Backend.');
      }
      
      return response.json();
    })
    .then(data => {
      console.log('Job Details:', data);
      
      let job = null;
      if (data.data && data.data.job) {
        job = data.data.job;
      } else if (data.job) {
        job = data.job;
      }
      
      if (!job) {
        modalContent.innerHTML = '<div class="alert alert-danger">Job-Details konnten nicht geladen werden. Die API-Antwort enthält keine Job-Daten.</div>';
        return;
      }
      
      // Jobdetails anzeigen
      modalContent.innerHTML = `
        <table class="table table-bordered table-striped">
          <tbody>
            <tr>
              <th class="align-middle bg-light" style="width: 20%">Status</th>
              <td><span class="status-badge ${getStatusBadgeClass(job.status)}">${job.status}</span></td>
            </tr>
            <tr>
              <th class="align-middle bg-light">Job ID</th>
              <td class="text-monospace small">${job.job_id}</td>
            </tr>
            <tr>
              <th class="align-middle bg-light">Batch ID</th>
              <td class="text-monospace small">${job.batch_id || '-'}</td>
            </tr>
            <tr>
              <th class="align-middle bg-light">Erstellt</th>
              <td>${formatDateTime(job.created_at)}</td>
            </tr>
            <tr>
              <th class="align-middle bg-light">Gestartet</th>
              <td>${job.started_at ? formatDateTime(job.started_at) : '-'}</td>
            </tr>
            <tr>
              <th class="align-middle bg-light">Abgeschlossen</th>
              <td>${job.completed_at ? formatDateTime(job.completed_at) : '-'}</td>
            </tr>
            ${job.progress ? `
            <tr>
              <th>Fortschritt</th>
              <td>
                <div class="progress mb-1">
                  <div class="progress-bar" role="progressbar" style="width: ${job.progress.percent}%;" 
                      aria-valuenow="${job.progress.percent}" aria-valuemin="0" aria-valuemax="100"></div>
                </div>
                <div class="small text-muted">
                  ${job.progress.message || `${job.progress.percent}%`}
                </div>
              </td>
            </tr>
            ` : ''}
            <tr>
              <th>Parameter</th>
              <td><pre class="job-details-content mb-0">${JSON.stringify(job.parameters, null, 2)}</pre></td>
            </tr>
            ${job.results ? `
            <tr>
              <th>Ergebnisse</th>
              <td><pre class="job-details-content mb-0">${JSON.stringify(job.results, null, 2)}</pre></td>
            </tr>
            ` : ''}
            ${job.error ? `
            <tr>
              <th>Fehler</th>
              <td class="job-details-content log-entry-error">
                <strong>${job.error.message || 'Unbekannter Fehler'}</strong>
                ${job.error.details ? `<pre class="mt-2 mb-0">${JSON.stringify(job.error.details, null, 2)}</pre>` : ''}
              </td>
            </tr>
            ` : ''}
            ${job.logs && job.logs.length > 0 ? `
            <tr>
              <th>Logs</th>
              <td class="job-details-content p-0">
                ${job.logs.map(log => `
                  <div class="log-entry ${log.level === 'error' ? 'log-entry-error' : log.level === 'warning' ? 'log-entry-warning' : ''} p-2">
                    [${formatDateTime(log.timestamp)}] ${log.message}
                  </div>
                `).join('')}
              </td>
            </tr>
            ` : ''}
          </tbody>
        </table>
      `;
    })
    .catch(error => {
      console.error('Fehler beim Laden der Job-Details:', error);
      
      // Detaillierte Fehlermeldung anzeigen
      modalContent.innerHTML = `
        <div class="alert alert-danger">
          <h5>Fehler beim Laden der Job-Details</h5>
          <p>${error.message}</p>
          <hr>
          <p class="mb-0"><strong>Mögliche Ursachen:</strong></p>
          <ul>
            <li>Die API-Route für Job-Details (/api/dashboard/event-monitor/job/${jobId}) existiert nicht.</li>
            <li>Der Server ist nicht erreichbar.</li>
            <li>Es gibt ein Problem mit der Datenbankverbindung.</li>
          </ul>
          <hr>
          <p class="mb-0">Technische Details für den Administrator:</p>
          <code>JobID: ${jobId}, BatchID: ${batchId}</code>
        </div>
      `;
    });
};

window.restartJob = function(jobId, batchId) {
  console.log(`Job ${jobId} von Batch ${batchId} neu starten`);
  
  // Bestätigung vom Benutzer einholen
  if (!confirm('Möchten Sie diesen Job wirklich neu starten?')) {
    return;
  }
  
  // Zeige Ladeindikator
  const statusElement = document.querySelector(`tr[data-job-id="${jobId}"] td:first-child`);
  const originalContent = statusElement ? statusElement.innerHTML : '';
  if (statusElement) {
    statusElement.innerHTML = `<div class="spinner-border spinner-border-sm text-primary" role="status">
      <span class="visually-hidden">Laden...</span>
    </div>`;
  }
  
  // API-Anfrage zum Neustarten des Jobs
  fetch(`/api/dashboard/event-monitor/job/${jobId}/restart`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ batch_id: batchId })
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`HTTP Fehler: ${response.status} ${response.statusText}`);
    }
    return response.json();
  })
  .then(data => {
    console.log('Job Neustart erfolgreich:', data);
    
    // Erfolgsmeldung anzeigen
    const toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white bg-success border-0 position-fixed bottom-0 end-0 m-3';
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          Job wurde erfolgreich für den Neustart markiert.
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    document.body.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Optional: Seite nach kurzer Verzögerung neu laden, um den neuen Status anzuzeigen
    setTimeout(() => {
      window.location.reload();
    }, 3000);
  })
  .catch(error => {
    console.error('Fehler beim Neustarten des Jobs:', error);
    
    // Fehlermeldung anzeigen
    alert(`Fehler beim Neustarten des Jobs: ${error.message}`);
    
    // Status-Element zurücksetzen
    if (statusElement) {
      statusElement.innerHTML = originalContent;
    }
  });
};

window.deleteJob = function(jobId, element, batchId) {
  // Bestätigung vom Benutzer einholen mit deutlicher Warnung
  if (!confirm('ACHTUNG: Möchten Sie diesen Job wirklich UNWIDERRUFLICH LÖSCHEN? Diese Aktion kann nicht rückgängig gemacht werden!')) {
    return;
  }
  
  // Lade-Animation anzeigen
  const row = element.closest('tr');
  const statusCell = row.querySelector('td:first-child');
  const originalContent = statusCell.innerHTML;
  statusCell.innerHTML = '<div class="spinner-border spinner-border-sm text-danger" role="status"><span class="visually-hidden">Wird gelöscht...</span></div> Wird gelöscht...';
  
  // API-Anfrage zum Löschen des Jobs
  fetch(`/api/dashboard/event-monitor/jobs/${jobId}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json'
    }
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`HTTP Fehler: ${response.status} ${response.statusText}`);
    }
    return response.json();
  })
  .then(data => {
    if (data.status === 'success') {
      // Erfolgreich gelöscht
      console.log('Job erfolgreich gelöscht:', data);
      
      // Erfolgsanimation und Entfernen der Zeile
      row.style.backgroundColor = '#ffebee';
      setTimeout(() => {
        row.style.opacity = '0';
        row.style.height = '0';
        row.style.overflow = 'hidden';
        row.style.transition = 'all 0.5s ease';
        
        setTimeout(() => {
          row.remove();
          
          // Erfolgsmeldung anzeigen
          const toast = document.createElement('div');
          toast.className = 'toast align-items-center text-white bg-danger border-0 position-fixed bottom-0 end-0 m-3';
          toast.setAttribute('role', 'alert');
          toast.setAttribute('aria-live', 'assertive');
          toast.setAttribute('aria-atomic', 'true');
          toast.innerHTML = `
            <div class="d-flex">
              <div class="toast-body">
                Job wurde erfolgreich gelöscht.
              </div>
              <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
          `;
          document.body.appendChild(toast);
          
          const bsToast = new bootstrap.Toast(toast);
          bsToast.show();
          
          // Aktualisiere Zähler und Batch-Statistiken, falls vorhanden
          if (batchId) {
            const batchElement = document.querySelector(`[data-batch-id="${batchId}"]`);
            if (batchElement) {
              const statsElement = batchElement.querySelector('.batch-status');
              if (statsElement) {
                // Hier könnte eine Funktion aufgerufen werden, die die Statistik aktualisiert
                // updateBatchStatistics(batchId);
              }
            }
          }
        }, 500);
      }, 500);
    } else {
      // Fehler beim Löschen
      statusCell.innerHTML = originalContent;
      alert(`Fehler beim Löschen: ${data.message || 'Unbekannter Fehler'}`);
    }
  })
  .catch(error => {
    console.error('Fehler beim Löschen des Jobs:', error);
    
    // Fehlermeldung anzeigen
    statusCell.innerHTML = originalContent;
    alert(`Fehler beim Löschen des Jobs: ${error.message}`);
  });
};

window.restartBatch = function(batchId) {
  console.log(`Batch ${batchId} neu starten`);
  
  if (!confirm(`Möchten Sie wirklich nicht erledigte Jobs im Batch ${batchId} neu starten?`)) {
    return;
  }
  
  // Loading-Indikator anzeigen oder Button sperren
  const batchElement = document.querySelector(`.card[data-batch-id="${batchId}"]`);
  if (batchElement) {
    batchElement.classList.add('processing');
  }
  
  // API-Anfrage zum Neustarten aller Jobs im Batch
  fetch(`/api/dashboard/event-monitor/batches/${batchId}/restart`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    }
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`HTTP-Fehler: ${response.status}`);
    }
    return response.json();
  })
  .then(data => {
    console.log('Antwort vom Batch-Neustart:', data);
    
    if (data.status === 'success') {
      alert(`Batch wurde erfolgreich neu gestartet. ${data.message || ''}`);
      
      // Sofortiger Reload ohne Verzögerung
        window.location.reload();
    } else {
      alert(`Fehler beim Neustarten des Batches: ${data.message || 'Unbekannter Fehler'}`);
      
      // Loading-Indikator entfernen
      if (batchElement) {
        batchElement.classList.remove('processing');
      }
    }
  })
  .catch(error => {
    console.error('Fehler beim Neustarten des Batches:', error);
    alert(`Fehler beim Neustarten des Batches: ${error.message}`);
    
    // Loading-Indikator entfernen
    if (batchElement) {
      batchElement.classList.remove('processing');
    }
  });
};

window.deleteBatch = function(batchId) {
  // Eine klarere und aussagekräftige Warnung anzeigen
  if (!confirm(`⚠️ WARNUNG ⚠️\n\nMöchten Sie wirklich ALLE JOBS in Batch ${batchId} UNWIDERRUFLICH LÖSCHEN?\nDiese Aktion kann NICHT rückgängig gemacht werden und löscht alle Daten permanent!`)) {
    return;
  }
  
  // Lade-Animation anzeigen
  const batchCard = document.querySelector(`.card[data-batch-id="${batchId}"]`);
  if (batchCard) {
    batchCard.style.backgroundColor = '#ffebee';
    batchCard.style.transition = 'background-color 0.3s ease';
  }
  
  const loadingElement = document.createElement('div');
  loadingElement.className = 'batch-operation-loader position-absolute top-0 start-0 w-100 h-100 d-flex justify-content-center align-items-center';
  loadingElement.style.backgroundColor = 'rgba(220,53,69,0.1)';
  loadingElement.style.zIndex = '100';
  loadingElement.innerHTML = `
    <div class="bg-white p-3 rounded shadow d-flex align-items-center">
      <div class="spinner-border text-danger me-2" role="status">
        <span class="visually-hidden">Verarbeite...</span>
      </div>
      <span>Lösche Batch und alle Jobs...</span>
    </div>
  `;
  
  if (batchCard) {
    batchCard.style.position = 'relative';
    batchCard.appendChild(loadingElement);
  }
  
  // Effizientere Lösung: Direkt den Batch löschen (dieser löscht auch alle Jobs)
  fetch(`/api/dashboard/event-monitor/batches/${batchId}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json'
    }
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`Fehler beim Löschen des Batches: ${response.statusText}`);
    }
    return response.json();
  })
  .then(data => {
    console.log(`Batch ${batchId} erfolgreich gelöscht:`, data);
    
    // Erfolgsmeldung anzeigen
    const toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white bg-danger border-0 position-fixed bottom-0 end-0 m-3';
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          Batch ${batchId} und alle zugehörigen Jobs wurden erfolgreich gelöscht.
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    document.body.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Kurze visuelle Reaktion: Batch-Karte ausblenden
    if (batchCard) {
      batchCard.style.transition = 'all 0.5s ease';
      batchCard.style.opacity = '0';
    }
    
    // Nach kurzer Verzögerung die Seite neu laden, um das Ergebnis anzuzeigen
    setTimeout(() => {
      window.location.reload();
    }, 2000); // 2 Sekunden Verzögerung, damit die Erfolgsmeldung noch gesehen werden kann
  })
  .catch(error => {
    console.error('Fehler beim Löschen des Batches:', error);
    
    // Entferne Lade-Animation und setze Anzeige zurück
    if (batchCard) {
      batchCard.style.backgroundColor = '';
      const loader = batchCard.querySelector('.batch-operation-loader');
      if (loader) {
        loader.remove();
      }
    }
    
    // Fehlermeldung anzeigen
    alert(`Fehler beim Löschen des Batches: ${error.message}`);
  });
};

window.archiveBatch = function(batchId) {
  if (confirm(`Sind Sie sicher, dass Sie den Batch ${batchId} archivieren möchten?`)) {
    console.log(`Batch ${batchId} archivieren`);
    
    // Erneute Bestätigung für kritische Aktion
    if (!confirm('Dieser Batch wird in der Hauptansicht nicht mehr angezeigt und erscheint stattdessen im Archiv. Fortfahren?')) {
      return;
    }
    
    // Lade-Animation anzeigen
    const batchCard = document.querySelector(`.card[data-batch-id="${batchId}"]`);
    if (batchCard) {
      batchCard.style.opacity = '0.7';
    }
    
    const loadingElement = document.createElement('div');
    loadingElement.className = 'batch-operation-loader position-absolute top-0 start-0 w-100 h-100 d-flex justify-content-center align-items-center';
    loadingElement.style.backgroundColor = 'rgba(0,0,0,0.1)';
    loadingElement.style.zIndex = '100';
    loadingElement.innerHTML = `
      <div class="bg-white p-3 rounded shadow d-flex align-items-center">
        <div class="spinner-border text-primary me-2" role="status">
          <span class="visually-hidden">Verarbeite...</span>
        </div>
        <span>Archiviere Batch...</span>
      </div>
    `;
    
    if (batchCard) {
      batchCard.style.position = 'relative';
      batchCard.appendChild(loadingElement);
    }
    
    // Batch archivieren
    fetch(`/api/dashboard/event-monitor/batches/${batchId}/archive`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        batch_id: batchId,
        archived: true
      })
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP Fehler: ${response.status} ${response.statusText}`);
      }
      return response.json();
    })
    .then(data => {
      console.log('Batch erfolgreich archiviert:', data);
      
      // Entferne Lade-Animation
      if (loadingElement) {
        loadingElement.remove();
      }
      
      // Nach kurzer Verzögerung die Card ausblenden und entfernen
      if (batchCard) {
        batchCard.style.transition = 'all 0.5s ease';
        batchCard.style.opacity = '0';
        batchCard.style.height = '0';
        batchCard.style.overflow = 'hidden';
        
        setTimeout(() => {
          batchCard.remove();
        }, 500);
      }
      
      // Erfolgsmeldung anzeigen
      const toast = document.createElement('div');
      toast.className = 'toast align-items-center text-white bg-success border-0 position-fixed bottom-0 end-0 m-3';
      toast.setAttribute('role', 'alert');
      toast.setAttribute('aria-live', 'assertive');
      toast.setAttribute('aria-atomic', 'true');
      toast.innerHTML = `
        <div class="d-flex">
          <div class="toast-body">
            Batch ${batchId} wurde erfolgreich archiviert.
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      `;
      document.body.appendChild(toast);
      
      const bsToast = new bootstrap.Toast(toast);
      bsToast.show();
    })
    .catch(error => {
      console.error('Fehler beim Archivieren des Batches:', error);
      
      // Entferne Lade-Animation
      if (loadingElement) {
        loadingElement.remove();
      }
      
      // Zustand der Batch-Card wiederherstellen
      if (batchCard) {
        batchCard.style.opacity = '1';
      }
      
      // Fehlermeldung anzeigen
      alert(`Fehler beim Archivieren des Batches: ${error.message}`);
    });
  }
}; 

// Funktion zum Laden des Archivs
function loadArchive() {
  DEBUG_LOG.load(`loadArchive aufgerufen`);
  
  const archiveContent = document.getElementById('archive-content');
  if (!archiveContent) {
    DEBUG_LOG.error(`Archiv-Content-Container nicht gefunden`);
    return;
  }
  
  // Lade-Animation anzeigen
  archiveContent.innerHTML = `
    <div class="d-flex justify-content-center py-4">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Laden...</span>
      </div>
    </div>
  `;
  
  // Performance-Logging starten
  const loadStart = performance.now();
  
  // API-Anfrage, um archivierte Batches zu laden
  DEBUG_LOG.api(`API-Anfrage für archivierte Batches wird gesendet`);
  fetch('/api/dashboard/event-monitor/batches?archived=true&limit=50')
    .then(response => {
      if (!response.ok) {
        DEBUG_LOG.error(`API-Fehler für archivierte Batches: ${response.status}`);
        throw new Error('Netzwerkantwort war nicht ok');
      }
      return response.json();
    })
    .then(data => {
      DEBUG_LOG.api(`API-Antwort für archivierte Batches erhalten`, { 
        status: data.status
      });
      
      // Performance-Logging für API-Antwort
      const apiTime = performance.now() - loadStart;
      logPerformance('archive_api_response', { time: apiTime });
      
      let batches = [];
      
      // Prüfe verschiedene mögliche Datenstrukturen
      if (data.data && data.data.batches) {
        DEBUG_LOG.info(`Batches gefunden in data.data.batches: ${data.data.batches.length} Batches`);
        batches = data.data.batches;
      } else if (data.batches) {
        DEBUG_LOG.info(`Batches gefunden in data.batches: ${data.batches.length} Batches`);
        batches = data.batches;
      } else {
        DEBUG_LOG.error(`Keine Batches in der Antwort gefunden!`, data);
      }
      
      const processStart = performance.now();
      
      if (batches && batches.length > 0) {
        DEBUG_LOG.info(`Verarbeite ${batches.length} archivierte Batches`);
        
        let html = '';
        
        batches.forEach((batch, index) => {
          html += `
            <div class="card batch-card" data-batch-id="${batch.batch_id}" data-index="archive-${index}">
              <div class="card-header">
                <div class="batch-info">
                  <strong>${batch.batch_name || batch.batch_id}</strong>
                  <span class="batch-meta">${formatDateTime(batch.created_at)}</span>
                </div>
                <div class="d-flex align-items-center gap-2">
                  <span class="status-badge ${getStatusBadgeClass(batch.status)}">
                    ${batch.status}
                  </span>
                  <span>${batch.total_jobs} Jobs (${batch.completed_jobs} abgeschlossen, ${batch.failed_jobs} fehlgeschlagen)</span>
                  <button class="btn btn-sm btn-outline-primary ms-2 load-jobs-btn" type="button" 
                          onclick="loadJobsForBatch('${batch.batch_id}', 'archive-${index}', false)">
                    <span id="jobs-toggle-text-archive-${index}">Jobs anzeigen</span>
                  </button>
                  <div class="dropdown d-inline-block ms-2">
                    <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" 
                            id="batchActionsDropdownArchive${index}" data-bs-toggle="dropdown" aria-expanded="false">
                      Batch-Aktionen
                    </button>
                    <ul class="dropdown-menu" aria-labelledby="batchActionsDropdownArchive${index}">
                      <li><a class="dropdown-item" href="#" onclick="restartBatch('${batch.batch_id}'); return false;">Batch neu starten</a></li>
                      <li><hr class="dropdown-divider"></li>
                      <li><a class="dropdown-item text-danger" href="#" onclick="deleteBatch('${batch.batch_id}'); return false;">Batch löschen</a></li>
                    </ul>
                  </div>
                  <div id="jobs-loading-archive-${index}" class="d-none">
                    <div class="d-flex align-items-center">
                      <div class="spinner-border spinner-border-sm text-primary me-2" role="status">
                        <span class="visually-hidden">Laden...</span>
                      </div>
                      <span>Laden...</span>
                    </div>
                  </div>
                </div>
              </div>
              <div class="card-body" id="card-body-archive-${index}">
                <div class="table-responsive d-none" id="table-container-archive-${index}" data-batch-id="${batch.batch_id}">
                  <table class="table table-hover job-table mb-0 batch-jobs-table">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Job-Name</th>
                        <th>Erstellt</th>
                        <th>Abgeschlossen</th>
                        <th>Fortschritt</th>
                        <th>Aktionen</th>
                      </tr>
                    </thead>
                    <tbody id="archive-jobs-container-${index}">
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          `;
        });
        
        archiveContent.innerHTML = html;
        
        // Performance-Logging für Rendering
        const renderTime = performance.now() - processStart;
        logPerformance('render_archive', { count: batches.length, time: renderTime });
        
        DEBUG_LOG.load(`Archivierte Batches erfolgreich geladen und gerendert`);
      } else {
        archiveContent.innerHTML = `
          <div class="alert alert-info">
            <i class="fas fa-info-circle me-2"></i> Keine archivierten Batches gefunden.
          </div>
        `;
        DEBUG_LOG.info(`Keine archivierten Batches gefunden`);
      }
    })
    .catch(error => {
      DEBUG_LOG.error(`Fehler beim Laden der archivierten Batches`, error);
      archiveContent.innerHTML = `
        <div class="alert alert-danger">
          <i class="fas fa-exclamation-circle me-2"></i> 
          Fehler beim Laden der archivierten Batches: ${error.message}
        </div>
      `;
    });
}

// Nach 60 Sekunden speicherbaren Bericht generieren
setTimeout(() => {
  DEBUG_LOG.info('Vollständiger Debug-Log-Bericht nach 60 Sekunden verfügbar');
  DEBUG_LOG.saveToConsole();
}, 60000); 