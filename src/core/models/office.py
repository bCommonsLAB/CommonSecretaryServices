"""
@fileoverview Office Models - Dataclasses for Office document processing (DOCX/XLSX/PPTX)

@description
Diese Modelle definieren die standardisierten Datenstrukturen für Office-Verarbeitung.
Sie sind bewusst eng an die vorhandenen PDF-Modelle angelehnt (vgl. `src/core/models/pdf.py`),
damit Jobs/Webhooks/Downloads konsistent bleiben.

Wichtig:
- Native Dataclasses (kein Pydantic)
- Strikte Typen + Validierung in __post_init__
- to_dict()/from_dict() für Serialisierung
- slots=True für Performance

@module core.models.office
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal, cast


OfficeDocumentType = Literal["docx", "xlsx", "pptx"]
OfficeContentKind = Literal["docx_paragraph", "docx_table", "xlsx_sheet", "pptx_slide"]


@dataclass(frozen=True, slots=True)
class OfficeTextContent:
    """Ein Textblock aus einem Office-Dokument.

    Wir verwenden hier bewusst eine flache Struktur, ähnlich zu `PDFMetadata.text_contents`.
    Dadurch können Clients Inhalte pro Unit (Slide/Sheet/Abschnitt) darstellen oder debuggen.
    """

    index: int
    text: str
    kind: OfficeContentKind

    def __post_init__(self) -> None:
        """Validierung der Felder nach Initialisierung."""
        if self.index < 0:
            raise ValueError("index muss >= 0 sein")
        if not self.kind:
            raise ValueError("kind darf nicht leer sein")
        # text darf leer sein (z.B. leere Folie), wird aber als String erzwungen
        if self.text is None:  # type: ignore[truthy-bool]
            raise ValueError("text darf nicht None sein")

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "text": self.text, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfficeTextContent":
        return cls(
            index=int(data.get("index", 0)),
            text=str(data.get("text", "")),
            kind=cast(OfficeContentKind, data.get("kind", "docx_paragraph")),
        )


@dataclass(frozen=True, slots=True)
class OfficeMetadata:
    """Metadaten einer verarbeiteten Office-Datei."""

    file_name: str
    file_size: int
    format: OfficeDocumentType
    process_dir: Optional[str] = None
    # Assets
    image_paths: List[str] = field(default_factory=list)
    preview_paths: List[str] = field(default_factory=list)
    # Inhalte (pro Unit) – analog zu PDF text_contents
    text_contents: List[OfficeTextContent] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert die Metadaten nach der Initialisierung.

        - file_name muss gesetzt sein
        - file_size muss >= 0 sein
        - format muss einer erlaubten OfficeDocumentType sein
        """
        if not self.file_name or not self.file_name.strip():
            raise ValueError("file_name darf nicht leer sein")
        if self.file_size < 0:
            raise ValueError("file_size muss >= 0 sein")
        if self.format not in ("docx", "xlsx", "pptx"):
            raise ValueError("format muss einer von 'docx', 'xlsx', 'pptx' sein")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_size": self.file_size,
            "format": self.format,
            "process_dir": self.process_dir,
            "image_paths": list(self.image_paths),
            "preview_paths": list(self.preview_paths),
            "text_contents": [tc.to_dict() for tc in self.text_contents],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfficeMetadata":
        raw_text_contents: Any = data.get("text_contents", [])
        text_contents: List[OfficeTextContent] = []
        if isinstance(raw_text_contents, list):
            for item in raw_text_contents:
                if isinstance(item, dict):
                    text_contents.append(OfficeTextContent.from_dict(cast(Dict[str, Any], item)))
        return cls(
            file_name=str(data.get("file_name", "")),
            file_size=int(data.get("file_size", 0)),
            format=cast(OfficeDocumentType, data.get("format", "docx")),
            process_dir=cast(Optional[str], data.get("process_dir")),
            image_paths=[str(p) for p in cast(List[Any], data.get("image_paths", []) or [])],
            preview_paths=[str(p) for p in cast(List[Any], data.get("preview_paths", []) or [])],
            text_contents=text_contents,
        )


@dataclass(frozen=True, slots=True)
class OfficeData:
    """Ergebnisdaten für Office-Verarbeitung (Markdown + Metadaten)."""

    extracted_text: str
    metadata: OfficeMetadata
    markdown_file: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Ergebnisdaten."""
        if self.extracted_text is None:  # type: ignore[truthy-bool]
            raise ValueError("extracted_text darf nicht None sein")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "extracted_text": self.extracted_text,
            "metadata": self.metadata.to_dict(),
            "markdown_file": self.markdown_file,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfficeData":
        metadata_any: Any = data.get("metadata", {})
        metadata_dict: Dict[str, Any] = metadata_any if isinstance(metadata_any, dict) else {}
        return cls(
            extracted_text=str(data.get("extracted_text", "")),
            metadata=OfficeMetadata.from_dict(metadata_dict),
            markdown_file=cast(Optional[str], data.get("markdown_file")),
        )






