"""Alpha Registry V3.0 — 注册表 + 文件系统管理"""
import os, json, csv, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
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
        spec.alpha_id = f"alpha_{datetime.now(CST).strftime('%Y%m%d_%H%M%S%f')}"

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


# ─── V3.2.5 — AlphaRegistry 类 + 验证结果回填 ──────────────────────


class AlphaRegistry:
    """文件系统 Alpha 注册表（类封装，兼容现有模块级函数）"""

    def __init__(self, root: Optional[str | Path] = None):
        self.root = Path(root) if root else REGISTRY_ROOT

    # ── 内部辅助 ──────────────────────────────────────

    def _get_alpha_dir(self, alpha_id: str) -> Path:
        return self.root / alpha_id

    def _load_index(self) -> list:
        idx_path = self.root / "registry_index.json"
        if idx_path.exists():
            return json.loads(idx_path.read_text())
        return []

    def _save_index(self, index: list):
        (self.root / "registry_index.json").write_text(
            json.dumps(index, indent=2, ensure_ascii=False)
        )

    def _find_alpha_by_name(self, name: str) -> str:
        """通过因子名查找 Alpha ID"""
        index = self._load_index()
        for entry in index:
            if entry.get("name") == name:
                return entry.get("alpha_id", "")
        # 回退：读每个 spec 的 name 字段
        for entry in index:
            aid = entry.get("alpha_id", "")
            spec_path = self._get_alpha_dir(aid) / "alpha_spec.json"
            if spec_path.exists():
                try:
                    spec = json.loads(spec_path.read_text())
                    if spec.get("name") == name:
                        return aid
                except (json.JSONDecodeError, OSError):
                    continue
        return ""

    def load_index(self) -> dict:
        """返回 {alpha_id: entry, ...} 格式索引"""
        raw = self._load_index()
        return {e.get("alpha_id", ""): e for e in raw if e.get("alpha_id")}

    # ── 核心：从验证结果回填 Alpha 元数据 ──────────────────

    def update_alpha_from_validation(self, alpha_id: str, validation_data: dict) -> dict:
        """从因子验证结果更新 Alpha 元数据

        Args:
            alpha_id: Alpha ID
            validation_data: 验证结果 dict（含 ic_analysis, scoring, anti_overfit 等）

        更新 spec.json 中的 ic_mean_history, peer_benchmark_result 等字段。
        """
        alpha_dir = self._get_alpha_dir(alpha_id)
        spec_path = alpha_dir / "alpha_spec.json"
        if not spec_path.exists():
            return {"error": f"Alpha {alpha_id} 不存在"}

        with open(spec_path) as f:
            spec = json.load(f)

        now = datetime.now(CST)
        today = now.strftime("%Y-%m-%d")

        updates = {}

        # 1) IC 历史
        if "ic_analysis" in validation_data:
            ic = validation_data["ic_analysis"]
            new_record = {
                "date": today,
                "ic_mean": ic.get("ic_mean"),
                "ic_ir": ic.get("ic_ir"),
                "pos_ratio": ic.get("pos_ratio"),
            }
            history = spec.get("ic_mean_history", [])
            # 避免同一天重复写入
            if not history or history[-1].get("date") != today:
                history.append(new_record)
            updates["ic_mean_history"] = history
            updates["last_validated"] = now.isoformat()

        # 2) 评分
        if "scoring" in validation_data:
            score_data = validation_data["scoring"]
            updates["overall_score"] = score_data.get("overall_score")
            updates["grade"] = score_data.get("grade")

        # 3) 同行基准对比
        if "anti_overfit" in validation_data:
            ao = validation_data["anti_overfit"]
            if "peer_benchmark" in ao:
                updates["peer_benchmark_result"] = ao["peer_benchmark"]

        # 4) 基准比较
        if "benchmark_comparison" in validation_data:
            updates["benchmark_comparison"] = validation_data["benchmark_comparison"]

        # 5) Audit log
        audit_entry = {
            "date": today,
            "action": "validation_backfill",
            "source": validation_data.get("factor_name", ""),
            "fields": list(updates.keys()),
        }
        audit_log = spec.get("audit_log", [])
        audit_log.append(audit_entry)
        updates["audit_log"] = audit_log

        spec.update(updates)
        spec["updated_at"] = now.isoformat()

        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2, ensure_ascii=False)

        return {"updated": True, "fields": list(updates.keys())}

    def batch_update_from_validation_dir(self, validation_dir: str) -> list[dict]:
        """从验证结果目录批量更新 Alpha 元数据

        Args:
            validation_dir: 如 research_outputs/factor_validation/

        遍历所有子目录中的 report.json，匹配 alpha name 并更新。
        """
        results = []
        val_path = Path(validation_dir)
        if not val_path.exists():
            return [{"error": f"目录不存在: {validation_dir}"}]

        for report_path in sorted(val_path.glob("*/report.json")):
            factor_name = report_path.parent.name
            try:
                with open(report_path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                results.append({"factor": factor_name, "error": str(e)})
                continue

            alpha_id = self._find_alpha_by_name(factor_name)
            if not alpha_id:
                results.append({
                    "factor": factor_name,
                    "updated": False,
                    "error": "未在 Alpha Registry 中找到对应因子",
                })
                continue

            result = self.update_alpha_from_validation(alpha_id, data)
            result["factor"] = factor_name
            result["alpha_id"] = alpha_id
            results.append(result)

        return results
