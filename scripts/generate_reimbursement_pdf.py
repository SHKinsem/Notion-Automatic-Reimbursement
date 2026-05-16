from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

try:
    from PIL import Image, ImageOps
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except ImportError as exc:  # pragma: no cover - exercised by users without dependencies
    raise SystemExit(
        "Missing PDF dependencies. Install them with:\n"
        "  python -m pip install reportlab pillow"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_OUTPUT_DIR = ROOT / "output"
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
DATE_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
NOTION_ID_PATTERN = re.compile(r"\s+[0-9a-f]{32}$", re.IGNORECASE)
MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
PDF_IMAGE_DPI = 200
PDF_IMAGE_JPEG_QUALITY = 80


@dataclass
class MarkdownRecord:
    path: Path
    title: str
    properties: dict[str, str]
    images: list[Path]


@dataclass
class ReimbursementItem:
    item_id: int
    row: dict[str, str]
    markdown: MarkdownRecord | None
    missing_markdown: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a reimbursement Markdown summary and one-item-per-page PDF."
    )
    parser.add_argument("--csv", type=Path, default=None, help="CSV exported from Notion.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--pdf-output", type=Path, default=None)
    return parser.parse_args()


def choose_csv(data_dir: Path) -> Path:
    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    preferred = [path for path in csv_files if not path.stem.endswith("_all")]
    return preferred[0] if preferred else csv_files[0]


def parse_notion_date(value: str) -> date:
    match = DATE_PATTERN.search(value or "")
    if not match:
        return date.max
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in value if character.isalnum())


def normalize_money(value: str) -> str:
    return re.sub(r"[^0-9.]", "", value or "")


def money_number(value: str) -> str:
    match = re.search(r"[0-9][0-9,]*(?:\.\d+)?", value or "")
    return match.group(0) if match else (value or "").strip()


def original_currency_amount(row: dict[str, str]) -> str:
    currency = (row.get("货币") or "").strip()
    amount = money_number(row.get("金额", ""))
    if currency and amount:
        return f"{currency} {amount}"
    return row.get("金额", "") or row.get("金额（港币）", "") or "-"


def english_date(value: str) -> str:
    parsed_date = parse_notion_date(value)
    if parsed_date == date.max:
        return value or "-"
    return f"{MONTH_NAMES[parsed_date.month - 1]} {parsed_date.day}, {parsed_date.year}"


def month_name(value: str) -> str:
    parsed_date = parse_notion_date(value)
    if parsed_date == date.max:
        return "Undated"
    return MONTH_NAMES[parsed_date.month - 1]


def safe_path_part(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value or "").strip("_")
    return value or fallback


def read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    return sorted(rows, key=lambda row: parse_notion_date(row.get("报销日期", "")))


def fallback_title_from_filename(path: Path) -> str:
    return NOTION_ID_PATTERN.sub("", path.stem).strip()


def parse_markdown(path: Path) -> MarkdownRecord:
    text = path.read_text(encoding="utf-8-sig")
    title = fallback_title_from_filename(path)
    properties: dict[str, str] = {}

    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("!["):
            continue
        match = re.match(r"^([^:：]+)[:：]\s*(.*)$", line)
        if match:
            properties[match.group(1).strip()] = match.group(2).strip()

    images = [resolve_image_path(path.parent, raw_path) for raw_path in IMAGE_PATTERN.findall(text)]
    return MarkdownRecord(path=path, title=title, properties=properties, images=images)


def resolve_image_path(base_dir: Path, raw_path: str) -> Path:
    raw_path = raw_path.strip().strip("<>")
    parsed = urlparse(raw_path)
    if parsed.scheme and parsed.scheme != "file":
        return Path(raw_path)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    return (base_dir / unquote(raw_path)).resolve()


def load_markdown_records(data_dir: Path) -> list[MarkdownRecord]:
    return [parse_markdown(path) for path in sorted(data_dir.glob("*.md"))]


