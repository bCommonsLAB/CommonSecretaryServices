# Offline-Client Integration Guide

Anleitung fuer die Integration von Offline-Clients (hinter NAT/Firewall) mit dem Secretary Service.

## Ueberblick

Offline-Clients koennen keine Webhooks empfangen, weil sie aus dem Internet nicht erreichbar sind. Die Loesung: Die gleichen Endpoints nutzen, aber **ohne `callback_url`**. Je nach Endpoint-Typ wird das Ergebnis entweder synchron oder via SSE/Polling abgeholt.

## Verhalten der Endpoints ohne `callback_url`

Die Endpoints verhalten sich unterschiedlich, wenn kein `callback_url` gesetzt ist:

### Synchrone Endpoints (Ergebnis direkt in der Response)

Diese Endpoints verarbeiten die Datei inline und geben das Ergebnis direkt zurueck:

| Endpoint | Response | Wartezeit |
|---|---|---|
| `POST /api/audio/process` | 200 + Ergebnis | Abhaengig von Dateigroesse (Sekunden bis wenige Minuten) |
| `POST /api/video/process` | 200 + Ergebnis | Abhaengig von Dateigroesse |
| `POST /api/video/youtube` | 200 + Ergebnis | Abhaengig von Videolaenge |
| `POST /api/transformer/template` | 200 + Ergebnis | Meist wenige Sekunden |

**Fuer Offline-Clients genuegt es, einfach `callback_url` wegzulassen.** Der Client wartet auf die synchrone Antwort.

### Asynchrone Endpoints (Job-Queue, `job_id` zurueck)

Diese Endpoints nutzen immer die Job-Queue, auch ohne `callback_url`:

| Endpoint | Response | Ergebnis abholen |
|---|---|---|
| `POST /api/pdf/process` | 202 + `job_id` | SSE-Stream oder Polling |
| `POST /api/pdf/process-mistral-ocr` | 202 + `job_id` | SSE-Stream oder Polling |
| `POST /api/pdf/process-url` | 202 + `job_id` | SSE-Stream oder Polling |
| `POST /api/office/process` | 202 + `job_id` | SSE-Stream oder Polling |
| `POST /api/office/process-via-pdf` | 202 + `job_id` | SSE-Stream oder Polling |

**Hinweis**: PDF und Office unterstuetzen optional `wait_ms` – der Server wartet bis zu `wait_ms` Millisekunden auf das Ergebnis und gibt es direkt zurueck, wenn der Job in der Zeit fertig wird.

## Entscheidungsmatrix

| Szenario | Empfehlung |
|---|---|
| Audio/Video/Transformer (Offline) | Synchron: `callback_url` weglassen, auf Response warten |
| PDF/Office (Offline, Echtzeit) | SSE: `job_id` aus 202-Response, dann `/stream` oeffnen |
| PDF/Office (Offline, einfach) | Polling: `job_id` aus 202-Response, dann `GET /api/jobs/{id}` |
| PDF/Office (Offline, kurze Jobs) | `wait_ms`: z.B. `wait_ms=30000` fuer bis zu 30s Wartezeit |
| Alle Endpoints (Online) | Webhook: `callback_url` setzen (bisheriger Weg) |

## Workflow: Synchrone Endpoints (Audio, Video, Transformer)

Kein SSE noetig. Einfach `callback_url` weglassen:

```python
import requests

BASE_URL = "https://commonsecretaryservices.bcommonslab.org/api"
API_KEY = "your-api-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def process_audio_sync(file_path: str, source_language: str = "de") -> dict:
    """Audio-Datei synchron verarbeiten. Ergebnis direkt in der Response."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/audio/process",
            files={"file": f},
            data={"source_language": source_language},
            headers=HEADERS,
            # KEIN callback_url -> synchrone Verarbeitung
        )
    resp.raise_for_status()
    return resp.json()


def process_video_sync(file_path: str) -> dict:
    """Video-Datei synchron verarbeiten."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/video/process",
            files={"file": f},
            data={"source_language": "de"},
            headers=HEADERS,
        )
    resp.raise_for_status()
    return resp.json()


# Verwendung
result = process_audio_sync("/path/to/recording.mp3")
print(result["data"]["transcription"]["text"])
```

