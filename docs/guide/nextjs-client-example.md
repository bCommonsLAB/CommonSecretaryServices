# Next.js Client für Session-Verarbeitung

Clientseitiger Worker für Session-Verarbeitung mit Video-Download im Browser-Kontext.

## Übersicht

Der Client übernimmt:
- Video-Download (umgeht Server-TLS-Probleme)
- Parallele API-Aufrufe (Session ohne Video + Audio separat)
- Progress-Tracking und Fehlerbehandlung
- Zusammenführung der Ergebnisse

## TypeScript Types

Erstelle `types/secretary-api.ts`:

```typescript
// API Base Types
export interface APIResponse<T = any> {
  status: 'success' | 'error';
  request: {
    processor: string;
    timestamp: string;
    parameters: Record<string, any>;
  };
  process: {
    id: string;
    main_processor: string;
    started: string;
    completed?: string;
    duration?: number;
    sub_processors: string[];
    is_from_cache: boolean;
    cache_key?: string;
    llm_info?: {
      total_tokens: number;
      total_duration_ms: number;
      total_requests: number;
      total_cost: number;
    };
  };
  data?: T;
  error?: {
    code: string;
    message: string;
    details: Record<string, any>;
  };
}

// Session API Types
export interface SessionInput {
  event: string;
  session: string;
  url: string;
  filename: string;
  track: string;
  day?: string;
  starttime?: string;
  endtime?: string;
  speakers?: string[];
  video_url?: string;
  attachments_url?: string;
  source_language?: string;
  target_language?: string;
  target?: string;
  template?: string;
  use_cache?: boolean;
  create_archive?: boolean;
}

export interface SessionOutput {
  web_text: string;
  video_transcript: string;
  input_data: SessionInput;
  target_dir: string;
  markdown_file: string;
  markdown_content: string;
  video_file?: string;
  attachments_url?: string;
  attachments: string[];
  page_texts: string[];
  structured_data: Record<string, any>;
  archive_data?: string;  // base64
  archive_filename?: string;
  asset_dir?: string;
}

export interface SessionData {
  input: SessionInput;
  output: SessionOutput;
}

export type SessionResponse = APIResponse<SessionData>;

// Audio API Types
export interface AudioTranscription {
  text: string;
  source_language: string;
  segments?: Array<{
    start: number;
    end: number;
    text: string;
  }>;
}

export interface AudioData {
  transcription: AudioTranscription;
  metadata: {
    duration: number;
    file_size?: number;
  };
}

export type AudioResponse = APIResponse<AudioData>;

// Progress Tracking
export interface ProcessingProgress {
  step: 'init' | 'download_video' | 'process_session' | 'process_audio' | 'merge' | 'complete' | 'error';
  percent: number;
  message: string;
}
```

## API Client Hook

Erstelle `hooks/useSecretaryAPI.ts`:

