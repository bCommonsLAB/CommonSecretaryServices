"""Audio-Job mit mode=diarized: der Handler nimmt den Sprecher-Processor und liest output_text."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


class _FakeRepo:
    def __init__(self) -> None:
        self.status_updates: List[Dict[str, Any]] = []
        self.logs: List[str] = []

    def update_job_status(self, *, job_id: str, status: str, progress: Any = None, results: Any = None, error: Any = None) -> bool:
        self.status_updates.append({"status": status, "results": results, "progress": progress})
        return True

    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        self.logs.append(message)
        return True


class _FakeDiarizedProcessor:
    calls: List[Dict[str, Any]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def process_diarized(self, **kwargs: Any) -> Any:
        _FakeDiarizedProcessor.calls.append(kwargs)

        class _Res:
            status = "success"

            def to_dict(self) -> Dict[str, Any]:
                return {
                    "status": "success",
                    "data": {
                        "output_text": "**Sprecher A:** Hallo",
                        "speakers": ["Sprecher A"],
                        "segments": [{"speaker": "Sprecher A", "start": 0.0, "end": 1.2, "text": "Hallo"}],
                        "dropped_context": ["prompt: kein Freitext"],
                        "detected_language": "de",
                        "from_cache": False,
                    },
                }

        return _Res()


class _NeverUsedPlainProcessor:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("mode=diarized darf nicht den normalen AudioProcessor nehmen")


@pytest.mark.asyncio
async def test_diarized_mode_uses_diarized_processor_and_output_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.processing.handlers.audio_handler import handle_audio_job

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.DiarizedAudioProcessor", _FakeDiarizedProcessor)
    monkeypatch.setattr("src.core.processing.handlers.audio_handler.AudioProcessor", _NeverUsedPlainProcessor)

    posted: List[Dict[str, Any]] = []

    def _fake_post(*, url: str, json: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Any:  # noqa: A002
        posted.append(json)

        class _Resp:
            status_code = 200
            ok = True

        return _Resp()

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.requests.post", _fake_post)

    class _Params:
        filename = "/tmp/diskussion.mp3"
        source_language = "de"
        target_language = "de"
        template = None
        use_cache = True
        context = {"original_filename": "diskussion.mp3"}
        webhook = {"url": "http://client/webhook", "token": "t", "jobId": "ext-7"}
        # Unbekannte Felder landen bei JobParameters.from_dict in extra
        extra = {"mode": "diarized", "transcription_context": {"language": "de", "prompt": "Thema", "keywords": ["Name"]}}

    class _Job:
        job_id = "job-7"
        parameters = _Params()

    await handle_audio_job(_Job(), _FakeRepo(), object())  # type: ignore[arg-type]

    assert _FakeDiarizedProcessor.calls, "process_diarized wurde nicht aufgerufen"
    context = _FakeDiarizedProcessor.calls[0]["transcription_context"]
    assert context is not None and context.prompt == "Thema" and context.keywords == ["Name"]
    completed = [p for p in posted if p.get("phase") == "completed"]
    assert completed
    payload = completed[0]["data"]
    assert payload["transcription"]["text"] == "**Sprecher A:** Hallo"
    assert payload["output_text"] == "**Sprecher A:** Hallo"
    assert payload["speakers"] == ["Sprecher A"]
    assert payload["segments"][0]["speaker"] == "Sprecher A"
    assert payload["dropped_context"] == ["prompt: kein Freitext"]
    assert payload["detected_language"] == "de"
    assert payload["from_cache"] is False


@pytest.mark.asyncio
async def test_unknown_mode_is_rejected() -> None:
    from src.core.processing.handlers.audio_handler import handle_audio_job

    class _Params:
        filename = "/tmp/x.mp3"
        extra = {"mode": "irgendwas"}

    class _Job:
        job_id = "job-8"
        parameters = _Params()

    with pytest.raises(ValueError):
        await handle_audio_job(_Job(), _FakeRepo(), object())  # type: ignore[arg-type]
