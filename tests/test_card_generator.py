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
    index_uploaded_files_by_color,
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


if __name__ == "__main__":
    unittest.main()