def match_markdown(row: dict[str, str], records: Iterable[MarkdownRecord], used_paths: set[Path]) -> MarkdownRecord | None:
    project_name = row.get("报销项目", "")
    normalized_project_name = normalize_text(project_name)
    best_record: MarkdownRecord | None = None
    best_score = -1

    for record in records:
        if record.path in used_paths:
            continue
        normalized_title = normalize_text(record.title)
        score = 0
        if normalized_title == normalized_project_name:
            score += 8
        elif normalized_project_name and normalized_project_name in normalized_title:
            score += 4
        elif normalized_title and normalized_title in normalized_project_name:
            score += 3

        if record.properties.get("报销日期") == row.get("报销日期"):
            score += 3
        if normalize_money(record.properties.get("金额", "")) == normalize_money(row.get("金额", "")):
            score += 2
        if normalize_money(record.properties.get("金额（港币）", "")) == normalize_money(row.get("金额（港币）", "")):
            score += 2
        if record.properties.get("付款人") == row.get("付款人"):
            score += 1
        if record.properties.get("下单人") == row.get("下单人"):
            score += 1

        if score > best_score:
            best_score = score
            best_record = record

    if best_score < 5:
        return None
    used_paths.add(best_record.path)
    return best_record


def build_items(rows: list[dict[str, str]], records: list[MarkdownRecord]) -> list[ReimbursementItem]:
    used_paths: set[Path] = set()
    items: list[ReimbursementItem] = []
    for item_id, row in enumerate(rows, start=1):
        markdown = match_markdown(row, records, used_paths)
        items.append(ReimbursementItem(item_id=item_id, row=row, markdown=markdown, missing_markdown=markdown is None))
    return items


def markdown_image_path(markdown_output: Path, image_path: Path) -> str:
    if not image_path.is_absolute():
        return image_path.as_posix()
    return Path(os.path.relpath(image_path, markdown_output.parent)).as_posix()


def write_intermediate_markdown(items: list[ReimbursementItem], markdown_output: Path, csv_path: Path) -> None:
    lines = [
        "# Reimbursement PDF Source",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Items: {len(items)}",
        "",
    ]

    for index, item in enumerate(items, start=1):
        row = item.row
        lines.extend(
            [
                '<div style="page-break-after: always;"></div>' if index > 1 else "",
                f"## ID {item.item_id}. {row.get('报销项目', 'Untitled')}",
                "",
                "| Field | Value |",
                "| --- | --- |",
            ]
        )
        lines.append(f"| Date | {english_date(row.get('报销日期', ''))} |")
        lines.append(f"| Amount | {original_currency_amount(row)} |")
        lines.append("")

        if item.markdown:
            if item.markdown.images:
                for image_index, image_path in enumerate(item.markdown.images, start=1):
                    image_reference = markdown_image_path(markdown_output, image_path)
                    lines.append(f"![Screenshot {image_index}]({image_reference})")
                    lines.append("")
            else:
                lines.append("> No screenshots found in the matched Markdown file.")
                lines.append("")
        else:
            lines.append("> No matching Markdown file found.")
            lines.append("")

    markdown_output.write_text("\n".join(line for line in lines if line is not None), encoding="utf-8")


