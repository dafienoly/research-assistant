"""Data Lineage V5.6 — 数据血缘/Manifest 追踪系统"""
import json, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
MANIFEST_DIR = Path("/mnt/d/HermesData/manifests")
MANIFEST_DIR.mkdir(parents=True, exist_ok=True)


def create_manifest(source_id: str, dataset: str, file_path: str, record_count: int = 0) -> dict:
    """创建数据文件的 manifest"""
    fpath = Path(file_path)
    manifest = {
        "manifest_id": f"mf_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}",
        "source_id": source_id,
        "dataset": dataset,
        "file": str(fpath),
        "record_count": record_count,
        "file_size": fpath.stat().st_size if fpath.exists() else 0,
        "file_hash": hashlib.sha256(fpath.read_bytes()).hexdigest()[:16] if fpath.exists() else "",
        "created_at": datetime.now(CST).isoformat(),
        "lineage": [],
    }
    path = MANIFEST_DIR / f"{manifest['manifest_id']}.json"
    path.write_text(json.dumps(manifest, indent=2))
    return manifest


def get_manifest(manifest_id: str) -> dict:
    path = MANIFEST_DIR / f"{manifest_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"error": "not found"}


def list_manifests(dataset: str = None) -> list:
    manifests = []
    for f in sorted(MANIFEST_DIR.glob("*.json"), reverse=True):
        data = json.loads(f.read_text())
        if dataset and data.get("dataset") != dataset:
            continue
        manifests.append(data)
    return manifests


def link_lineage(child_id: str, parent_id: str):
    """记录数据血缘关系"""
    child = get_manifest(child_id)
    if "error" not in child:
        child.setdefault("lineage", [])
        if parent_id not in child["lineage"]:
            child["lineage"].append(parent_id)
            path = MANIFEST_DIR / f"{child_id}.json"
            path.write_text(json.dumps(child, indent=2))
    parent = get_manifest(parent_id)
    if "error" not in parent:
        parent.setdefault("children", [])
        if child_id not in parent["children"]:
            parent["children"] = parent.get("children", []) + [child_id]
            path = MANIFEST_DIR / f"{parent_id}.json"
            path.write_text(json.dumps(parent, indent=2))