```csharp
// C# - Audio synchron verarbeiten
using var form = new MultipartFormDataContent();
form.Add(new StreamContent(File.OpenRead("recording.mp3")), "file", "recording.mp3");
form.Add(new StringContent("de"), "source_language");

var resp = await client.PostAsync($"{BASE_URL}/audio/process", form);
var result = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
```

## Workflow: Asynchrone Endpoints (PDF, Office) mit SSE

### Ablauf

1. Datei an den direkten Endpoint senden (ohne `callback_url`)
2. `job_id` aus der 202-Response lesen (Feld `job.id`)
3. SSE-Stream oeffnen: `GET /api/jobs/{job_id}/stream`
4. Events verarbeiten bis `completed` oder `error`

### Python-Beispiel: PDF mit SSE

```python
import requests
import json

BASE_URL = "https://commonsecretaryservices.bcommonslab.org/api"
API_KEY = "your-api-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def process_pdf_with_sse(file_path: str) -> dict:
    """PDF verarbeiten und Ergebnis via SSE empfangen."""

    # 1. Datei hochladen (ohne callback_url)
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/pdf/process",
            files={"file": f},
            data={"extraction_method": "combined"},
            headers=HEADERS,
        )
    resp.raise_for_status()
    data = resp.json()

    # Synchrones Ergebnis? (bei wait_ms oder kleinen Dateien moeglich)
    if resp.status_code == 200:
        return data

    # 2. job_id aus 202-Response extrahieren
    job_id = data.get("job", {}).get("id")
    if not job_id:
        raise ValueError(f"Keine job_id in Response: {data}")

    print(f"Job eingereicht: {job_id}")

    # 3. SSE-Stream oeffnen
    return stream_job_updates(job_id)


def stream_job_updates(job_id: str) -> dict:
    """SSE-Stream oeffnen und auf Ergebnis warten."""
    url = f"{BASE_URL}/jobs/{job_id}/stream"

    with requests.get(url, headers=HEADERS, stream=True) as resp:
        resp.raise_for_status()

        current_event = None

        for line in resp.iter_lines(decode_unicode=True):
            if line is None:
                continue

            # SSE-Kommentare (Heartbeats) ignorieren
            if line.startswith(":"):
                continue

            if line.startswith("event: "):
                current_event = line[7:]
                continue

            if line.startswith("data: "):
                current_data = json.loads(line[6:])
                print(f"[{current_event}] {current_data.get('message', '')}")

                if current_event == "progress":
                    progress = current_data.get("data", {}).get("progress", 0)
                    print(f"  Fortschritt: {progress}%")

                if current_event in ("completed", "error", "timeout"):
                    return current_data

    return {"phase": "error", "message": "Stream unerwartet geschlossen"}


# Verwendung
result = process_pdf_with_sse("/path/to/document.pdf")
if result["phase"] == "completed":
    print("Ergebnis:", json.dumps(result["data"], indent=2))
else:
    print("Fehler:", result.get("error", result.get("message")))
```

### Python-Beispiel mit Reconnect

Fuer sehr lange Jobs oder instabile Verbindungen:

```python
import time

MAX_RETRIES = 3
RETRY_DELAY_SEC = 5


def stream_with_reconnect(job_id: str) -> dict:
    """SSE-Stream mit automatischem Reconnect.

    Bei Verbindungsabbruch wird geprueft, ob der Job bereits fertig ist.
    Falls ja, wird der SSE-Stream neu geoeffnet (liefert sofort das
    completed-Event im Webhook-kompatiblen Format).
    Falls nein, wird der Stream ebenfalls neu geoeffnet.
    """
    for attempt in range(MAX_RETRIES):
        try:
            result = stream_job_updates(job_id)
            return result

        except requests.exceptions.ConnectionError:
            print(f"Verbindung verloren (Versuch {attempt + 1}/{MAX_RETRIES})")

            # Kurz warten, dann SSE-Stream erneut oeffnen.
            # Der Stream liefert den aktuellen Status sofort als erstes Event
            # (auch wenn der Job bereits completed ist).
            time.sleep(RETRY_DELAY_SEC)

    return {"phase": "error", "message": "Max Retries erreicht"}
```

