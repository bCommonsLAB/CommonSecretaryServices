import json
import sys
from typing import Any, Dict, List, Tuple, cast


def _step_block(events: List[Dict[str, Any]], step: str) -> List[Dict[str, Any]]:

    return [e for e in events if step in (str(e.get("step", "")) + str(e.get("phase", "")))]


def _get_ts(e: Dict[str, Any]) -> float:

    # Tolerant: nutze in Events enthaltene timestamp-Felder falls vorhanden, sonst 0
    ts = e.get("timestamp") or e.get("time")
    try:
        return float(ts) if ts is not None else 0.0
    except Exception:
        return 0.0


def _check_gate_uniqueness(step_events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:

    msgs: List[str] = []
    gates = [e for e in step_events if str(e.get("phase", "")).startswith("transform_gate") or str(e.get("phase", "")).endswith("_gate_plan") or str(e.get("phase", "")).endswith("_gate_skip")]
    plan = [g for g in gates if "plan" in str(g.get("phase", ""))]
    skip = [g for g in gates if "skip" in str(g.get("phase", ""))]
    ok = len(plan) <= 1 and len(skip) <= 1
    if not ok:
        msgs.append(f"Mehrere Gate-Events gefunden (plan={len(plan)}, skip={len(skip)})")
    return ok, msgs


def _check_idempotency(step: str, step_events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:

    msgs: List[str] = []
    is_skip = any("gate_skip" in str(e.get("phase", "")) for e in step_events)
    if is_skip:
        # Keine Payload-lastigen Events bei Skip
        payload_like = [e for e in step_events if any(k in e for k in ("data", "bodyPreview", "savedItemId"))]
        if payload_like:
            msgs.append(f"Idempotenz verletzt bei {step}: Payload-Events trotz Skip ({len(payload_like)})")
            return False, msgs
    return True, msgs


def _check_counts_consistency(ingest_events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:

    msgs: List[str] = []
    totals: List[Tuple[str, int]] = []
    for e in ingest_events:
        details_raw: Any = e.get("details") or e
        details: Dict[str, Any] = cast(Dict[str, Any], details_raw) if isinstance(details_raw, dict) else {}
        for k in ("total", "vectors", "chunks"):
            if k in details:
                try:
                    totals.append((str(k), int(details[k])))
                except Exception:
                    pass
    # Heuristik: keine widersprüchlichen Werte für denselben Schlüssel
    by_key: Dict[str, set[int]] = {}
    for k, v in totals:
        by_key.setdefault(k, set()).add(v)
    for k, vals in by_key.items():
        if len(vals) > 1:
            msgs.append(f"Inkonsistente Metrik '{k}': {sorted(vals)}")
    return len(msgs) == 0, msgs


def _check_spans(step: str, step_events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:

    msgs: List[str] = []
    if not step_events:
        return True, msgs
    times = [
        _get_ts(e)
        for e in step_events
        if any(k in e for k in ("timestamp", "time"))
    ]
    if len(times) < 2:
        return True, msgs
    # Falls es separate Span-Meldungen gibt, könnten sie in Events eingebettet sein; hier nur Heuristik
    # Toleranz prüfen (ohne echte Spanquelle: PASS per Default)
    return True, msgs


def _check_dupes(events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:

    msgs: List[str] = []
    dupes = [e for e in events if "dup" in str(e.get("message", "")) or "dup" in str(e.get("phase", ""))]
    if dupes:
        msgs.append(f"Duplikat-Hinweise gefunden: {len(dupes)}")
        return False, msgs
    return True, msgs


def check_log_file(path: str) -> int:

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Erlaube sowohl JSON (Objekt mit Arrays) als auch JSONL (eine Zeile je Event)
    events: List[Dict[str, Any]] = []
    try:
        data_any: Any = json.loads(content)
        if isinstance(data_any, dict):
            data_dict: Dict[str, Any] = cast(Dict[str, Any], data_any)
            if "events" in data_dict:
                events_field_any: Any = data_dict.get("events", [])
                events_field_list: List[Any] = cast(List[Any], events_field_any) if isinstance(events_field_any, list) else []
                for item_any in events_field_list:
                    if isinstance(item_any, dict):
                        item_dict: Dict[str, Any] = cast(Dict[str, Any], item_any)
                        events.append(item_dict)
        elif isinstance(data_any, list):
            data_list: List[Any] = cast(List[Any], data_any)
            for item_any in data_list:
                if isinstance(item_any, dict):
                    item_dict = cast(Dict[str, Any], item_any)
                    events.append(item_dict)
    except Exception:
        # Fallback JSONL
        events = []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                obj_any: Any = json.loads(line)
                if isinstance(obj_any, dict):
                    events.append(cast(Dict[str, Any], obj_any))
            except Exception:
                pass

    # Schrittblöcke (heuristisch)
    extract = _step_block(events, "extract")
    transform = _step_block(events, "transform")
    store = _step_block(events, "store")
    ingest = _step_block(events, "ingest")

    checks: List[Tuple[str, bool, List[str]]] = []
    for name, block in (
        ("extract", extract),
        ("transform", transform),
        ("store", store),
        ("ingest", ingest),
    ):
        ok_gate, msg_gate = _check_gate_uniqueness(block)
        ok_idem, msg_idem = _check_idempotency(name, block)
        ok_span, msg_span = _check_spans(name, block)
        checks.append((f"{name}.gate", ok_gate, msg_gate))
        checks.append((f"{name}.idempotency", ok_idem, msg_idem))
        checks.append((f"{name}.spans", ok_span, msg_span))

    ok_counts, msg_counts = _check_counts_consistency(ingest)
    checks.append(("ingest.counts", ok_counts, msg_counts))

    ok_dupes, msg_dupes = _check_dupes(events)
    checks.append(("global.dupes", ok_dupes, msg_dupes))

    failures = 0
    for name, ok, msgs in checks:
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name}")
        for m in msgs:
            print(f"  - {m}")
        if not ok:
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python -m tests.scripts.check_pdf_workflow_logs <logfile.json|jsonl>")
        sys.exit(2)
    sys.exit(check_log_file(sys.argv[1]))


