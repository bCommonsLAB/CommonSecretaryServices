// event-monitor.js

// Batches abrufen
async function fetchBatches(status = null, limit = 100, skip = 0) {
  let url = `/api/event-job/batches?limit=${limit}&skip=${skip}`;
  if (status) url += `&status=${status}`;

  const response = await fetch(url);
  const data = await response.json();
  return data.batches;
}

// Jobs eines bestimmten Batches abrufen
async function fetchJobsForBatch(batchId) {
  const url = `/api/event-job/jobs?batch_id=${batchId}`;
  const response = await fetch(url);
  const data = await response.json();
  return data.jobs;
}

// Batch löschen Funktion
function deleteBatch(batchId) {
  // Eine klarere und aussagekräftige Warnung anzeigen
  if (!confirm(`⚠️ WARNUNG ⚠️\n\nMöchten Sie wirklich ALLE JOBS in Batch ${batchId} UNWIDERRUFLICH LÖSCHEN?\nDiese Aktion kann NICHT rückgängig gemacht werden und löscht alle Daten permanent!`)) {
    return;
  }
  
  // Lade-Animation anzeigen
  const batchCard = document.querySelector(`.card:has([data-batch-id="${batchId}"])`);
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
}

// Exportiere Funktionen für externe Nutzung
// Sorge dafür, dass deleteBatch global verfügbar ist
window.deleteBatch = deleteBatch;

// Weitere Exporte für Module
export { fetchBatches, fetchJobsForBatch, deleteBatch }; 