### Alternative: PDF mit `wait_ms` (ohne SSE)

Fuer kurze PDFs kann der Client einfach warten:

```python
def process_pdf_wait(file_path: str, wait_ms: int = 30000) -> dict:
    """PDF verarbeiten und bis zu wait_ms auf das Ergebnis warten."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/pdf/process",
            files={"file": f},
            data={
                "extraction_method": "combined",
                "wait_ms": str(wait_ms),  # Server wartet bis zu 30s
            },
            headers=HEADERS,
        )
    resp.raise_for_status()
    data = resp.json()

    if resp.status_code == 200:
        return data  # Ergebnis direkt

    # Timeout: Job laeuft noch, manuell pollen oder SSE nutzen
    job_id = data.get("job", {}).get("id")
    print(f"Job {job_id} laeuft noch, wechsle zu Polling...")
    return poll_job(job_id)
```

### JavaScript-Beispiel (Browser / Node.js)

```javascript
const BASE_URL = "https://commonsecretaryservices.bcommonslab.org/api";
const API_KEY = "your-api-key";

// PDF hochladen und job_id erhalten
async function submitPdf(file) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("extraction_method", "combined");
  // KEIN callback_url

  const resp = await fetch(`${BASE_URL}/pdf/process`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${API_KEY}` },
    body: formData,
  });

  const data = await resp.json();

  // Synchrones Ergebnis?
  if (resp.status === 200) return { result: data, jobId: null };

  return { result: null, jobId: data.job?.id };
}

// SSE-Stream oeffnen (fuer 202-Responses)
function streamJobUpdates(jobId, onProgress, onComplete, onError) {
  fetch(`${BASE_URL}/jobs/${jobId}/stream`, {
    headers: { "Authorization": `Bearer ${API_KEY}` },
  }).then((response) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    function processChunk({ done, value }) {
      if (done) return;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      let currentEvent = null;

      for (const line of lines) {
        if (line.startsWith(":")) continue;
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7);
          continue;
        }
        if (line.startsWith("data: ")) {
          const data = JSON.parse(line.slice(6));

          if (currentEvent === "progress") onProgress(data);
          else if (currentEvent === "completed") { onComplete(data); return; }
          else if (currentEvent === "error" || currentEvent === "timeout") { onError(data); return; }
        }
      }

      reader.read().then(processChunk);
    }

    reader.read().then(processChunk);
  });
}

// Verwendung
const { result, jobId } = await submitPdf(fileInput.files[0]);
if (result) {
  console.log("Ergebnis (synchron):", result);
} else {
  streamJobUpdates(
    jobId,
    (data) => console.log(`Fortschritt: ${data.data?.progress}%`),
    (data) => console.log("Fertig:", data.data?.extracted_text || data.data),
    (data) => console.error("Fehler:", data.error || data.message)
  );
}
```

### C# / .NET Beispiel

```csharp
using System.Net.Http;
using System.Text.Json;

var client = new HttpClient();
client.DefaultRequestHeaders.Add("Authorization", "Bearer your-api-key");

// 1. PDF hochladen
using var form = new MultipartFormDataContent();
form.Add(new StreamContent(File.OpenRead("/path/to/file.pdf")), "file", "file.pdf");
form.Add(new StringContent("combined"), "extraction_method");

var resp = await client.PostAsync($"{BASE_URL}/pdf/process", form);
var json = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());

