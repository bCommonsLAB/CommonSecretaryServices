"""Tests für das Rendern des Hefts: Auffüllen, HTML, PDF-Maße, Schriften, Bild-ppi.

Die PDF-Tests laufen nur, wenn WeasyPrint samt Pango geladen werden kann.
Unter Windows z. B. mit WEASYPRINT_DLL_DIRECTORIES auf einen Ordner mit den GTK-DLLs.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from src.core.models.booklet import BookletRequest
from src.core.resource_tracking import ResourceCalculator
from src.processors.booklet.render import BookletRenderer, TEMPLATES_ROOT, pad_to_multiple_of_four
from src.processors.booklet.tokens import THEMES
from src.processors.booklet_processor import BookletProcessor


def _weasyprint_available() -> bool:
    try:
        from weasyprint import HTML  # type: ignore
        HTML(string="<p>x</p>").write_pdf()
        return True
    except Exception:
        return False


WEASYPRINT_OK = _weasyprint_available()


def _page(kind: str, page_id: str) -> dict:
    return {"type": kind, "id": page_id, "theme": THEMES["marke"], "partial": f"{kind}.html", "css_class": ""}


class TestPadding(unittest.TestCase):
    def test_multiple_of_four_is_unchanged(self) -> None:
        pages = [_page("cover", "c"), _page("project", "p1"), _page("project", "p2"), _page("back", "b")]
        self.assertEqual([p["id"] for p in pad_to_multiple_of_four(pages)], ["c", "p1", "p2", "b"])

    def test_blanks_go_before_back_matter(self) -> None:
        pages = [_page("cover", "c"), _page("text", "intro"), _page("project", "p1"),
                 _page("text", "outro"), _page("back", "b")]
        padded = pad_to_multiple_of_four(pages)
        self.assertEqual(len(padded), 8)
        self.assertEqual([p["type"] for p in padded],
                         ["cover", "text", "project", "blank", "blank", "blank", "text", "back"])

    def test_without_content_pages_blanks_are_appended(self) -> None:
        padded = pad_to_multiple_of_four([_page("text", "a")])
        self.assertEqual([p["type"] for p in padded], ["text", "blank", "blank", "blank"])


class TestRenderer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        BookletProcessor.work_root = self.tmp / "work"
        photo = self.tmp / "foto.jpg"
        Image.new("RGB", (4000, 3000), (60, 110, 70)).save(photo, "JPEG", quality=90)
        self.request = BookletRequest.from_dict({
            "title": "Testheft",
            "pages": [
                {"type": "cover", "id": "cover", "title": "b*coop Projektheft", "subtitle": "Projekte 2026",
                 "image_url": str(photo), "focus": {"y": 40}},
                {"type": "text", "id": "vorwort", "template": "intro", "heading": "Vorwort",
                 "markdown": "Wir sind eine **Genossenschaft** mit Silbentrennungsbedarf für Donaudampfschifffahrtsgesellschaften."},
                {"type": "divider", "id": "teil1", "theme": "natur", "heading": "Projekte"},
                {"type": "project", "id": "garden", "title": "b*garden", "theme": "Natur",
                 "text": "Ein Stück Garten für alle, die keinen haben. Gemeinschaftlich bewirtschaftet.",
                 "image_url": str(photo), "focus": {"y": 3},
                 "qr_url": "https://wiki.bcommonslab.org/projekte?id=garden",
                 "organization": {"name": "b*coop"}},
                {"type": "project", "id": "ohne", "title": "IT-Helden für kleine Organisationen", "theme": "lernen",
                 "text": "Ohne Bild."},
                {"type": "text", "id": "impressum", "template": "impressum", "heading": "Impressum",
                 "markdown": "b*coop Genossenschaft"},
                {"type": "back", "id": "back", "markdown": "wiki.bcommonslab.org",
                 "qr_url": "https://wiki.bcommonslab.org"},
            ],
        })
        self.processor = BookletProcessor(ResourceCalculator(), process_id="job-render")
        self.images = self.processor.prepare_images(self.request)

    def tearDown(self) -> None:
        BookletProcessor.work_root = None
        self._tmp.cleanup()

    def test_template_folder_exists(self) -> None:
        self.assertTrue((TEMPLATES_ROOT / "bcoop-heft-120" / "base.html").is_file())
        self.assertTrue((TEMPLATES_ROOT / "bcoop-heft-120" / "fonts" / "Jost-Regular.ttf").is_file())

    def test_html_contains_pages_and_theme_classes(self) -> None:
        html = BookletRenderer().render_html(self.request, self.images)
        self.assertIn('class="page page-project theme-natur"', html)
        self.assertIn("images/garden.jpg", html)
        self.assertIn("<strong>Genossenschaft</strong>", html)
        self.assertIn("<svg", html)  # QR
        self.assertIn("text-impressum", html)
        self.assertNotIn("note-too-long", html)  # kein Text über 400 Zeichen im Mustersatz
        self.assertEqual(html.count('<section class="page'), 8)  # 7 Seiten + 1 Leerseite

    def test_processor_render_pdf_marks_stage(self) -> None:
        if not WEASYPRINT_OK:
            self.skipTest("WeasyPrint/Pango nicht verfügbar")
        result = self.processor.render_pdf(self.request, self.images)
        self.assertEqual(result.stage, "pdf")
        self.assertEqual(result.pdf_file, "heft.pdf")
        self.assertIn("heft.pdf", result.assets)
        self.assertIsNotNone(result.pdf)
        assert result.pdf is not None
        self.assertTrue(result.pdf["page_count_ok"])
        self.assertEqual(result.pdf["page_count"], 8)

    def test_pdf_geometry_fonts_and_ppi(self) -> None:
        if not WEASYPRINT_OK:
            self.skipTest("WeasyPrint/Pango nicht verfügbar")
        result = self.processor.render_pdf(self.request, self.images)
        pdf_path = Path(result.work_dir) / "heft.pdf"
        self.assertTrue(pdf_path.is_file())

        doc = fitz.open(str(pdf_path))
        try:
            self.assertEqual(doc.page_count, 8)
            first = doc[0]
            self.assertAlmostEqual(first.mediabox.width * 25.4 / 72, 126.0, delta=0.2)
            self.assertAlmostEqual(first.trimbox.width * 25.4 / 72, 120.0, delta=0.2)
            self.assertEqual(doc.metadata.get("title"), "Testheft")

            # 7 Seiten plus eine Leerseite vor dem Nachspann: ... ohne (5), blank (6), Impressum (7), Rückseite (8)
            self.assertIn("wiki.bcommonslab.org", doc[7].get_text())
            self.assertIn("Impressum", doc[6].get_text())
            self.assertEqual(doc[5].get_text().strip(), "")

            # Projektseite: Titel und Thema sichtbar, Bild in Druckauflösung
            project_text = doc[3].get_text()
            self.assertIn("b*garden", project_text)
            self.assertIn("NATUR", project_text)
        finally:
            doc.close()

        assert result.pdf is not None
        garden_page = result.pdf["pages"][3]
        self.assertTrue(garden_page["images"], "Projektseite hat ein Bild")
        self.assertGreaterEqual(garden_page["images"][0]["ppi"], 299)
        self.assertAlmostEqual(garden_page["images"][0]["box_mm"]["width"], 126.0, delta=0.3)

        # Schrift eingebettet. Unter Windows lädt WeasyPrint mit den GTK-DLLs aus Fremdinstallationen
        # keine @font-face-Dateien und nimmt stumm Systemschriften; die Prüfung gilt dort nicht.
        # Im Linux-Container (Zielplattform) muss Jost als Subset eingebettet sein.
        self.assertEqual(result.pdf["fonts_not_embedded"], [])
        if sys.platform == "win32" and not any("Jost" in f for f in result.pdf["fonts_embedded"]):
            self.skipTest("Windows-Fontconfig lädt keine @font-face-Dateien; Schriftprüfung nur im Container")
        self.assertTrue(any("Jost" in f for f in result.pdf["fonts_embedded"]), result.pdf["fonts_embedded"])


if __name__ == "__main__":
    unittest.main()