```typescript
import { useState, useCallback } from 'react';
import { 
  SessionInput, 
  SessionResponse, 
  AudioResponse, 
  ProcessingProgress 
} from '@/types/secretary-api';

interface UseSecretaryAPIConfig {
  apiBaseUrl: string;
  apiToken: string;
}

export function useSecretaryAPI(config: UseSecretaryAPIConfig) {
  const [progress, setProgress] = useState<ProcessingProgress>({
    step: 'init',
    percent: 0,
    message: 'Bereit'
  });
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const updateProgress = useCallback((update: Partial<ProcessingProgress>) => {
    setProgress(prev => ({ ...prev, ...update }));
  }, []);

  /**
   * Lädt Video herunter und konvertiert zu Blob
   */
  const downloadVideo = useCallback(async (videoUrl: string): Promise<Blob | null> => {
    try {
      updateProgress({ 
        step: 'download_video', 
        percent: 10, 
        message: 'Lade Video herunter...' 
      });

      // CORS-Proxy verwenden oder direkt laden (abhängig von Vimeo-Einstellungen)
      const response = await fetch(videoUrl, {
        method: 'GET',
        mode: 'cors',
      });

      if (!response.ok) {
        throw new Error(`Video-Download fehlgeschlagen: ${response.status}`);
      }

      const blob = await response.blob();
      updateProgress({ percent: 20, message: 'Video heruntergeladen' });
      
      return blob;
    } catch (err) {
      console.error('Video-Download Fehler:', err);
      // Video-Fehler nicht fatal - Session kann ohne Video weiterlaufen
      return null;
    }
  }, [updateProgress]);

  /**
   * Verarbeitet Session (ohne Video)
   */
  const processSession = useCallback(async (
    input: SessionInput
  ): Promise<SessionResponse | null> => {
    try {
      updateProgress({ 
        step: 'process_session', 
        percent: 30, 
        message: 'Verarbeite Session-Daten...' 
      });

      // Entferne video_url für diesen Aufruf
      const { video_url, ...inputWithoutVideo } = input;

      const response = await fetch(`${config.apiBaseUrl}/api/session/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.apiToken}`,
        },
        body: JSON.stringify(inputWithoutVideo),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error?.message || 'Session-Verarbeitung fehlgeschlagen');
      }

      const data: SessionResponse = await response.json();
      updateProgress({ percent: 60, message: 'Session verarbeitet' });
      
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unbekannter Fehler';
      setError(`Session-Fehler: ${message}`);
      throw err;
    }
  }, [config, updateProgress]);

  /**
   * Verarbeitet Audio-Datei
   */
  const processAudio = useCallback(async (
    audioBlob: Blob,
    sourceLanguage: string = 'en',
    targetLanguage: string = 'de'
  ): Promise<AudioResponse | null> => {
    try {
      updateProgress({ 
        step: 'process_audio', 
        percent: 40, 
        message: 'Transkribiere Audio...' 
      });

      const formData = new FormData();
      formData.append('file', audioBlob, 'video-audio.mp3');
      formData.append('source_language', sourceLanguage);
      formData.append('target_language', targetLanguage);

      const response = await fetch(`${config.apiBaseUrl}/api/audio/process`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${config.apiToken}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error?.message || 'Audio-Verarbeitung fehlgeschlagen');
      }

      const data: AudioResponse = await response.json();
      updateProgress({ percent: 80, message: 'Audio transkribiert' });
      
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unbekannter Fehler';
      console.error('Audio-Fehler:', message);
      // Audio-Fehler nicht fatal
      return null;
    }
  }, [config, updateProgress]);

  /**
   * Extrahiert Audio aus Video-Blob (via Browser Web Audio API)
   */
  const extractAudioFromVideo = useCallback(async (
    videoBlob: Blob
  ): Promise<Blob | null> => {
    try {
      // Für Browser: Nutze FFmpeg.wasm oder sende direkt als Video
      // Einfachste Lösung: Server kann auch Video akzeptieren
      // Alternativ: https://github.com/ffmpegwasm/ffmpeg.wasm
      
      // Vorerst: Sende Video-Blob direkt (Server extrahiert Audio)
      return videoBlob;
    } catch (err) {
      console.error('Audio-Extraktion fehlgeschlagen:', err);
      return null;
    }
  }, []);

  /**
   * Hauptfunktion: Verarbeitet komplette Session mit Video
   */
  const processSessionWithVideo = useCallback(async (
    input: SessionInput
  ): Promise<{
    session: SessionResponse | null;
    audio: AudioResponse | null;
    combined: SessionOutput | null;
  }> => {
    setIsProcessing(true);
    setError(null);
    
    try {
      updateProgress({ 
        step: 'init', 
        percent: 0, 
        message: 'Starte Verarbeitung...' 
      });

      // Parallel: Session (ohne Video) + Video-Download
      const [sessionResult, videoBlob] = await Promise.all([
        processSession(input),
        input.video_url ? downloadVideo(input.video_url) : Promise.resolve(null)
      ]);

      let audioResult: AudioResponse | null = null;

      // Wenn Video verfügbar: Audio extrahieren und transkribieren
      if (videoBlob) {
        const audioBlob = await extractAudioFromVideo(videoBlob);
        if (audioBlob) {
          audioResult = await processAudio(
            audioBlob,
            input.source_language || 'en',
            input.target_language || 'de'
          );
        }
      }

      // Ergebnisse zusammenführen
      let combined: SessionOutput | null = null;
      if (sessionResult?.data?.output) {
        combined = {
          ...sessionResult.data.output,
          video_transcript: audioResult?.data?.transcription.text || '',
        };
      }

      updateProgress({ 
        step: 'complete', 
        percent: 100, 
        message: 'Verarbeitung abgeschlossen' 
      });

      setIsProcessing(false);
      return { session: sessionResult, audio: audioResult, combined };

    } catch (err) {
      const message = err instanceof Error ? err.message : 'Verarbeitung fehlgeschlagen';
      setError(message);
      updateProgress({ 
        step: 'error', 
        percent: 0, 
        message 
      });
      setIsProcessing(false);
      throw err;
    }
  }, [processSession, downloadVideo, extractAudioFromVideo, processAudio, updateProgress]);

  /**
   * Lädt ZIP-Archiv herunter (wenn create_archive=true)
   */
  const downloadArchive = useCallback(async (
    archiveData: string,
    filename: string
  ): Promise<void> => {
    try {
      // Base64 dekodieren
      const binaryString = atob(archiveData);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      
      // Blob erstellen und Download triggern
      const blob = new Blob([bytes], { type: 'application/zip' });
      const url = URL.createObjectURL(blob);
      
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Archiv-Download fehlgeschlagen:', err);
      throw err;
    }
  }, []);

  return {
    processSessionWithVideo,
    downloadArchive,
    progress,
    error,
    isProcessing,
  };
}
```

