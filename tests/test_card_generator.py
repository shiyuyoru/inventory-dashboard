import tempfile
import unittest
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw

from card_generator import (
    build_combo_cards,
    collect_required_colors,
    color_code_from_filename,
    combo_filename,
    create_card_run_dir,
    extract_lure_from_poster,
    index_uploaded_files_by_color,
    parse_custom_combo_text,
    prepare_cutouts,
    suppress_soft_shadow,
    validate_cutout_paths,
)


class DummyUpload:
    def __init__(self, name):
        self.name = name


class CardGeneratorTests(unittest.TestCase):
    def test_collect_required_colors_and_filename_are_sorted(self):
        combo_df = pd.DataFrame({"推荐组合色号": ["003、001、014", "014、002、003"]})

        self.assertEqual(collect_required_colors(combo_df), ["001", "002", "003", "014"])
        self.assertEqual(combo_filename(["003", "001", "014"]), "1314.png")

    def test_upload_filename_color_detection(self):
        self.assertEqual(color_code_from_filename("1.png"), "001")
        self.assertEqual(color_code_from_filename("001.png"), "001")
        self.assertEqual(color_code_from_filename("14.jpg"), "014")
        self.assertEqual(color_code_from_filename("014.webp"), "014")
        self.assertEqual(color_code_from_filename("LW118-014.webp"), "")

    def test_index_uploaded_files_reports_missing_inputs(self):
        required = ["001", "002", "003", "004", "005", "006"]
        uploads = [DummyUpload("1.png"), DummyUpload("002.jpg"), DummyUpload("14.webp")]

        indexed, ignored, duplicates = index_uploaded_files_by_color(uploads, required)

        self.assertEqual(sorted(indexed), ["001", "002"])
        self.assertEqual(ignored, ["14.webp"])
        self.assertEqual(duplicates, [])
        self.assertEqual([c for c in required if c not in indexed], ["003", "004", "005", "006"])

    def test_parse_custom_combo_text(self):
        combos, errors = parse_custom_combo_text("3,4\n1，5\n 3, 4, 5, 6\n\n")

        self.assertEqual(combos, [
            ["003", "004"],
            ["001", "005"],
            ["003", "004", "005", "006"],
        ])
        self.assertEqual(errors, [])

    def test_parse_custom_combo_text_reports_invalid_lines(self):
        combos, errors = parse_custom_combo_text("3,abc\n31,4\n5")

        self.assertEqual(combos, [])
        self.assertEqual(len(errors), 3)
        self.assertIn("不是数字", errors[0])
        self.assertIn("超出", errors[1])
        self.assertIn("至少需要 2 个色号", errors[2])

    def test_extract_lure_from_poster_ignores_title_and_color_label(self):
        image = Image.new("RGB", (900, 520), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 45, 260, 70), fill=(30, 30, 30))
        draw.text((80, 78), "NEEDLE STYLO", fill=(20, 20, 20))
        draw.rounded_rectangle((170, 230, 760, 315), radius=40, fill=(50, 150, 210))
        draw.ellipse((180, 245, 230, 295), fill=(245, 245, 245))
        draw.text((430, 420), "005", fill=(40, 160, 210))

        extracted = extract_lure_from_poster(image)

        self.assertIsNotNone(extracted)
        self.assertGreater(extracted.width / extracted.height, 3)
        self.assertLess(extracted.height, 160)

    def test_suppress_soft_shadow_keeps_colored_lure(self):
        image = Image.new("RGBA", (120, 40), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 24, 110, 32), fill=(224, 224, 224, 255))
        draw.rectangle((20, 10, 100, 20), fill=(40, 140, 220, 255))

        cleaned = suppress_soft_shadow(image)

        self.assertEqual(cleaned.getpixel((30, 28))[:3], (255, 255, 255))
        self.assertEqual(cleaned.getpixel((30, 15))[:3], (40, 140, 220))

    def test_build_combo_cards_creates_png_and_zip(self):
        combo_df = pd.DataFrame({"推荐组合色号": ["003、001、014"]})

        with tempfile.TemporaryDirectory() as tmp:
            run_paths = create_card_run_dir(Path(tmp) / "web_runs")
            image_paths = {}
            for idx, color in enumerate(["001", "003", "014"]):
                path = run_paths["raw_dir"] / f"{color}.png"
                image = Image.new("RGBA", (500, 120), (255, 255, 255, 0))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle(
                    (20, 20, 480, 100),
                    radius=30,
                    fill=(180, 80 + idx * 40, 120 + idx * 30, 255),
                )
                image.save(path)
                image_paths[color] = path

            result = build_combo_cards(combo_df, image_paths, run_paths)

            self.assertEqual(len(result.card_paths), 1)
            self.assertEqual(result.card_paths[0].name, "1314.png")
            self.assertTrue(result.zip_path.exists())
            with Image.open(result.card_paths[0]) as card:
                self.assertEqual(card.size, (1000, 1000))

    def test_build_cards_supports_two_to_six_piece_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_paths = create_card_run_dir(Path(tmp) / "web_runs")
            image_paths = {}
            for idx, color in enumerate(["001", "002", "003", "004", "005", "006"]):
                path = run_paths["raw_dir"] / f"{color}.png"
                image = Image.new("RGBA", (700, 150), (255, 255, 255, 0))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle(
                    (18, 18, 682, 132),
                    radius=35,
                    fill=(160 + idx * 10, 70 + idx * 18, 120 + idx * 12, 255),
                )
                image.save(path)
                image_paths[color] = path

            combo_df = pd.DataFrame({
                "推荐组合色号": [
                    "001、002",
                    "001、002、003",
                    "001、002、003、004",
                    "001、002、003、004、005",
                    "001、002、003、004、005、006",
                ]
            })
            result = build_combo_cards(combo_df, image_paths, run_paths)

            self.assertEqual(len(result.card_paths), 5)
            self.assertTrue(result.zip_path.exists())
            for card_path in result.card_paths:
                with Image.open(card_path) as card:
                    self.assertEqual(card.size, (1000, 1000))

    def test_build_cards_only_uses_selected_combo_df(self):
        combo_df = pd.DataFrame({"推荐组合色号": ["003、004"]})

        with tempfile.TemporaryDirectory() as tmp:
            run_paths = create_card_run_dir(Path(tmp) / "web_runs")
            image_paths = {}
            for color in ["003", "004"]:
                path = run_paths["raw_dir"] / f"{color}.png"
                image = Image.new("RGBA", (500, 120), (255, 255, 255, 0))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle((20, 20, 480, 100), radius=30, fill=(180, 80, 120, 255))
                image.save(path)
                image_paths[color] = path

            result = build_combo_cards(combo_df, image_paths, run_paths)

            self.assertEqual([p.name for p in result.card_paths], ["34.png"])

    def test_prepare_cutouts_skips_valid_transparent_png_without_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_paths = create_card_run_dir(Path(tmp) / "web_runs")
            raw_paths = {}
            for color in ["009", "016"]:
                path = run_paths["raw_dir"] / f"{color}.png"
                image = Image.new("RGBA", (520, 130), (255, 255, 255, 0))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle((20, 28, 500, 102), radius=32, fill=(80, 150, 220, 255))
                image.save(path)
                raw_paths[color] = path

            cutout_paths, warnings = prepare_cutouts(raw_paths, run_paths, rembg_session=None)

            self.assertEqual(warnings, [])
            self.assertEqual(sorted(cutout_paths), ["009", "016"])
            self.assertEqual(validate_cutout_paths(["009", "016"], cutout_paths), [])
            self.assertTrue((run_paths["debug_dir"] / "009" / "final_cutout.png").exists())
            self.assertIn("skipped rembg", (run_paths["debug_dir"] / "mapping.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