def register_pdf_font() -> str:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for font_path in candidates:
        if not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJKFont", str(font_path)))
            return "CJKFont"
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def draw_wrapped_text(pdf: canvas.Canvas, text: str, x: float, y: float, max_width: float, font_name: str, font_size: float, leading: float) -> float:
    text = str(text or "")
    line = ""
    pdf.setFont(font_name, font_size)
    for character in text:
        next_line = line + character
        if pdf.stringWidth(next_line, font_name, font_size) <= max_width:
            line = next_line
            continue
        pdf.drawString(x, y, line)
        y -= leading
        line = character
    if line:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def draw_metadata(pdf: canvas.Canvas, item: ReimbursementItem, x: float, y: float, width: float, font_name: str) -> float:
    row = item.row
    metadata = [
        ("Date", english_date(row.get("报销日期", ""))),
        ("Amount", original_currency_amount(row)),
    ]

    column_width = width / 2
    card_height = 19 * mm
    pdf.setStrokeColor(colors.HexColor("#D8DEE9"))
    pdf.setFillColor(colors.HexColor("#F7F9FB"))
    pdf.roundRect(x, y - card_height, width, card_height, 4, fill=1, stroke=1)

    for index, (label, value) in enumerate(metadata):
        item_x = x + index * column_width + 5 * mm
        item_y = y - 12 * mm
        pdf.setFillColor(colors.HexColor("#5B6573"))
        pdf.setFont(font_name, 8)
        pdf.drawString(item_x, item_y + 5.5 * mm, label)
        pdf.setFillColor(colors.HexColor("#101828"))
        pdf.setFont(font_name, 14)
        pdf.drawString(item_x, item_y, value or "-")

    return y - card_height - 7 * mm


