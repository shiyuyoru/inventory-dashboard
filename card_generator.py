from __future__ import annotations

import io
import math
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MODEL_NAME = "birefnet-general"
MODEL_DIR = Path(r"D:\codex\.u2net")
MODEL_PATH = MODEL_DIR / "birefnet-general.onnx"
CANVAS_SIZE = 1000
CARD_SIZE = (CANVAS_SIZE, CANVAS_SIZE)
CARD_BACKGROUND = (255, 255, 255)
TEXT_COLOR = (45, 45, 45)
TEXT_PAD_WIDTH = 3

IMAGE_AREA_X1 = 35
IMAGE_AREA_X2 = 790
LABEL_X = 845
FONT_SIZE = {
    2: 62,
    3: 58,
    4: 54,
    5: 48,
    6: 44,
}
ROW_CENTERS_BY_COUNT = {
    2: [315, 685],
    3: [205, 500, 795],
    4: [145, 380, 620, 855],
    5: [105, 300, 500, 700, 895],
    6: [85, 250, 415, 585, 750, 915],
}
MAX_BOX_BY_COUNT = {
    2: (765, 355),
    3: (765, 285),
    4: (755, 220),
    5: (730, 175),
    6: (700, 135),
}
WHITE_TRIM_THRESHOLD = 246
WHITE_TRIM_PADDING = 10
POSTER_COMPONENT_THRESHOLD = 242
POSTER_EXTRACT_PADDING = 8
SHADOW_AVG_THRESHOLD = 218
SHADOW_CHANNEL_SPREAD = 20
SHADOW_MIN_CHANNEL_THRESHOLD = 150
CORE_MASK_CHANNEL_SPREAD = 18
CORE_MASK_DARK_THRESHOLD = 168
CORE_MASK_DILATE_SIZE = 9
MIN_COMPONENT_PIXELS = 80
LURE_COMPONENT_MIN_ASPECT = 2.2
LURE_COMPONENT_MIN_WIDTH_RATIO = 0.16
ANGLE_TARGET_DEGREES = 8
ANGLE_CORRECTION_THRESHOLD = 9
MAX_AUTO_ROTATION_DEGREES = 26
ANGLE_SAMPLE_SIZE = 220

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
    debug_dir: Path
    zip_path: Path
    card_paths: list[Path]
    missing_colors: list[str]
    raw_paths: dict[str, Path]
    cutout_paths: dict[str, Path]
    warnings: list[str]


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
    debug_dir = run_dir / "debug"
    for directory in [raw_dir, png_dir, cards_dir, debug_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": run_dir,
        "raw_dir": raw_dir,
        "png_dir": png_dir,
        "cards_dir": cards_dir,
        "debug_dir": debug_dir,
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


def save_uploaded_color_bytes(file_name: str, data: bytes, color_code: str, raw_dir: Path) -> Path:
    color = normalize_color_code(color_code)
    if not color:
        raise ValueError(f"Invalid color code: {color_code}")
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".png"
    out_path = raw_dir / f"{color}{suffix}"
    out_path.write_bytes(data)
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


def _expand_bbox(bbox: tuple[int, int, int, int], size: tuple[int, int], padding: int):
    left, top, right, bottom = bbox
    width, height = size
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding),
        min(height, bottom + padding),
    )


def trim_transparent(image: Image.Image, padding: int = 8) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return image

    return image.crop(_expand_bbox(bbox, image.size, padding))


def trim_near_white(image: Image.Image, threshold: int = WHITE_TRIM_THRESHOLD, padding: int = WHITE_TRIM_PADDING) -> Image.Image:
    rgb = image.convert("RGB")
    mask = rgb.point(lambda value: 255 if value < threshold else 0).convert("L")
    bbox = mask.getbbox()
    if bbox is None:
        return image
    return image.crop(_expand_bbox(bbox, image.size, padding))


