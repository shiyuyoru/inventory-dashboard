from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
CANVAS_SIZE = 1000
CARD_SIZE = (CANVAS_SIZE, CANVAS_SIZE)
CARD_BACKGROUND = (255, 255, 255)
TEXT_COLOR = (45, 45, 45)
TEXT_PAD_WIDTH = 3

LEFT_AREA_X1 = 55
LEFT_AREA_X2 = 780
LABEL_X = 840
FONT_SIZE_BY_COUNT = {
    2: 58,
    3: 56,
    4: 52,
    5: 48,
    6: 44,
}
TOP_MARGIN_BY_COUNT = {
    2: 105,
    3: 70,
    4: 50,
    5: 34,
    6: 24,
}
BOTTOM_MARGIN_BY_COUNT = {
    2: 105,
    3: 70,
    4: 50,
    5: 34,
    6: 24,
}
MAX_BOX_WIDTH_BY_COUNT = {
    2: 730,
    3: 730,
    4: 720,
    5: 700,
    6: 680,
}
MAX_BOX_HEIGHT_BY_COUNT = {
    2: 320,
    3: 255,
    4: 205,
    5: 170,
    6: 145,
}
ROW_HEIGHT_RATIO = 0.92

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
]


@dataclass(frozen=True)
class CardGenerationResult:
    run_dir: Path
    raw_dir: Path
    png_dir: Path
    cards_dir: Path
    zip_path: Path
    card_paths: list[Path]
    missing_colors: list[str]


def normalize_color_code(value) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit():
        return ""
    number = int(text)
    if not 1 <= number <= 30:
        return ""
    return str(number).zfill(3)


def color_code_from_filename(filename: str) -> str:
    stem = Path(str(filename or "")).stem.strip()
    if not re.fullmatch(r"\d{1,3}", stem):
        return ""
    return normalize_color_code(stem)


def index_uploaded_files_by_color(uploaded_files, required_colors: Iterable[str] | None = None):
    required = set(required_colors or [])
    uploaded_by_color = {}
    ignored_files = []
    duplicate_files = []

    for uploaded in uploaded_files or []:
        color = color_code_from_filename(getattr(uploaded, "name", ""))
        if not color or (required and color not in required):
            ignored_files.append(getattr(uploaded, "name", ""))
            continue
        if color in uploaded_by_color:
            duplicate_files.append(getattr(uploaded, "name", ""))
        uploaded_by_color[color] = uploaded

    return uploaded_by_color, ignored_files, duplicate_files


def parse_combo_colors(combo_value) -> list[str]:
    if combo_value is None:
        return []
    text = str(combo_value).strip()
    if not text:
        return []
    parts = re.split(r"[\s,，、/;+]+", text)
    colors = [normalize_color_code(part) for part in parts]
    return [color for color in colors if color]


def format_combo_colors(colors: Iterable[str]) -> str:
    normalized = [normalize_color_code(color) for color in colors]
    valid = [color for color in normalized if color]
    return "、".join(sorted(valid, key=lambda item: int(item)))


def parse_custom_combo_text(text: str) -> tuple[list[list[str]], list[str]]:
    combos: list[list[str]] = []
    errors: list[str] = []
    seen: set[tuple[str, ...]] = set()

    for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        tokens = [token for token in re.split(r"[\s,，、/;+]+", line) if token]
        if not tokens:
            errors.append(f"第 {line_no} 行为空组合。")
            continue

        colors: list[str] = []
        line_errors: list[str] = []
        for token in tokens:
            if not token.isdigit():
                line_errors.append(f"{token} 不是数字")
                continue
            color = normalize_color_code(token)
            if not color:
                line_errors.append(f"{token} 超出 001-030")
                continue
            colors.append(color)

        if line_errors:
            errors.append(f"第 {line_no} 行无效：" + "，".join(line_errors) + "。")
            continue
        if len(colors) < 2:
            errors.append(f"第 {line_no} 行无效：组合至少需要 2 个色号。")
            continue
        if len(colors) > 6:
            errors.append(f"第 {line_no} 行无效：组合最多支持 6 个色号。")
            continue

        key = tuple(sorted(colors, key=lambda item: int(item)))
        if key in seen:
            continue
        seen.add(key)
        combos.append(list(key))

    return combos, errors


def collect_required_colors(combo_df, combo_col: str = "推荐组合色号") -> list[str]:
    if combo_df is None or combo_df.empty or combo_col not in combo_df.columns:
        return []
    colors: set[str] = set()
    for value in combo_df[combo_col].dropna().tolist():
        colors.update(parse_combo_colors(value))
    return sorted(colors, key=lambda item: int(item))


def combo_filename(colors: Iterable[str]) -> str:
    normalized = [normalize_color_code(color) for color in colors]
    numbers = [str(int(color)) for color in sorted((c for c in normalized if c), key=lambda item: int(item))]
    return "".join(numbers) + ".png"


def create_card_run_dir(base_dir: Path | str = "web_runs") -> dict[str, Path]:
    base = Path(base_dir)
    run_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = base / run_name
    raw_dir = run_dir / "raw"
    png_dir = run_dir / "png"
    cards_dir = run_dir / "cards"
    for directory in [raw_dir, png_dir, cards_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": run_dir,
        "raw_dir": raw_dir,
        "png_dir": png_dir,
        "cards_dir": cards_dir,
        "zip_path": run_dir / "result.zip",
    }


