"""Core Artifact V2.14.2 — 统一 ArtifactManifest"""
import json, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


class ArtifactManifest:
    """产物清单"""
    def __init__(self, output_dir: str, run_id: str = "", source_run_id: str = ""):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.source_run_id = source_run_id
        self.files = []
        self.input_hash = ""
        self.output_hash = ""

    def add_file(self, path: str, category: str = "report"):
        full = self.output_dir / path
        h = hashlib.md5(full.read_bytes()).hexdigest()[:12] if full.exists() else ""
        self.files.append({"path": path, "category": category, "hash": h, "size": full.stat().st_size if full.exists() else 0})

    def add_input(self, path: str):
        full = Path(path)
        if full.exists():
            self.input_hash = hashlib.md5(full.read_bytes()).hexdigest()[:12]

    def write(self):
        self.output_hash = hashlib.md5(json.dumps(self.files, sort_keys=True).encode()).hexdigest()[:12]
        manifest = {
            "run_id": self.run_id,
            "source_run_id": self.source_run_id,
            "generated_at": datetime.now(CST).isoformat(),
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "files": self.files,
        }
        (self.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