## React Component Beispiel

Erstelle `components/SessionProcessor.tsx`:

```typescript
'use client';

import { useState } from 'react';
import { useSecretaryAPI } from '@/hooks/useSecretaryAPI';
import { SessionInput } from '@/types/secretary-api';

export function SessionProcessor() {
  const [sessionData, setSessionData] = useState<SessionInput>({
    event: 'FOSDEM 2025',
    session: 'Keynote',
    url: 'https://example.org/session/keynote',
    filename: 'keynote.md',
    track: 'ecosocial',
    video_url: 'https://player.vimeo.com/video/1029681888',
    attachments_url: 'https://example.org/slides.pdf',
    source_language: 'en',
    target_language: 'de',
    template: 'Session',
    create_archive: true,
  });

  const {
    processSessionWithVideo,
    downloadArchive,
    progress,
    error,
    isProcessing,
  } = useSecretaryAPI({
    apiBaseUrl: process.env.NEXT_PUBLIC_SECRETARY_API_URL || 'http://localhost:5001',
    apiToken: process.env.NEXT_PUBLIC_SECRETARY_API_TOKEN || '',
  });

  const [result, setResult] = useState<any>(null);

  const handleProcess = async () => {
    try {
      const { session, audio, combined } = await processSessionWithVideo(sessionData);
      
      setResult({
        markdown: combined?.markdown_content,
        webText: combined?.web_text,
        transcript: combined?.video_transcript,
        attachments: combined?.attachments,
        archiveData: combined?.archive_data,
        archiveFilename: combined?.archive_filename,
      });

      // Auto-Download ZIP wenn verfügbar
      if (combined?.archive_data && combined?.archive_filename) {
        await downloadArchive(combined.archive_data, combined.archive_filename);
      }
    } catch (err) {
      console.error('Verarbeitung fehlgeschlagen:', err);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Session Processor</h1>

      {/* Input Form */}
      <div className="space-y-4 mb-6">
        <div>
          <label className="block text-sm font-medium mb-1">Event *</label>
          <input
            type="text"
            value={sessionData.event}
            onChange={(e) => setSessionData({ ...sessionData, event: e.target.value })}
            className="w-full px-3 py-2 border rounded"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Session *</label>
          <input
            type="text"
            value={sessionData.session}
            onChange={(e) => setSessionData({ ...sessionData, session: e.target.value })}
            className="w-full px-3 py-2 border rounded"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">URL *</label>
          <input
            type="url"
            value={sessionData.url}
            onChange={(e) => setSessionData({ ...sessionData, url: e.target.value })}
            className="w-full px-3 py-2 border rounded"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Video URL</label>
          <input
            type="url"
            value={sessionData.video_url || ''}
            onChange={(e) => setSessionData({ ...sessionData, video_url: e.target.value })}
            className="w-full px-3 py-2 border rounded"
            placeholder="https://player.vimeo.com/video/..."
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Track *</label>
          <input
            type="text"
            value={sessionData.track}
            onChange={(e) => setSessionData({ ...sessionData, track: e.target.value })}
            className="w-full px-3 py-2 border rounded"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Dateiname *</label>
          <input
            type="text"
            value={sessionData.filename}
            onChange={(e) => setSessionData({ ...sessionData, filename: e.target.value })}
            className="w-full px-3 py-2 border rounded"
            placeholder="keynote.md"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Quellsprache</label>
            <select
              value={sessionData.source_language}
              onChange={(e) => setSessionData({ ...sessionData, source_language: e.target.value })}
              className="w-full px-3 py-2 border rounded"
            >
              <option value="en">Englisch</option>
              <option value="de">Deutsch</option>
              <option value="fr">Französisch</option>
              <option value="it">Italienisch</option>
              <option value="es">Spanisch</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Zielsprache</label>
            <select
              value={sessionData.target_language}
              onChange={(e) => setSessionData({ ...sessionData, target_language: e.target.value })}
              className="w-full px-3 py-2 border rounded"
            >
              <option value="de">Deutsch</option>
              <option value="en">Englisch</option>
              <option value="fr">Französisch</option>
              <option value="it">Italienisch</option>
              <option value="es">Spanisch</option>
            </select>
          </div>
        </div>

        <div className="flex items-center">
          <input
            type="checkbox"
            checked={sessionData.create_archive}
            onChange={(e) => setSessionData({ ...sessionData, create_archive: e.target.checked })}
            className="mr-2"
          />
          <label className="text-sm">ZIP-Archiv erstellen</label>
        </div>
      </div>

      {/* Progress Bar */}
      {isProcessing && (
        <div className="mb-6">
          <div className="flex justify-between text-sm mb-1">
            <span>{progress.message}</span>
            <span>{progress.percent}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${progress.percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded text-red-700">
          {error}
        </div>
      )}

      {/* Action Button */}
      <button
        onClick={handleProcess}
        disabled={isProcessing}
        className="w-full px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
      >
        {isProcessing ? 'Verarbeite...' : 'Session verarbeiten'}
      </button>

      {/* Results Display */}
      {result && (
        <div className="mt-8 space-y-4">
          <h2 className="text-xl font-bold">Ergebnis</h2>

          {result.markdown && (
            <div>
              <h3 className="font-medium mb-2">Generiertes Markdown</h3>
              <pre className="bg-gray-50 p-4 rounded text-sm overflow-auto max-h-96">
                {result.markdown}
              </pre>
            </div>
          )}

          {result.transcript && (
            <div>
              <h3 className="font-medium mb-2">Video-Transkript</h3>
              <div className="bg-gray-50 p-4 rounded text-sm max-h-64 overflow-auto">
                {result.transcript}
              </div>
            </div>
          )}

          {result.attachments && result.attachments.length > 0 && (
            <div>
              <h3 className="font-medium mb-2">Anhänge ({result.attachments.length})</h3>
              <ul className="list-disc list-inside">
                {result.attachments.map((att: string, idx: number) => (
                  <li key={idx} className="text-sm">{att}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

## Environment Variables

Erstelle `.env.local`:

```bash
NEXT_PUBLIC_SECRETARY_API_URL=http://localhost:5001
NEXT_PUBLIC_SECRETARY_API_TOKEN=dein_api_token_hier
```

## Batch-Verarbeitung

Für mehrere Sessions erstelle `hooks/useSessionBatch.ts`:

```typescript
import { useState, useCallback } from 'react';
import { useSecretaryAPI } from './useSecretaryAPI';
import { SessionInput } from '@/types/secretary-api';