if (resp.StatusCode == System.Net.HttpStatusCode.OK)
{
    Console.WriteLine("Ergebnis (synchron): " + json.RootElement);
}
else
{
    // 2. job_id aus 202-Response
    var jobId = json.RootElement.GetProperty("job").GetProperty("id").GetString();

    // 3. SSE-Stream lesen
    var stream = await client.GetStreamAsync($"{BASE_URL}/jobs/{jobId}/stream");
    using var reader = new StreamReader(stream);

    string? currentEvent = null;
    while (!reader.EndOfStream)
    {
        var line = await reader.ReadLineAsync();
        if (line == null) continue;
        if (line.StartsWith(":")) continue;

        if (line.StartsWith("event: "))
        {
            currentEvent = line[7..];
            continue;
        }

        if (line.StartsWith("data: "))
        {
            var data = JsonDocument.Parse(line[6..]);
            Console.WriteLine($"[{currentEvent}] {data.RootElement.GetProperty("message")}");

            if (currentEvent is "completed" or "error")
                break;
        }
    }
}
```

## Polling-Integration (Alternative fuer PDF/Office)

### Ablauf

1. Datei an den direkten Endpoint senden (ohne `callback_url`)
2. `job_id` aus der 202-Response lesen
3. Periodisch `GET /api/jobs/{job_id}` abfragen
4. Auf `status == "completed"` oder `status == "failed"` pruefen

### Python-Beispiel

```python
import requests
import time

BASE_URL = "https://commonsecretaryservices.bcommonslab.org/api"
API_KEY = "your-api-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def poll_job(job_id: str, interval_sec: float = 5.0, max_wait_sec: float = 600) -> dict:
    """Pollt den Job-Status bis er abgeschlossen ist."""
    start = time.monotonic()

    while time.monotonic() - start < max_wait_sec:
        resp = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()["data"]

        status = data["status"]
        print(f"Status: {status}")

        if status == "completed":
            return data
        if status == "failed":
            raise RuntimeError(f"Job fehlgeschlagen: {data.get('error', {}).get('message')}")

        time.sleep(interval_sec)

    raise TimeoutError(f"Job {job_id} nicht innerhalb von {max_wait_sec}s abgeschlossen")
```

## Zusammenfassung: Online vs. Offline Workflow

### Online-Client (bisheriger Weg)

```
Client --> POST /api/pdf/process (file + callback_url) --> 202 + job_id
                                                           ...
Server --> POST callback_url (Webhook mit Ergebnis)    <-- Client empfaengt
```

### Offline-Client: Synchrone Endpoints

```
Client --> POST /api/audio/process (file, KEIN callback_url) --> 200 + Ergebnis
```

### Offline-Client: Asynchrone Endpoints (PDF/Office)

```
Client --> POST /api/pdf/process (file, KEIN callback_url) --> 202 + job_id
Client --> GET /api/jobs/{job_id}/stream                   --> SSE-Events
           event: progress (30%)
           event: progress (70%)
           event: completed + Ergebnis
```

## Authentifizierung

Alle Requests (inklusive SSE-Stream) benoetigen den API-Key:

```
Authorization: Bearer YOUR_API_KEY
```

oder alternativ:

```
X-Secretary-Api-Key: YOUR_API_KEY
```

## Fehlerbehebung

### SSE-Stream schliesst sofort

- Pruefen: Ist die `job_id` korrekt? `GET /api/jobs/{job_id}` testen.
- Pruefen: Ist der API-Key gueltig?

### Keine Events nach langer Wartezeit

- Heartbeats (`": heartbeat"`) sollten alle 15 Sekunden ankommen.
- Falls nicht: Proxy oder Firewall blockiert moeglicherweise die Verbindung.
- Loesung: Auf Polling umsteigen.

### Stream-Timeout nach 300s

- Der Stream schliesst nach 5 Minuten automatisch.
- Fuer laengere Jobs: Stream neu oeffnen (der aktuelle Status wird sofort gesendet) oder auf Polling umsteigen.

### Proxy-Timeout (60-120s)

- Manche Corporate-Proxies schliessen langlebige Verbindungen.
- Die Heartbeats (alle 15s) verhindern dies in den meisten Faellen.
- Falls es trotzdem passiert: Reconnect-Logik implementieren (siehe Python-Beispiel oben).
