"""Development utility: convert every demo DWG and build a side-by-side report.

Usage:
    .venv/bin/python make_comparison.py --demo ../ODA_Converter/demo \
        --ref ../ODA_Converter/demo-png --out demo-output-qwen

Outputs ours/<name>.png, comparisons/<name>_comparison.png, manifest.csv,
index.html and summary.json (per-file decode statistics for gap analysis).
Only files inside --out are written; existing outputs there are replaced.
"""
import argparse
import csv
import html
import json
from pathlib import Path
import textwrap
import traceback

from PIL import Image, ImageDraw

from dwg2image import dwg_to_png, read_dwg


def _panel(image, box=(1180, 860)):
    image = image.convert('RGB')
    image.thumbnail(box, Image.LANCZOS)
    canvas = Image.new('RGB', box, '#11141a')
    canvas.paste(image, ((box[0] - image.width) // 2, (box[1] - image.height) // 2))
    return canvas


def _text_panel(text, box=(1180, 860)):
    canvas = Image.new('RGB', box, '#1b2029')
    draw = ImageDraw.Draw(canvas)
    y = 24
    for line in textwrap.wrap(text, 90):
        draw.text((24, y), line, fill='#ff9f9f')
        y += 18
        if y > box[1] - 24:
            break
    return canvas


def _label(panel, text):
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, panel.width, 22), fill='#000000')
    draw.text((8, 5), text, fill='#eeeeee')
    return panel


def comparison(reference, ours, error):
    left = _label(_panel(reference), 'REFERENCE (ODA export)')
    if ours is not None:
        right = _label(_panel(ours), 'OURS (independent decoder)')
    else:
        right = _label(_text_panel(error), 'FAILED - reason')
    joined = Image.new('RGB', (left.width + right.width + 12, left.height), '#333333')
    joined.paste(left, (0, 0))
    joined.paste(right, (left.width + 12, 0))
    return joined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', type=Path, required=True)
    parser.add_argument('--ref', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dpi', type=int, default=300)
    args = parser.parse_args()
    (args.out / 'ours').mkdir(parents=True, exist_ok=True)
    (args.out / 'comparisons').mkdir(parents=True, exist_ok=True)

    rows, summary = [], {}
    sources = sorted(args.demo.glob('*.dwg'))
    for index, source in enumerate(sources, 1):
        stem = source.stem
        reference_path = args.ref / f'{stem}.png'
        reference = Image.open(reference_path) if reference_path.exists() else None
        ours_path = args.out / 'ours' / f'{stem}.png'
        record = {'dwg': source.name}
        error = None
        try:
            drawing = read_dwg(source)
            record['object_count'] = drawing.object_count
            record['unsupported_modelspace'] = drawing.unsupported_modelspace
            record['unsupported_blocks'] = {
                f'{handle:X}': types for handle, types in drawing.unsupported_blocks.items()}
        except Exception as exc:
            record['read_error'] = f'{type(exc).__name__}: {exc}'
        try:
            if ours_path.exists():
                ours_path.unlink()
            dwg_to_png(source, ours_path, dpi=args.dpi)
            status = 'converted'
        except Exception as exc:
            status = 'failed'
            error = f'{type(exc).__name__}: {exc}'
            record['export_traceback'] = traceback.format_exc(limit=3)
        record['status'] = status
        record['error'] = error
        summary[stem] = record

        comparison_path = args.out / 'comparisons' / f'{stem}_comparison.png'
        if comparison_path.exists():
            comparison_path.unlink()
        if reference is not None:
            ours = Image.open(ours_path) if status == 'converted' else None
            comparison(reference, ours, error or '').save(comparison_path)
        rows.append({'dwg': source.name,
                     'reference_png': reference_path.name if reference else '',
                     'our_png': f'ours/{stem}.png' if status == 'converted' else '',
                     'comparison_png': f'comparisons/{stem}_comparison.png' if reference else '',
                     'status': status, 'error': error or ''})
        print(f'[{index}/{len(sources)}] {status}: {source.name}'
              + (f' -- {error}' if error else ''), flush=True)

    with (args.out / 'manifest.csv').open('w', newline='', encoding='utf-8-sig') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')

    converted = sum(row['status'] == 'converted' for row in rows)
    body = []
    for row in rows:
        image = (f'<a href="{html.escape(row["comparison_png"])}">'
                 f'<img loading="lazy" src="{html.escape(row["comparison_png"])}" '
                 f'alt="{html.escape(row["dwg"])}"></a>') if row['comparison_png'] else ''
        body.append(f'<tr><td>{html.escape(row["dwg"])}</td><td>{row["status"]}</td>'
                    f'<td>{image}</td><td>{html.escape(row["error"])}</td></tr>')
    page = ("<!doctype html><meta charset='utf-8'><title>dwg2image comparisons (qwen)</title>"
            "<style>body{font:15px system-ui;background:#222831;color:#eee;margin:24px}"
            "table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #555;"
            "vertical-align:top}img{max-width:900px;height:auto}td:first-child{min-width:180px}"
            "td:nth-child(2){min-width:90px}</style>"
            f"<h1>dwg2image independent decoder vs reference PNG</h1>"
            f"<p>DWG: {len(rows)} | converted: {converted} | failed: {len(rows) - converted}. "
            "Failed entries show the reason beside the reference image. "
            "Per-file decode statistics: <a href='summary.json'>summary.json</a>.</p>"
            "<table><thead><tr><th>DWG</th><th>Status</th><th>Side by side</th><th>Error</th>"
            "</tr></thead><tbody>" + ''.join(body) + '</tbody></table>')
    (args.out / 'index.html').write_text(page, encoding='utf-8')
    print(f'DONE: {converted}/{len(rows)} converted -> {args.out}/index.html')


if __name__ == '__main__':
    main()