# Offline-Client Integration Guide

Anleitung fuer die Integration von Offline-Clients (hinter NAT/Firewall) mit dem Secretary Service.

## Ueberblick

Offline-Clients koennen keine Webhooks empfangen, weil sie aus dem Internet nicht erreichbar sind. Stattdessen gibt es zwei Alternativen:

1. **SSE (Server-Sent Events)** – Echtzeit-Updates ueber eine langlebige HTTP-Verbindung
2. **Polling** – Periodisches Abfragen des Job-Status

## Entscheidungsmatrix

| Szenario | Empfehlung |
|---|---|
| Client ist aus dem Internet erreichbar | Webhook (`callback_url`) |
| Client hinter Firewall, braucht Echtzeit-Updates | SSE (`/stream`) |
| Client hinter Firewall, einfachste Loesung | Polling (`GET /api/jobs/{id}`) |
| Sehr lange Jobs (> 5 Minuten) | Polling oder SSE mit Reconnect |

## SSE-Integration (Empfohlen)

### Ablauf

1. Job einreichen (ohne `callback_url`)
2. `job_id` aus der Response lesen
3. SSE-Stream oeffnen: `GET /api/jobs/{job_id}/stream`
4. Events verarbeiten bis `completed` oder `error`

### Python-Beispiel

```python
import requests
import json

BASE_URL = "https://commonsecretaryservices.bcommonslab.org/api"
API_KEY = "your-api-key"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def submit_job(job_type: str, parameters: dict) -> str:
    """Job einreichen und job_id zurueckgeben."""
    resp = requests.post(
        f"{BASE_URL}/jobs/",
        json={"job_type": job_type, "parameters": parameters},
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["data"]["job_id"]


def stream_job_updates(job_id: str) -> dict:
    """SSE-Stream oeffnen und auf Ergebnis warten.

    Gibt das finale Event-Payload zurueck (completed oder error).
    """
    url = f"{BASE_URL}/jobs/{job_id}/stream"

    # stream=True fuer langlebige Verbindung
    with requests.get(url, headers=HEADERS, stream=True) as resp:
        resp.raise_for_status()

        current_event = None
        current_data = None

        for line in resp.iter_lines(decode_unicode=True):
            if line is None:
                continue

            # SSE-Kommentare (z.B. Heartbeats) ignorieren
            if line.startswith(":"):
                continue

            # Event-Typ lesen
            if line.startswith("event: "):
                current_event = line[7:]
                continue

            # Daten lesen
            if line.startswith("data: "):
                current_data = json.loads(line[6:])

                print(f"[{current_event}] {current_data.get('message', '')}")

                # Bei Fortschritt: Prozent anzeigen
                if current_event == "progress":
                    progress = current_data.get("data", {}).get("progress", 0)
                    print(f"  Fortschritt: {progress}%")

                # Bei Abschluss: Ergebnis zurueckgeben
                if current_event in ("completed", "error", "timeout"):
                    return current_data

                continue

            # Leere Zeile = Event-Trenner (zuruecksetzen)
            if line == "":
                current_event = None
                current_data = None

    return {"phase": "error", "message": "Stream unerwartet geschlossen"}


# Beispiel: PDF verarbeiten
job_id = submit_job("pdf", {
    "filename": "/path/to/document.pdf",
    "extraction_method": "combined",
})
print(f"Job eingereicht: {job_id}")

result = stream_job_updates(job_id)
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
    """SSE-Stream mit automatischem Reconnect."""
    for attempt in range(MAX_RETRIES):
        try:
            result = stream_job_updates(job_id)
            return result

        except requests.exceptions.ConnectionError:
            print(f"Verbindung verloren (Versuch {attempt + 1}/{MAX_RETRIES})")

            # Pruefen ob Job bereits fertig ist
            status_resp = requests.get(
                f"{BASE_URL}/jobs/{job_id}",
                headers=HEADERS,
            )
            if status_resp.ok:
                job_data = status_resp.json().get("data", {})
                status = job_data.get("status")
                if status == "completed":
                    return {"phase": "completed", "data": {"results": job_data.get("results")}}
                if status == "failed":
                    return {"phase": "error", "error": job_data.get("error")}

            time.sleep(RETRY_DELAY_SEC)

    return {"phase": "error", "message": "Max Retries erreicht"}
```

### JavaScript-Beispiel (Browser / Node.js)

```javascript
const BASE_URL = "https://commonsecretaryservices.bcommonslab.org/api";
const API_KEY = "your-api-key";

// 1. Job einreichen
async function submitJob(jobType, parameters) {
  const resp = await fetch(`${BASE_URL}/jobs/`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ job_type: jobType, parameters }),
  });
  const data = await resp.json();
  return data.data.job_id;
}

// 2. SSE-Stream oeffnen
function streamJobUpdates(jobId, onProgress, onComplete, onError) {
  // EventSource unterstuetzt keine Auth-Header nativ,
  // daher fetch mit ReadableStream verwenden
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
      // Letzte (moeglicherweise unvollstaendige) Zeile behalten
      buffer = lines.pop() || "";

      let currentEvent = null;

      for (const line of lines) {
        if (line.startsWith(":")) continue;        // Heartbeat
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7);
          continue;
        }
        if (line.startsWith("data: ")) {
          const data = JSON.parse(line.slice(6));

          if (currentEvent === "progress") {
            onProgress(data);
          } else if (currentEvent === "completed") {
            onComplete(data);
            return;
          } else if (currentEvent === "error" || currentEvent === "timeout") {
            onError(data);
            return;
          }
        }
      }

      reader.read().then(processChunk);
    }

    reader.read().then(processChunk);
  });
}

// Verwendung
const jobId = await submitJob("pdf", { filename: "/path/to/file.pdf" });

streamJobUpdates(
  jobId,
  (data) => console.log(`Fortschritt: ${data.data?.progress}%`),
  (data) => console.log("Fertig:", data.data?.results),
  (data) => console.error("Fehler:", data.error || data.message)
);
```

### C# / .NET Beispiel

```csharp
using System.Net.Http;
using System.Text.Json;

var client = new HttpClient();
client.DefaultRequestHeaders.Add("Authorization", "Bearer your-api-key");

// Job einreichen
var content = new StringContent(
    JsonSerializer.Serialize(new { job_type = "pdf", parameters = new { filename = "/path/to/file.pdf" } }),
    System.Text.Encoding.UTF8,
    "application/json"
);
var resp = await client.PostAsync("https://commonsecretaryservices.bcommonslab.org/api/jobs/", content);
var json = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
var jobId = json.RootElement.GetProperty("data").GetProperty("job_id").GetString();

// SSE-Stream lesen
var stream = await client.GetStreamAsync($"https://commonsecretaryservices.bcommonslab.org/api/jobs/{jobId}/stream");
using var reader = new StreamReader(stream);

string? currentEvent = null;
while (!reader.EndOfStream)
{
    var line = await reader.ReadLineAsync();
    if (line == null) continue;
    if (line.StartsWith(":")) continue;  // Heartbeat

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
```

## Polling-Integration (Alternative)

### Ablauf

1. Job einreichen (ohne `callback_url`)
2. Periodisch `GET /api/jobs/{job_id}` abfragen
3. Auf `status == "completed"` oder `status == "failed"` pruefen

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