def save_uploaded_color_image(uploaded_file, color_code: str, raw_dir: Path) -> Path:
    color = normalize_color_code(color_code)
    if not color:
        raise ValueError(f"Invalid color code: {color_code}")
    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".png"
    out_path = raw_dir / f"{color}{suffix}"
    out_path.write_bytes(uploaded_file.getvalue())
    return out_path


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in FONT_CANDIDATES:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def format_label(color_code: str) -> str:
    return normalize_color_code(color_code) or str(color_code).zfill(TEXT_PAD_WIDTH)


def trim_transparent(image: Image.Image, padding: int = 8) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return image

    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)
    return image.crop((left, top, right, bottom))


def resize_keep_ratio(image: Image.Image, scale: float) -> Image.Image:
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _layout_config(count: int) -> tuple[int, int, int, int, int]:
    safe_count = min(max(count, 2), 6)
    top = TOP_MARGIN_BY_COUNT.get(safe_count, 40)
    bottom = BOTTOM_MARGIN_BY_COUNT.get(safe_count, 40)
    max_width = min(MAX_BOX_WIDTH_BY_COUNT.get(safe_count, 700), LEFT_AREA_X2 - LEFT_AREA_X1)
    max_height = MAX_BOX_HEIGHT_BY_COUNT.get(safe_count, 160)
    font_size = FONT_SIZE_BY_COUNT.get(safe_count, 46)
    return top, bottom, max_width, max_height, font_size


def layout_rows(count: int) -> list[int]:
    top, bottom, _, _, _ = _layout_config(count)
    available = CARD_SIZE[1] - top - bottom
    row_height = available / max(count, 1)
    return [round(top + row_height * (i + 0.5)) for i in range(count)]


def load_source_image(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema() == (255, 255):
        background = Image.new("RGBA", image.size, CARD_BACKGROUND + (255,))
        background.alpha_composite(image)
        image = background
    return trim_transparent(image)


def make_combo_card(combo_colors: list[str], image_paths: dict[str, Path], out_path: Path) -> Path:
    normalized = [normalize_color_code(color) for color in combo_colors]
    normalized = [color for color in normalized if color]
    missing = [color for color in normalized if color not in image_paths]
    if missing:
        raise FileNotFoundError(f"Missing color images: {', '.join(missing)}")

    sorted_combo = sorted(normalized, key=lambda item: int(item))
    images: list[tuple[str, Image.Image]] = []
    for color in sorted_combo:
        images.append((color, load_source_image(image_paths[color])))

    if not images:
        raise ValueError("Empty combo colors")

    count = len(images)
    centers = layout_rows(count)
    top, bottom, max_box_width, max_box_height, font_size = _layout_config(count)
    available = CARD_SIZE[1] - top - bottom
    row_height = available / max(count, 1)
    box_height = min(max_box_height, round(row_height * ROW_HEIGHT_RATIO))

    canvas = Image.new("RGB", CARD_SIZE, CARD_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    font = load_font(font_size)
    left_area_width = LEFT_AREA_X2 - LEFT_AREA_X1

    for (color, image), center_y in zip(images, centers):
        scale = min(max_box_width / image.width, box_height / image.height)
        resized = resize_keep_ratio(image, scale)
        x = round(LEFT_AREA_X1 + (left_area_width - resized.width) / 2)
        y = round(center_y - resized.height / 2)
        canvas.paste(resized.convert("RGB"), (x, y), resized.getchannel("A"))

        label = format_label(color)
        text_box = draw.textbbox((0, 0), label, font=font)
        text_height = text_box[3] - text_box[1]
        draw.text((LABEL_X, round(center_y - text_height / 2) - 2), label, fill=TEXT_COLOR, font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def build_combo_cards(combo_df, image_paths: dict[str, Path], run_paths: dict[str, Path]) -> CardGenerationResult:
    card_paths: list[Path] = []
    missing_colors: set[str] = set()
    seen_names: set[str] = set()

    if combo_df is not None and not combo_df.empty and "推荐组合色号" in combo_df.columns:
        for _, row in combo_df.iterrows():
            colors = parse_combo_colors(row.get("推荐组合色号"))
            if not colors:
                continue
            missing = [color for color in colors if color not in image_paths]
            if missing:
                missing_colors.update(missing)
                continue

            filename = combo_filename(colors)
            if filename in seen_names:
                stem = Path(filename).stem
                filename = f"{stem}_{len(seen_names) + 1}.png"
            seen_names.add(filename)
            out_path = run_paths["cards_dir"] / filename
            card_paths.append(make_combo_card(colors, image_paths, out_path))

    zip_path = run_paths["zip_path"]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for card_path in card_paths:
            zf.write(card_path, arcname=card_path.name)

    return CardGenerationResult(
        run_dir=run_paths["run_dir"],
        raw_dir=run_paths["raw_dir"],
        png_dir=run_paths["png_dir"],
        cards_dir=run_paths["cards_dir"],
        zip_path=zip_path,
        card_paths=card_paths,
        missing_colors=sorted(missing_colors, key=lambda item: int(item)),
    )


def image_bytes(path: Path) -> bytes:
    return path.read_bytes()


def create_sample_source_image(color: tuple[int, int, int] = (220, 70, 70), size: tuple[int, int] = (640, 160)) -> bytes:
    image = Image.new("RGBA", size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 25, size[0] - 20, size[1] - 25), radius=40, fill=color + (255,))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
