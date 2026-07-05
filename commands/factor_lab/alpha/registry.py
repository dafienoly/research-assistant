"""Alpha Registry V3.0 — 注册表 + 文件系统管理"""
import os, json, csv, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.lifecycle import AlphaLifecycle
from factor_lab.core.audit import AuditTrail
from factor_lab.core.artifact import ArtifactManifest

CST = timezone(timedelta(hours=8))
REGISTRY_ROOT = Path("/mnt/d/HermesData/alpha_registry")
REGISTRY_INDEX = REGISTRY_ROOT / "registry_index.json"


def _ensure_registry():
    REGISTRY_ROOT.mkdir(parents=True, exist_ok=True)


def _load_index():
    _ensure_registry()
    if REGISTRY_INDEX.exists():
        return json.loads(REGISTRY_INDEX.read_text())
    return []


def _save_index(index):
    REGISTRY_INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False))


def register_alpha(spec: AlphaSpec) -> dict:
    """注册 Alpha，创建文件系统目录"""
    _ensure_registry()
    spec.created_at = datetime.now(CST).isoformat()
    spec.updated_at = spec.created_at
    if not spec.alpha_id:
        spec.alpha_id = f"alpha_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"

    alpha_dir = REGISTRY_ROOT / spec.alpha_id
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / "versions").mkdir(exist_ok=True)
    (alpha_dir / "artifacts").mkdir(exist_ok=True)
    (alpha_dir / "evaluation").mkdir(exist_ok=True)
    (alpha_dir / "promotion_history").mkdir(exist_ok=True)

    # Write spec
    spec_dict = {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
    (alpha_dir / "alpha_spec.json").write_text(json.dumps(spec_dict, indent=2, ensure_ascii=False))

    # Manifest
    manifest = ArtifactManifest(str(alpha_dir), run_id=spec.alpha_id)
    manifest.add_file("alpha_spec.json", category="spec")
    manifest.write()

    # Audit
    audit = AuditTrail(str(alpha_dir))
    audit.log("alpha_register", run_id=spec.alpha_id, module="alpha_registry",
              status="registered", message=f"Alpha {spec.name} registered",
              safety={"enabled": False, "paper_enabled": False, "live_enabled": False})

    # Index
    index = _load_index()
    index.append({"alpha_id": spec.alpha_id, "name": spec.name, "status": spec.status,
                   "version": spec.version, "created_at": spec.created_at})
    _save_index(index)

    return {"alpha_id": spec.alpha_id, "alpha_dir": str(alpha_dir), "status": "registered"}


def list_alpha() -> list:
    return _load_index()


def get_alpha(alpha_id: str) -> dict:
    alpha_dir = REGISTRY_ROOT / alpha_id
    spec_path = alpha_dir / "alpha_spec.json"
    if not spec_path.exists():
        return {"error": f"Alpha {alpha_id} not found"}
    return json.loads(spec_path.read_text())


def update_alpha_status(alpha_id: str, new_status: str, target_enabled: bool = None) -> dict:
    alpha_dir = REGISTRY_ROOT / alpha_id
    spec_path = alpha_dir / "alpha_spec.json"
    if not spec_path.exists():
        return {"error": "not found"}
    spec = json.loads(spec_path.read_text())
    lifecycle = AlphaLifecycle(str(alpha_dir))
    transition = lifecycle.transition(spec["status"], new_status)
    if not transition.get("success"):
        return transition
    spec["status"] = new_status
    spec["updated_at"] = datetime.now(CST).isoformat()
    if target_enabled is not None:
        spec["enabled"] = target_enabled
        if not target_enabled:
            spec["paper_enabled"] = False
            spec["live_enabled"] = False
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    audit = AuditTrail(str(alpha_dir))
    audit.log("alpha_status_update", run_id=alpha_id, status=new_status,
              message=f"Status: {spec.get('status')} -> {new_status}")
    # Update index
    index = _load_index()
    for i, entry in enumerate(index):
        if entry["alpha_id"] == alpha_id:
            index[i]["status"] = new_status
    _save_index(index)
    return {"alpha_id": alpha_id, "status": new_status, "success": True}


def retire_alpha(alpha_id: str) -> dict:
    return update_alpha_status(alpha_id, "retired")


def export_registry(output_path: str):
    index = _load_index()
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        if index:
            w = csv.DictWriter(f, fieldnames=index[0].keys())
            w.writeheader()
            w.writerows(index)
