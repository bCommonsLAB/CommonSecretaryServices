"""Tests für die Booklet-Bildpipeline: Ausschnitt, Duoton, Wasserzeichen, Modelle, Prozessor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.core.exceptions import ValidationError
from src.core.models.booklet import BookletPage, BookletRequest
from src.core.resource_tracking import ResourceCalculator
from src.processors.booklet.duotone import apply_duotone
from src.processors.booklet.images import crop_to_frame, load_image
from src.processors.booklet.tokens import PHOTO_PX, THEMES, hex_to_rgb, readiness, resolve_theme
from src.processors.booklet.watermark import add_too_small_band, placeholder_image
from src.processors.booklet_processor import BookletProcessor


def _gradient(width: int, height: int) -> Image.Image:
    """Vertikaler Verlauf: oben schwarz, unten weiß. Damit ist die Lage des Ausschnitts messbar."""
    image = Image.new("L", (width, height))
    image.putdata([int(255 * (y / max(1, height - 1))) for y in range(height) for _ in range(width)])
    return image.convert("RGB")


class TestTokens(unittest.TestCase):
    def test_photo_px_matches_300dpi(self) -> None:
        self.assertEqual(PHOTO_PX, (1488, 685))

    def test_resolve_theme_accepts_bwiki_values_and_defaults_to_marke(self) -> None:
        self.assertEqual(resolve_theme("Natur").key, "natur")
        self.assertEqual(resolve_theme("ZUSAMMENHALT").key, "zusammenhalt")
        self.assertEqual(resolve_theme("b*coop").key, "marke")
        self.assertEqual(resolve_theme(None).key, "marke")
        self.assertEqual(resolve_theme("gibt es nicht").key, "marke")

    def test_all_themes_have_valid_colours(self) -> None:
        for theme in THEMES.values():
            for value in (theme.dark, theme.bar, theme.shadow, theme.light):
                r, g, b = hex_to_rgb(value)
                self.assertTrue(0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255)

    def test_readiness_thresholds(self) -> None:
        self.assertEqual(readiness(300), "ready")
        self.assertEqual(readiness(299.9), "borderline")
        self.assertEqual(readiness(220), "borderline")
        self.assertEqual(readiness(219), "not-ready")


class TestCrop(unittest.TestCase):
    def test_four_to_three_uses_full_width_and_focus_top(self) -> None:
        result = crop_to_frame(_gradient(4000, 3000), focus_x=50, focus_y=3)
        self.assertEqual(result.crop["x"], 0)
        self.assertEqual(result.crop["width"], 4000)
        self.assertEqual(result.crop["y"], 0)  # Fokus fast oben: Fenster klemmt an der Oberkante
        self.assertAlmostEqual(result.crop["height"], 4000 / (126 / 58), delta=1)
        self.assertEqual(result.image.size, PHOTO_PX)  # verkleinert auf das Fotofeld
        self.assertGreater(result.dpi, 800)
        self.assertEqual(result.source_size, (4000, 3000))

    def test_focus_bottom_moves_window_down(self) -> None:
        top = crop_to_frame(_gradient(2000, 1500), focus_y=0)
        bottom = crop_to_frame(_gradient(2000, 1500), focus_y=100)
        self.assertEqual(top.crop["y"], 0)
        self.assertEqual(bottom.crop["y"], 1500 - bottom.crop["height"])
        # unten ist der Verlauf heller
        self.assertGreater(bottom.image.convert("L").getpixel((10, 10)), top.image.convert("L").getpixel((10, 10)))

    def test_wide_banner_uses_full_height_and_focus_x(self) -> None:
        result = crop_to_frame(_gradient(6000, 1000), focus_x=100)
        self.assertEqual(result.crop["height"], 1000)
        self.assertAlmostEqual(result.crop["width"], 1000 * (126 / 58), delta=1)
        self.assertEqual(result.crop["x"], 6000 - result.crop["width"])

    def test_small_image_is_not_upscaled(self) -> None:
        result = crop_to_frame(_gradient(800, 600))
        self.assertEqual(result.crop["width"], 800)
        self.assertEqual(result.image.size[0], 800)
        self.assertLess(result.dpi, 220)
        self.assertEqual(readiness(result.dpi), "not-ready")

    def test_pipeline_output_1440_is_borderline(self) -> None:
        result = crop_to_frame(_gradient(1440, 1080))
        self.assertEqual(readiness(result.dpi), "borderline")
        self.assertAlmostEqual(result.dpi, 290, delta=1)


class TestDuotone(unittest.TestCase):
    def test_black_and_white_map_to_shadow_and_light(self) -> None:
        theme = THEMES["natur"]
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (0, 0, 0))
        image.putpixel((1, 0), (255, 255, 255))
        toned = apply_duotone(image, theme.shadow, theme.light)
        self.assertEqual(toned.getpixel((0, 0)), hex_to_rgb(theme.shadow))
        self.assertEqual(toned.getpixel((1, 0)), hex_to_rgb(theme.light))

    def test_midtone_lies_between_endpoints(self) -> None:
        toned = apply_duotone(Image.new("RGB", (1, 1), (128, 128, 128)), "#000000", "#ffffff", contrast=1.0)
        r, g, b = toned.getpixel((0, 0))
        self.assertTrue(100 < r < 160 and r == g == b)

    def test_output_is_rgb(self) -> None:
        toned = apply_duotone(_gradient(40, 30), THEMES["leben"].shadow, THEMES["leben"].light)
        self.assertEqual(toned.mode, "RGB")
        self.assertEqual(toned.size, (40, 30))


class TestWatermark(unittest.TestCase):
    def test_band_changes_pixels_and_keeps_size(self) -> None:
        source = Image.new("RGB", (600, 276), (200, 200, 200))
        marked = add_too_small_band(source, dpi=161)
        self.assertEqual(marked.size, source.size)
        self.assertEqual(marked.mode, "RGB")
        # Die Bildmitte liegt auf dem Band
        centre = marked.getpixel((300, 138))
        self.assertNotEqual(centre, (200, 200, 200))
        self.assertGreater(centre[0], centre[1])  # rötlich
        # Eine Ecke bleibt unberührt
        self.assertEqual(marked.getpixel((5, 5)), (200, 200, 200))

    def test_placeholder_uses_bar_colour(self) -> None:
        theme = THEMES["arbeiten"]
        plate = placeholder_image(theme)
        self.assertEqual(plate.size, PHOTO_PX)
        self.assertEqual(plate.getpixel((5, 5)), hex_to_rgb(theme.bar))


class TestModels(unittest.TestCase):
    def test_request_requires_pages(self) -> None:
        with self.assertRaises(ValidationError):
            BookletRequest.from_dict({"title": "x"})
        with self.assertRaises(ValidationError):
            BookletRequest.from_dict({"pages": []})

    def test_request_rejects_unknown_type_and_duplicate_ids(self) -> None:
        with self.assertRaises(ValidationError):
            BookletRequest.from_dict({"pages": [{"type": "poster"}]})
        with self.assertRaises(ValidationError):
            BookletRequest.from_dict({"pages": [{"type": "blank", "id": "a"}, {"type": "blank", "id": "a"}]})

    def test_request_fills_defaults(self) -> None:
        req = BookletRequest.from_dict({
            "pages": [
                {"type": "cover", "title": "Heft"},
                {"type": "project", "id": "p1", "theme": "Natur", "focus": {"y": 10}},
            ]
        })
        self.assertEqual(req.template, "bcoop-heft-120")
        self.assertEqual(req.pages[0].id, "page-001")
        self.assertEqual(req.pages[1].focus.x, 50.0)
        self.assertEqual(req.pages[1].focus.y, 10.0)
        self.assertTrue(req.pages[0].has_image_slot)
        self.assertFalse(BookletPage.from_dict({"type": "text"}, 0).has_image_slot)


class TestProcessor(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        BookletProcessor.work_root = self.tmp / "work"
        big = self.tmp / "big.jpg"
        _gradient(4000, 3000).save(big, "JPEG", quality=90)
        small = self.tmp / "small.jpg"
        _gradient(800, 600).save(small, "JPEG", quality=90)
        self.big = str(big)
        self.small = str(small)

    def tearDown(self) -> None:
        BookletProcessor.work_root = None
        self._tmp.cleanup()

    def test_load_image_from_path_returns_rgb(self) -> None:
        image = load_image(self.big)
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (4000, 3000))

    def test_prepare_images_writes_files_and_report(self) -> None:
        request = BookletRequest.from_dict({
            "title": "Test",
            "pages": [
                {"type": "cover", "id": "cover", "image_url": self.big, "theme": "marke"},
                {"type": "text", "id": "intro", "markdown": "Hallo"},
                {"type": "project", "id": "gut", "theme": "natur", "image_url": self.big, "focus": {"y": 3}},
                {"type": "project", "id": "klein", "theme": "leben", "image_url": self.small},
                {"type": "project", "id": "ohne", "theme": "lernen"},
                {"type": "project", "id": "kaputt", "theme": "arbeiten", "image_url": str(self.tmp / "fehlt.jpg")},
            ],
        })
        processor = BookletProcessor(ResourceCalculator(), process_id="job-test")
        result = processor.prepare_images(request)

        self.assertEqual(result.stage, "images")
        self.assertEqual(result.page_count, 6)
        by_id = {r.page_id: r for r in result.images}
        self.assertEqual(set(by_id), {"cover", "gut", "klein", "ohne", "kaputt"})
        self.assertEqual(by_id["gut"].status, "ready")
        self.assertEqual((by_id["gut"].output_width, by_id["gut"].output_height), PHOTO_PX)
        self.assertEqual(by_id["klein"].status, "not-ready")
        self.assertTrue(any("zu klein" in w for w in by_id["klein"].warnings))
        self.assertEqual(by_id["ohne"].status, "missing")
        self.assertEqual(by_id["kaputt"].status, "error")
        self.assertEqual(result.summary["ready"], 2)

        work = Path(result.work_dir)
        self.assertTrue(work.is_relative_to(self.tmp / "work"))
        for report in result.images:
            self.assertTrue((work / "images" / report.file).is_file(), report.file)
        report_json = json.loads((work / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report_json["summary"], result.summary)
        self.assertIn("report.json", result.assets)
        self.assertIn("images/gut.jpg", result.assets)

        # Duoton: der Ausschnitt aus dem Verlauf ist getönt, nicht grau
        toned = Image.open(work / "images" / "gut.jpg").convert("RGB")
        r, g, b = toned.getpixel((744, 600))
        self.assertFalse(r == g == b)


if __name__ == "__main__":
    unittest.main()
