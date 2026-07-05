"""Core Report V2.14.2 — 统一 ReportBuilder"""
import csv, json
from pathlib import Path


class ReportBuilder:
    def __init__(self, output_dir: str):
        self.out = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.sections = []

    def add_section(self, title: str, content: str):
        self.sections.append({"title": title, "content": content})

    def to_html(self, title: str = "Report") -> str:
        rows = "".join(f"<div class='card'><h2>{s['title']}</h2><p>{s['content']}</p></div>" for s in self.sections)
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body {{font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px;}}
.card {{background:#16213e;border-radius:8px;padding:20px;margin:12px 0;}}
h1 {{color:#00bcd4;}}h2 {{color:#00bcd4;border-bottom:1px solid #333;}}</style></head><body>
<h1>{title}</h1>{rows}</body></html>"""

    def write_html(self, filename: str = "report.html"):
        (self.out / filename).write_text(self.to_html(filename))

    def write_csv(self, filename: str, rows: list):
        if rows:
            with open(self.out / filename, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)

    def write_md(self, filename: str, text: str):
        (self.out / filename).write_text(text, encoding="utf-8")