interface BatchJob {
  id: string;
  input: SessionInput;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  result?: any;
  error?: string;
  progress: number;
}

export function useSessionBatch(config: { apiBaseUrl: string; apiToken: string }) {
  const [jobs, setJobs] = useState<BatchJob[]>([]);
  const [currentJobIndex, setCurrentJobIndex] = useState<number>(-1);
  const { processSessionWithVideo } = useSecretaryAPI(config);

  const addJobs = useCallback((inputs: SessionInput[]) => {
    const newJobs: BatchJob[] = inputs.map((input, idx) => ({
      id: `job-${Date.now()}-${idx}`,
      input,
      status: 'pending',
      progress: 0,
    }));
    setJobs(prev => [...prev, ...newJobs]);
  }, []);

  const processBatch = useCallback(async () => {
    for (let i = 0; i < jobs.length; i++) {
      const job = jobs[i];
      if (job.status !== 'pending') continue;

      setCurrentJobIndex(i);
      setJobs(prev => prev.map((j, idx) => 
        idx === i ? { ...j, status: 'processing' as const, progress: 0 } : j
      ));

      try {
        const result = await processSessionWithVideo(job.input);
        
        setJobs(prev => prev.map((j, idx) => 
          idx === i ? { 
            ...j, 
            status: 'completed' as const, 
            result, 
            progress: 100 
          } : j
        ));
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Fehler';
        setJobs(prev => prev.map((j, idx) => 
          idx === i ? { 
            ...j, 
            status: 'failed' as const, 
            error: message,
            progress: 0
          } : j
        ));
      }
    }
    setCurrentJobIndex(-1);
  }, [jobs, processSessionWithVideo]);

  const clearJobs = useCallback(() => {
    setJobs([]);
    setCurrentJobIndex(-1);
  }, []);

  return {
    jobs,
    addJobs,
    processBatch,
    clearJobs,
    currentJobIndex,
    isProcessing: currentJobIndex >= 0,
  };
}
```

## Verwendung in Page

Erstelle `app/sessions/page.tsx`:

```typescript
'use client';

