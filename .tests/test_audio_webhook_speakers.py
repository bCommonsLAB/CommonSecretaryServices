"""Abschluss-Webhook: Sprecherfelder aus structured_data, sonst nur der Text plus Log."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.api.audio_completed_data import MISSING_SPEAKER_DATA_LOG


class _Repo:
    def __init__(self) -> None:
        self.logs: List[str] = []

    def update_job_status(self, *, job_id: str, status: str, progress: Any = None, results: Any = None, error: Any = None) -> bool:
        return True

    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        self.logs.append(message)
        return True


class _Params:
    filename = "/tmp/diskussion.mp3"
    source_language = "de"
    target_language = "de"
    template = None
    use_cache = False
    context: Dict[str, Any] = {}
    webhook = {"url": "http://client/webhook", "token": "t", "jobId": "ext-9"}
    extra = {"mode": "diarized"}


class _Job:
    job_id = "job-9"
    parameters = _Params()


def _patch_post(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    posted: List[Dict[str, Any]] = []

    def _fake_post(*, url: str, json: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Any:  # noqa: A002
        posted.append(json)

        class _Resp:
            status_code = 200
            ok = True

        return _Resp()

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.requests.post", _fake_post)
    return posted


@pytest.mark.asyncio
async def test_missing_data_block_sends_text_only_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.processing.handlers.audio_handler import handle_audio_job

    class _Processor:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def process_diarized(self, **_kwargs: Any) -> Any:
            class _Res:
                status = "success"

                def to_dict(self) -> Dict[str, Any]:
                    return {"status": "success"}

            return _Res()

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.DiarizedAudioProcessor", _Processor)
    posted = _patch_post(monkeypatch)
    repo = _Repo()

    await handle_audio_job(_Job(), repo, object())  # type: ignore[arg-type]

    completed = [item for item in posted if item.get("phase") == "completed"]
    assert len(completed) == 1
    assert completed[0]["data"] == {"transcription": {"text": ""}}
    assert MISSING_SPEAKER_DATA_LOG in repo.logs


@pytest.mark.asyncio
async def test_finished_chunk_posts_progress_and_job_log(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.processing.handlers.audio_handler import handle_audio_job

    class _Processor:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def process_diarized(self, **kwargs: Any) -> Any:
            kwargs["on_chunk_done"](2, 3, 1200.4, 4)

            class _Res:
                status = "success"

                def to_dict(self) -> Dict[str, Any]:
                    return {"status": "success", "data": {"output_text": "Text", "transcription": {"text": "Text"}}}

            return _Res()

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.DiarizedAudioProcessor", _Processor)
    posted = _patch_post(monkeypatch)
    repo = _Repo()

    await handle_audio_job(_Job(), repo, object())  # type: ignore[arg-type]

    progress = [item for item in posted if item.get("phase") == "progress"]
    messages = [str(item.get("message")) for item in progress]
    assert "Stück 2/3 transkribiert (1200 s, 4 Sprecher)" in messages
    assert "Stück 2/3 transkribiert (1200 s, 4 Sprecher)" in repo.logs


@pytest.mark.asyncio
async def test_heartbeat_posts_progress_with_unchanged_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lebenszeichen: phase=progress, Meldung 'läuft seit', Prozent wie zuletzt gemeldet."""
    from src.core.processing.handlers.audio_handler import handle_audio_job

    class _Processor:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def process_diarized(self, **kwargs: Any) -> Any:
            # Erst ein Lebenszeichen ohne fertiges Stueck, dann ein fertiges, dann wieder eines.
            kwargs["on_chunk_alive"](1, 2, 125.0)
            kwargs["on_chunk_done"](2, 2, 23.0, 1)
            kwargs["on_chunk_alive"](1, 2, 250.0)

            class _Res:
                status = "success"

                def to_dict(self) -> Dict[str, Any]:
                    return {"status": "success", "data": {"output_text": "Text", "transcription": {"text": "Text"}}}

            return _Res()

    monkeypatch.setattr("src.core.processing.handlers.audio_handler.DiarizedAudioProcessor", _Processor)
    posted = _patch_post(monkeypatch)
    repo = _Repo()

    await handle_audio_job(_Job(), repo, object())  # type: ignore[arg-type]

    beats = [item for item in posted if item.get("phase") == "progress" and "läuft seit" in str(item.get("message"))]
    assert [item["message"] for item in beats] == ["Stück 1/2 läuft seit 2 min", "Stück 1/2 läuft seit 4 min"]
    # Vor dem ersten fertigen Stueck gilt der Startwert 20, danach der Wert des fertigen Stuecks (55).
    assert [item["data"]["progress"] for item in beats] == [20, 55]
    assert "Stück 1/2 läuft seit 4 min" in repo.logs
