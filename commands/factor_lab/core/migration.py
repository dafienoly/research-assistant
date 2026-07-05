"""Migration Compatibility Layer V2.14.3 — 让 V2 模块输出 core 框架产物"""
import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.core.audit import AuditTrail
from factor_lab.core.artifact import ArtifactManifest
from factor_lab.core.config import ConfigManager
from factor_lab.core.gate import GateEngine
from factor_lab.core.report import ReportBuilder

CST = timezone(timedelta(hours=8))


class MigrationCompat:
    """兼容层: 让 V2 模块同时输出旧产物和 core 框架产物"""

    def __init__(self, output_dir: str, run_id: str, module: str, source_run_id: str = ""):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.module = module
        self.source_run_id = source_run_id

        # 初始化 core 框架组件
        self.audit = AuditTrail(str(self.output_dir))
        self.manifest = ArtifactManifest(str(self.output_dir), run_id=run_id, source_run_id=source_run_id)
        self.config_mgr = ConfigManager()
        self.gate = GateEngine()
        self.report = ReportBuilder(str(self.output_dir))

        # 记录旧产物
        self._legacy_files = []

    def legacy(self, path: str):
        """记录旧产物文件"""
        full = self.output_dir / path
        if full.exists():
            self._legacy_files.append(path)
            self.manifest.add_file(path, category="legacy")

    def add_core_output(self, path: str, category: str = "core"):
        """添加 core 框架产物"""
        self.manifest.add_file(path, category=category)

    def finalize(self, verdict: str = "", safety: dict = None):
        """写入 core 框架产物"""
        # manifest.json
        if safety:
            self.manifest.add_file("audit.jsonl", category="audit")
        self.manifest.write()

        # 审计事件
        self.audit.log(
            event="migration_compat",
            run_id=self.run_id,
            source_run_id=self.source_run_id,
            module=self.module,
            status=verdict or "completed",
            safety=safety or {},
        )

    def log_event(self, event: str, status: str = "passed", message: str = "", safety: dict = None):
        self.audit.log(event=event, run_id=self.run_id, source_run_id=self.source_run_id,
                       module=self.module, status=status, message=message, safety=safety)
