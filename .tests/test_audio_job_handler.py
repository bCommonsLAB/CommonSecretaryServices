from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest


@dataclass
class _FakeProgress:
    step: str
    percent: int
    message: str | None = None


@dataclass
class _FakeResults:
    structured_data: Dict[str, Any] | None = None
    markdown_content: str | None = None


class _FakeRepo:
    def __init__(self) -> None:
        self.status_updates: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []

    def update_job_status(self, *, job_id: str, status: str, progress: Any = None, results: Any = None, error: Any = None) -> bool:
        self.status_updates.append(
            {
                "job_id": job_id,
                "status": status,
                "progress": progress,
                "results": results,
                "error": error,
            }
        )
        return True

    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        self.logs.append({"job_id": job_id, "level": level, "message": message})
        return True


class _FakeAudioProcessor:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def process(self, **_kwargs: Any) -> Any:
        # Minimal kompatible Struktur: result.to_dict() muss Dict liefern
        class _Res:
            status = "success"

            def to_dict(self) -> Dict[str, Any]:
                return {
                    "status": "success",
                    "data": {
                        "transcription": {"text": "TRANSCRIPT"},
                        "metadata": {"duration": 1.23},
                    },
                    "error": None,
                    "process": {"id": "pid"},
                }

        return _Res()


@pytest.mark.asyncio
async def test_audio_handler_sends_completed_webhook_and_persists_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.processing.handlers.audio_handler import handle_audio_job

    # Monkeypatch AudioProcessor + requests.post
    monkeypatch.setattr("src.core.processing.handlers.audio_handler.AudioProcessor", _FakeAudioProcessor)

    posted: List[Dict[str, Any]] = []

    def _fake_post(*, url: str, json: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Any:  # noqa: A002
        posted.append({"url": url, "json": json, "headers": headers, "timeout": timeout})

        class _Resp:
            status_code = 200
            ok = True

        return _Resp()

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.requests.post", _fake_post)

    repo = _FakeRepo()

    # Minimal Job-Objekt: nur Felder, die handler nutzt
    class _Params:
        filename = "C:/tmp/test.wav"
        source_language = "de"
        target_language = "de"
        template = None
        use_cache = False
        context = {"k": "v"}
        webhook = {"url": "http://client/webhook", "token": "t", "jobId": "ext-1"}

    class _Job:
        job_id = "job-1"
        parameters = _Params()

    # ResourceCalculator wird im FakeAudioProcessor nicht genutzt
    class _RC:
        pass

    await handle_audio_job(_Job(), repo, _RC())  # type: ignore[arg-type]

    # Handler sollte Ergebnisse persistieren (status_updates enthält results)
    assert any(u.get("results") is not None for u in repo.status_updates)
    # Und completed Webhook schicken
    completed = [p for p in posted if p["json"].get("phase") == "completed"]
    assert completed, "expected at least one completed webhook payload"
    payload = completed[0]["json"]
    data = payload.get("data") or {}
    # Neuer Standard: transcription.text
    assert (data.get("transcription") or {}).get("text") == "TRANSCRIPT"
    # Keine Aliase / keine Zusatzfelder im strict schema
    assert "transcript_text" not in data