def _flat_pixels(image: Image.Image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def has_effective_alpha(image: Image.Image) -> bool:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    min_alpha, max_alpha = image.getchannel("A").getextrema()
    return min_alpha < 245 and max_alpha > 10


def lure_core_mask(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    mask = Image.new("L", rgba.size, 0)
    mask_pixels = []
    for r, g, b, a in _flat_pixels(rgba):
        if not a:
            mask_pixels.append(0)
            continue
        channel_spread = max(r, g, b) - min(r, g, b)
        if channel_spread >= CORE_MASK_CHANNEL_SPREAD or min(r, g, b) <= CORE_MASK_DARK_THRESHOLD:
            mask_pixels.append(255)
        else:
            mask_pixels.append(0)
    mask.putdata(mask_pixels)
    return mask


def suppress_soft_shadow(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    protected = lure_core_mask(rgba).filter(ImageFilter.MaxFilter(CORE_MASK_DILATE_SIZE))
    pixels = []
    protected_pixels = list(_flat_pixels(protected))
    for idx, (r, g, b, a) in enumerate(_flat_pixels(rgba)):
        channel_spread = max(r, g, b) - min(r, g, b)
        outside_core = not protected_pixels[idx]
        very_light_gray = (r + g + b) / 3 >= SHADOW_AVG_THRESHOLD and channel_spread <= SHADOW_CHANNEL_SPREAD + 8
        soft_background_gray = min(r, g, b) >= SHADOW_MIN_CHANNEL_THRESHOLD and channel_spread <= SHADOW_CHANNEL_SPREAD
        if a and outside_core and (soft_background_gray or very_light_gray):
            pixels.append((255, 255, 255, a))
        else:
            pixels.append((r, g, b, a))
    out = Image.new("RGBA", rgba.size)
    out.putdata(pixels)
    return out


def trim_to_lure_core(image: Image.Image, padding: int = 14) -> Image.Image:
    mask = lure_core_mask(image)
    bbox = mask.getbbox()
    if bbox is None:
        return image
    return image.crop(_expand_bbox(bbox, image.size, padding))


def _component_bboxes(mask: Image.Image) -> list[tuple[int, int, int, int, int]]:
    width, height = mask.size
    pixels = mask.load()
    visited = bytearray(width * height)
    components = []

    for start_y in range(height):
        for start_x in range(width):
            idx = start_y * width + start_x
            if visited[idx] or not pixels[start_x, start_y]:
                continue

            stack = [(start_x, start_y)]
            visited[idx] = 1
            min_x = max_x = start_x
            min_y = max_y = start_y
            count = 0

            while stack:
                x, y = stack.pop()
                count += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y

                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nx < 0 or nx >= width or ny < 0 or ny >= height:
                        continue
                    n_idx = ny * width + nx
                    if visited[n_idx] or not pixels[nx, ny]:
                        continue
                    visited[n_idx] = 1
                    stack.append((nx, ny))

            if count >= MIN_COMPONENT_PIXELS:
                components.append((min_x, min_y, max_x + 1, max_y + 1, count))

    return components


def extract_lure_from_poster(image: Image.Image) -> Image.Image | None:
    rgb = image.convert("RGB")
    mask = rgb.point(lambda value: 255 if value < POSTER_COMPONENT_THRESHOLD else 0).convert("L")
    scale = min(1.0, 360 / max(mask.size))
    if scale < 1:
        small_mask = mask.resize(
            (max(1, round(mask.width * scale)), max(1, round(mask.height * scale))),
            Image.Resampling.NEAREST,
        )
    else:
        small_mask = mask

    components = _component_bboxes(small_mask)
    candidates = []
    for left, top, right, bottom, count in components:
        width = right - left
        height = bottom - top
        aspect = width / max(height, 1)
        width_ratio = width / max(small_mask.width, 1)
        if aspect < LURE_COMPONENT_MIN_ASPECT or width_ratio < LURE_COMPONENT_MIN_WIDTH_RATIO:
            continue
        if height < 8:
            continue
        center_y = (top + bottom) / 2 / max(small_mask.height, 1)
        center_penalty = abs(center_y - 0.55) * 0.25
        score = count * aspect * (1 + width_ratio) * (1 - center_penalty)
        candidates.append((score, left, top, right, bottom))

    if not candidates:
        return None

    _, left, top, right, bottom = max(candidates, key=lambda item: item[0])
    if scale < 1:
        left = math.floor(left / scale)
        top = math.floor(top / scale)
        right = math.ceil(right / scale)
        bottom = math.ceil(bottom / scale)

    crop = image.crop(_expand_bbox((left, top, right, bottom), image.size, POSTER_EXTRACT_PADDING))
    crop = trim_to_lure_core(crop)
    crop = suppress_soft_shadow(crop)
    return trim_near_white(crop, padding=WHITE_TRIM_PADDING)


def filter_cutout_subject(cutout: Image.Image) -> tuple[Image.Image, Image.Image, bool]:
    cutout = cutout.convert("RGBA")
    alpha_mask = cutout.getchannel("A").point(lambda value: 255 if value > 12 else 0)
    components = _component_bboxes(alpha_mask)
    image_area = max(cutout.width * cutout.height, 1)
    candidates = []

    for left, top, right, bottom, area in components:
        width = right - left
        height = bottom - top
        if area < max(120, image_area * 0.001):
            continue
        aspect = width / max(height, 1)
        width_ratio = width / max(cutout.width, 1)
        center_x = (left + right) / 2 / max(cutout.width, 1)
        center_y = (top + bottom) / 2 / max(cutout.height, 1)
        if aspect < 1.8 or width_ratio < 0.12:
            continue
        if center_y < 0.06 or center_x < 0.04 or center_x > 0.96:
            continue
        score = area * aspect * (1 + width_ratio)
        candidates.append((score, left, top, right, bottom, area, aspect))

    if not candidates:
        return trim_transparent(cutout), alpha_mask, True

    candidates.sort(reverse=True)
    _, left, top, right, bottom, best_area, best_aspect = candidates[0]
    selected_bbox = _expand_bbox((left, top, right, bottom), cutout.size, 28)
    selected_mask = Image.new("L", cutout.size, 0)
    draw = ImageDraw.Draw(selected_mask)

    uncertain = best_aspect < 2.2 or len(candidates) > 5
    for _, c_left, c_top, c_right, c_bottom, area, aspect in candidates:
        expanded_component = _expand_bbox((c_left, c_top, c_right, c_bottom), cutout.size, 8)
        overlaps = not (
            expanded_component[2] < selected_bbox[0]
            or expanded_component[0] > selected_bbox[2]
            or expanded_component[3] < selected_bbox[1]
            or expanded_component[1] > selected_bbox[3]
        )
        if overlaps or (area >= best_area * 0.12 and aspect >= 2.0):
            draw.rectangle((c_left, c_top, c_right, c_bottom), fill=255)

    filtered = cutout.copy()
    filtered.putalpha(Image.composite(alpha_mask, Image.new("L", cutout.size, 0), selected_mask))
    filtered = trim_transparent(filtered)
    return filtered, selected_mask, uncertain


def remove_background_with_session(image: Image.Image, rembg_session):
    if rembg_session is None:
        raise RuntimeError("birefnet-general 抠图模型未加载。")
    from rembg import remove

    return remove(
        image.convert("RGBA"),
        session=rembg_session,
        post_process_mask=True,
        alpha_matting=False,
    ).convert("RGBA")


def write_mapping_log(run_paths: dict[str, Path], lines: list[str]) -> None:
    log_path = run_paths["debug_dir"] / "mapping.log"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_cutouts(
    raw_paths: dict[str, Path],
    run_paths: dict[str, Path],
    rembg_session,
    progress_callback=None,
) -> tuple[dict[str, Path], list[str]]:
    cutout_paths: dict[str, Path] = {}
    warnings: list[str] = []
    mapping_lines: list[str] = []

    for idx, (color, raw_path) in enumerate(sorted(raw_paths.items(), key=lambda item: int(item[0])), start=1):
        if progress_callback:
            progress_callback(idx, len(raw_paths), f"正在抠图：{color}")

        color_debug_dir = run_paths["debug_dir"] / color
        color_debug_dir.mkdir(parents=True, exist_ok=True)
        out_path = run_paths["png_dir"] / f"{color}.png"
        if out_path.exists() and out_path.stat().st_mtime >= raw_path.stat().st_mtime:
            cutout_paths[color] = out_path
            mapping_lines.append(f"color {color} -> raw {raw_path} -> reused png {out_path}")
            continue

        original = Image.open(raw_path).convert("RGBA")
        original.save(color_debug_dir / "original.png")

        if has_effective_alpha(original):
            raw_cutout = trim_transparent(original)
            mapping_lines.append(f"color {color} -> raw {raw_path} -> alpha png skipped rembg")
        else:
            raw_cutout = remove_background_with_session(original, rembg_session)
            mapping_lines.append(f"color {color} -> raw {raw_path} -> rembg birefnet-general")

        raw_cutout.save(color_debug_dir / "raw_cutout.png")
        final_cutout, filtered_mask, uncertain = filter_cutout_subject(raw_cutout)
        filtered_mask.save(color_debug_dir / "filtered_mask.png")
        final_cutout.save(color_debug_dir / "final_cutout.png")

        if uncertain:
            mapping_lines.append(f"color {color} -> low confidence subject selection; debug retained")

        alpha_bbox = final_cutout.getchannel("A").getbbox() if final_cutout.mode == "RGBA" else None
        if alpha_bbox is None:
            warnings.append(f"{color} 未识别到有效鱼饵主体，请上传更干净的单色号鱼饵图。")
        else:
            area = (alpha_bbox[2] - alpha_bbox[0]) * (alpha_bbox[3] - alpha_bbox[1])
            if area < max(300, final_cutout.width * final_cutout.height * 0.02):
                warnings.append(f"{color} 鱼饵主体面积过小，请检查上传图或 debug 文件。")

        final_cutout.save(out_path)
        cutout_paths[color] = out_path
        mapping_lines.append(f"color {color} -> cutout {out_path}")

    write_mapping_log(run_paths, mapping_lines)
    return cutout_paths, warnings


def validate_cutout_paths(required_colors: list[str], cutout_paths: dict[str, Path]) -> list[str]:
    errors = []
    for color in required_colors:
        path = cutout_paths.get(color)
        if path is None:
            errors.append(f"色号 {color} 未生成透明 PNG。")
            continue
        if path.suffix.lower() != ".png":
            errors.append(f"色号 {color} 的抠图文件不是 PNG：{path.name}")
            continue
        try:
            with Image.open(path) as image:
                if image.mode != "RGBA":
                    errors.append(f"色号 {color} 的 PNG 不是 RGBA 透明图。")
                elif not has_effective_alpha(image):
                    errors.append(f"色号 {color} 的 PNG 没有有效透明通道。")
        except Exception as exc:
            errors.append(f"色号 {color} 的 PNG 无法读取：{exc}")

    resolved = [str(Path(path).resolve()).lower() for path in cutout_paths.values()]
    if len(resolved) != len(set(resolved)):
        errors.append("存在多个色号指向同一个抠图文件。")
    return errors


def foreground_mask(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema() != (255, 255):
        return alpha.point(lambda value: 255 if value > 12 else 0)
    rgb = rgba.convert("RGB")
    return rgb.point(lambda value: 255 if value < WHITE_TRIM_THRESHOLD else 0).convert("L")


def estimate_lure_angle(image: Image.Image) -> float | None:
    mask = foreground_mask(image)
    bbox = mask.getbbox()
    if bbox is None:
        return None

    mask = mask.crop(bbox)
    scale = min(1.0, ANGLE_SAMPLE_SIZE / max(mask.size))
    if scale < 1:
        mask = mask.resize(
            (max(1, round(mask.width * scale)), max(1, round(mask.height * scale))),
            Image.Resampling.NEAREST,
        )

    flat_data = mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
    pixels = list(flat_data)
    coords = []
    for y in range(mask.height):
        row_start = y * mask.width
        for x, value in enumerate(pixels[row_start:row_start + mask.width]):
            if value:
                coords.append((x, y))

    if len(coords) < 30:
        return None

    mean_x = sum(x for x, _ in coords) / len(coords)
    mean_y = sum(y for _, y in coords) / len(coords)
    cov_xx = sum((x - mean_x) ** 2 for x, _ in coords) / len(coords)
    cov_yy = sum((y - mean_y) ** 2 for _, y in coords) / len(coords)
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in coords) / len(coords)
    if cov_xx == cov_yy and cov_xy == 0:
        return None

    angle_y_down = math.degrees(0.5 * math.atan2(2 * cov_xy, cov_xx - cov_yy))
    if angle_y_down > 90:
        angle_y_down -= 180
    if angle_y_down < -90:
        angle_y_down += 180
    return -angle_y_down


def auto_correct_lure_angle(image: Image.Image) -> Image.Image:
    angle = estimate_lure_angle(image)
    if angle is None:
        return image

    delta = ANGLE_TARGET_DEGREES - angle
    if abs(delta) < ANGLE_CORRECTION_THRESHOLD:
        return image

    rotation = max(-MAX_AUTO_ROTATION_DEGREES, min(MAX_AUTO_ROTATION_DEGREES, delta))
    fill = (255, 255, 255, 0) if image.getchannel("A").getextrema() != (255, 255) else CARD_BACKGROUND + (255,)
    rotated = image.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=fill)
    if fill[-1] == 0:
        return trim_transparent(rotated)
    return trim_near_white(rotated)


def resize_keep_ratio(image: Image.Image, scale: float) -> Image.Image:
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _layout_config(count: int) -> tuple[list[int], int, int, int]:
    safe_count = min(max(count, 2), 6)
    centers = ROW_CENTERS_BY_COUNT.get(safe_count, ROW_CENTERS_BY_COUNT[6])
    max_width, max_height = MAX_BOX_BY_COUNT.get(safe_count, MAX_BOX_BY_COUNT[6])
    max_width = min(max_width, IMAGE_AREA_X2 - IMAGE_AREA_X1)
    font_size = FONT_SIZE.get(safe_count, 46)
    return centers, max_width, max_height, font_size


def layout_rows(count: int) -> list[int]:
    centers, _, _, _ = _layout_config(count)
    return centers[:count]


def load_source_image(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema() == (255, 255):
        return extract_lure_from_poster(image) or trim_near_white(image)
    return trim_transparent(image)


def make_combo_card(
    combo_colors: list[str],
    image_paths: dict[str, Path],
    out_path: Path,
    auto_angle_correction: bool = True,
) -> Path:
    normalized = [normalize_color_code(color) for color in combo_colors]
    normalized = [color for color in normalized if color]
    missing = [color for color in normalized if color not in image_paths]
    if missing:
        raise FileNotFoundError(f"Missing color images: {', '.join(missing)}")

    sorted_combo = sorted(normalized, key=lambda item: int(item))
    images: list[tuple[str, Image.Image]] = []
    for color in sorted_combo:
        image = load_source_image(image_paths[color])
        if auto_angle_correction:
            image = auto_correct_lure_angle(image)
        images.append((color, image))

    if not images:
        raise ValueError("Empty combo colors")

    count = len(images)
    centers = layout_rows(count)
    _, max_box_width, max_box_height, font_size = _layout_config(count)

    canvas = Image.new("RGB", CARD_SIZE, CARD_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    font = load_font(font_size)
    image_area_width = IMAGE_AREA_X2 - IMAGE_AREA_X1

    for (color, image), center_y in zip(images, centers):
        scale = min(max_box_width / image.width, max_box_height / image.height)
        resized = resize_keep_ratio(image, scale)
        x = round(IMAGE_AREA_X1 + (image_area_width - resized.width) / 2)
        y = round(center_y - resized.height / 2)
        canvas.paste(resized.convert("RGB"), (x, y), resized.getchannel("A"))

        label = format_label(color)
        text_box = draw.textbbox((0, 0), label, font=font)
        text_height = text_box[3] - text_box[1]
        draw.text((LABEL_X, round(center_y - text_height / 2) - 2), label, fill=TEXT_COLOR, font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def build_combo_cards(
    combo_df,
    image_paths: dict[str, Path],
    run_paths: dict[str, Path],
    auto_angle_correction: bool = True,
    raw_paths: dict[str, Path] | None = None,
    warnings: list[str] | None = None,
) -> CardGenerationResult:
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
            card_paths.append(make_combo_card(colors, image_paths, out_path, auto_angle_correction=auto_angle_correction))

    zip_path = run_paths["zip_path"]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for card_path in card_paths:
            zf.write(card_path, arcname=card_path.name)

    return CardGenerationResult(
        run_dir=run_paths["run_dir"],
        raw_dir=run_paths["raw_dir"],
        png_dir=run_paths["png_dir"],
        cards_dir=run_paths["cards_dir"],
        debug_dir=run_paths["debug_dir"],
        zip_path=zip_path,
        card_paths=card_paths,
        missing_colors=sorted(missing_colors, key=lambda item: int(item)),
        raw_paths=raw_paths or {},
        cutout_paths=image_paths,
        warnings=warnings or [],
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
