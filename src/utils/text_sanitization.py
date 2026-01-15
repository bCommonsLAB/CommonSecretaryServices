from __future__ import annotations

import re


_FENCED_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", flags=re.MULTILINE)


def remove_fenced_code_blocks(text: str) -> str:
    """
    Entfernt Markdown-Codeblöcke (```...```).

    Motivation:
    - Für bestimmte Prompt-Use-Cases (z.B. Cursor-Chat-Analyse) wollen wir Codeblöcke ignorieren,
      damit sich die Zusammenfassung stärker auf Fragen/Antworten/Entscheidungen fokussiert.
    - Wir entfernen nur fenced blocks; Inline-Code bleibt erhalten (kann z.B. wichtige Bezeichner enthalten).
    """
    return _FENCED_CODE_BLOCK_RE.sub("", text)