import { SessionProcessor } from '@/components/SessionProcessor';

export default function SessionsPage() {
  return (
    <main className="container mx-auto py-8">
      <SessionProcessor />
    </main>
  );
}
```

## Installation

```bash
npm install
# Keine zusätzlichen Dependencies nötig - nutzt nur fetch API
```

## Wichtige Hinweise

1. **Video-Download CORS:**
   - Vimeo-Player-URLs haben oft CORS-Restrictions
   - Lösung: Nutze Vimeo-Embed-API oder Proxy
   - Alternative: `<video>` Element + MediaRecorder API für Audio-Extraktion

2. **Große Dateien:**
   - Browser-Download kann bei großen Videos langsam sein
   - Zeige Progress mit `fetch` + `ReadableStream`

3. **Audio-Extraktion im Browser:**
   - Einfachste Lösung: Sende Video-Blob an `/api/audio/process`
   - Fortgeschritten: FFmpeg.wasm für clientseitige Konvertierung

4. **Fehlerbehandlung:**
   - Session läuft auch ohne Video weiter
   - Zeige Warnung, wenn Video scheitert

5. **Authentifizierung:**
   - Token nie im Frontend hardcoden
   - Nutze `.env.local` und `NEXT_PUBLIC_*` Prefix

## Production-Optimierungen

- Server-Side Rendering für initiale Daten
- React Query für Caching
- WebWorker für Video-Processing
- Zustandsverwaltung mit Zustand/Redux

Das sollte alle Anforderungen für deinen Next.js Client abdecken!