def draw_image_in_box(pdf: canvas.Canvas, image_path: Path, x: float, y: float, width: float, height: float, font_name: str) -> None:
    pdf.setStrokeColor(colors.HexColor("#D0D5DD"))
    pdf.setFillColor(colors.white)
    pdf.roundRect(x, y, width, height, 4, fill=1, stroke=1)

    if not image_path.exists():
        pdf.setFillColor(colors.HexColor("#667085"))
        draw_wrapped_text(pdf, f"Missing image: {image_path}", x + 8 * mm, y + height / 2, width - 16 * mm, font_name, 9, 11)
        return

    padding = 3 * mm
    available_width = width - 2 * padding
    available_height = height - 2 * padding

    try:
        with Image.open(image_path) as source_image:
            image = ImageOps.exif_transpose(source_image)
            image.load()

        image_width, image_height = image.size
        target_width_px = max(1, round(available_width / 72 * PDF_IMAGE_DPI))
        target_height_px = max(1, round(available_height / 72 * PDF_IMAGE_DPI))
        resize_scale = min(target_width_px / image_width, target_height_px / image_height, 1.0)
        if resize_scale < 1.0:
            resized_size = (
                max(1, round(image_width * resize_scale)),
                max(1, round(image_height * resize_scale)),
            )
            image = image.resize(resized_size, Image.Resampling.LANCZOS)
            image_width, image_height = image.size

        has_alpha = "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)
        image_buffer = io.BytesIO()
        if has_alpha:
            image.save(image_buffer, format="PNG", optimize=True)
        else:
            image.convert("RGB").save(
                image_buffer,
                format="JPEG",
                quality=PDF_IMAGE_JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
        image_buffer.seek(0)
        image_reader = ImageReader(image_buffer)
    except Exception as exc:
        pdf.setFillColor(colors.HexColor("#667085"))
        draw_wrapped_text(pdf, f"Cannot read image: {image_path.name} ({exc})", x + 8 * mm, y + height / 2, width - 16 * mm, font_name, 9, 11)
        return

    scale = min(available_width / image_width, available_height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    draw_x = x + (width - draw_width) / 2
    draw_y = y + (height - draw_height) / 2
    pdf.drawImage(image_reader, draw_x, draw_y, draw_width, draw_height, preserveAspectRatio=True, mask="auto")


def draw_placeholders(pdf: canvas.Canvas, x: float, y: float, width: float, height: float, font_name: str, message: str) -> None:
    pdf.setStrokeColor(colors.HexColor("#D0D5DD"))
    pdf.setFillColor(colors.HexColor("#F8FAFC"))
    pdf.roundRect(x, y, width, height, 4, fill=1, stroke=1)
    pdf.setFillColor(colors.HexColor("#667085"))
    pdf.setFont(font_name, 11)
    draw_wrapped_text(pdf, message, x + 10 * mm, y + height - 18 * mm, width - 20 * mm, font_name, 11, 14)


def image_boxes(x: float, y: float, width: float, height: float, image_count: int) -> list[tuple[float, float, float, float]]:
    gap = 5 * mm
    if image_count <= 1:
        return [(x, y, width, height)]
    if image_count == 2:
        box_width = (width - gap) / 2
        return [(x, y, box_width, height), (x + box_width + gap, y, box_width, height)]

    columns = 2
    rows = (image_count + 1) // 2
    box_width = (width - gap) / columns
    box_height = (height - gap * (rows - 1)) / rows
    boxes = []
    for index in range(image_count):
        row_number = index // columns
        column_number = index % columns
        box_x = x + column_number * (box_width + gap)
        box_y = y + (rows - row_number - 1) * (box_height + gap)
        boxes.append((box_x, box_y, box_width, box_height))
    return boxes


def write_pdf(items: list[ReimbursementItem], pdf_output: Path) -> None:
    pdf_output.parent.mkdir(parents=True, exist_ok=True)
    font_name = register_pdf_font()
    pdf = canvas.Canvas(str(pdf_output), pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    margin = 14 * mm

    for item in items:
        title = item.row.get("报销项目") or "Untitled"
        top = page_height - margin

        pdf.setFillColor(colors.HexColor("#0F172A"))
        pdf.setFont(font_name, 18)
        title_bottom = draw_wrapped_text(pdf, f"ID {item.item_id}. {title}", margin, top, page_width - 2 * margin, font_name, 18, 21)

        metadata_y = min(top - 18 * mm, title_bottom - 4 * mm)
        after_metadata_y = draw_metadata(pdf, item, margin, metadata_y, page_width - 2 * margin, font_name)

        image_area_top = after_metadata_y
        image_area_bottom = margin
        image_area_height = max(40 * mm, image_area_top - image_area_bottom)

        images = item.markdown.images if item.markdown else []
        if images:
            boxes = image_boxes(margin, image_area_bottom, page_width - 2 * margin, image_area_height, len(images))
            for image_path, box in zip(images, boxes):
                draw_image_in_box(pdf, image_path, *box, font_name)
        else:
            message = "No screenshots found in the matched Markdown file." if item.markdown else "No matching Markdown file found."
            draw_placeholders(pdf, margin, image_area_bottom, page_width - 2 * margin, image_area_height, font_name, message)

        pdf.showPage()

    pdf.save()


def write_grouped_pdfs(items: list[ReimbursementItem], output_dir: Path) -> list[Path]:
    grouped_items: dict[tuple[str, str], list[ReimbursementItem]] = defaultdict(list)
    for item in items:
        currency = safe_path_part(item.row.get("货币", ""), "UNKNOWN")
        month = month_name(item.row.get("报销日期", ""))
        grouped_items[(currency, month)].append(item)

    pdf_outputs: list[Path] = []
    for (currency, month), group_items in grouped_items.items():
        pdf_output = output_dir / currency / f"{currency}_{month}.pdf"
        write_pdf(group_items, pdf_output)
        pdf_outputs.append(pdf_output)
    return pdf_outputs


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = (args.csv or choose_csv(data_dir)).resolve()
    markdown_output = (args.markdown_output or output_dir / "reimbursement_report.md").resolve()
    pdf_output = args.pdf_output.resolve() if args.pdf_output else None

    rows = read_csv_rows(csv_path)
    records = load_markdown_records(data_dir)
    items = build_items(rows, records)

    write_intermediate_markdown(items, markdown_output, csv_path)
    if pdf_output:
        write_pdf(items, pdf_output)
        pdf_outputs = [pdf_output]
    else:
        pdf_outputs = write_grouped_pdfs(items, output_dir)

    missing_markdown_count = sum(1 for item in items if item.missing_markdown)
    image_count = sum(len(item.markdown.images) for item in items if item.markdown)
    print(f"CSV: {csv_path}")
    print(f"Items: {len(items)}")
    print(f"Matched Markdown files: {len(items) - missing_markdown_count}/{len(items)}")
    print(f"Referenced screenshots: {image_count}")
    print(f"Markdown: {markdown_output}")
    print("PDFs:")
    for output in pdf_outputs:
        print(f"  {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())