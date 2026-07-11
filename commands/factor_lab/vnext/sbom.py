"""Generate a CycloneDX 1.5 SBOM across active VNext environments."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COLLECT_SCRIPT = r"""
import json
from importlib.metadata import distributions
rows = []
for dist in distributions():
    meta = dist.metadata
    name = meta.get('Name')
    if not name:
        continue
    rows.append({
        'name': name,
        'version': dist.version,
        'license': meta.get('License-Expression') or meta.get('License') or 'NOASSERTION',
    })
print(json.dumps(sorted(rows, key=lambda item: item['name'].lower())))
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class CycloneDXGenerator:
    def generate(self, project_root: str | Path, *, output_path: str | Path) -> dict[str, Any]:
        root = Path(project_root).resolve()
        environments = {
            "hermes-core": root / ".venv_quant" / "bin" / "python",
            "hermes-research-vectorbt": root / ".venv_vectorbt" / "bin" / "python",
        }
        components: list[dict[str, Any]] = []
        for environment, interpreter in environments.items():
            for package in self._collect(interpreter):
                license_name = str(package["license"]).strip() or "NOASSERTION"
                if package["name"].lower() == "vectorbt":
                    license_name = "Apache-2.0-WITH-Commons-Clause-1.0"
                bom_ref = f"pkg:pypi/{package['name'].lower()}@{package['version']}?environment={environment}"
                components.append(
                    {
                        "bom-ref": bom_ref,
                        "type": "library",
                        "name": package["name"],
                        "version": package["version"],
                        "purl": f"pkg:pypi/{package['name'].lower()}@{package['version']}",
                        "licenses": [{"license": {"name": license_name[:4096]}}],
                        "properties": [{"name": "hermes:environment", "value": environment}],
                    }
                )
        lock_files = [
            root / "requirements" / "core.lock",
            root / "requirements" / "vectorbt.lock",
            root / "requirements" / "execution-vnpy.lock",
            root / "requirements" / "openbb-sidecar.lock",
            root / "requirements" / "finrl-lab.lock",
            root / "commands" / "frontend" / "package-lock.json",
        ]
        document = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": "urn:uuid:3bc3b767-ea9b-5ccb-a025-7f3f9016f704",
            "version": 1,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tools": {"components": [{"type": "application", "name": "Hermes CycloneDXGenerator", "version": "1.0"}]},
                "component": {
                    "type": "application",
                    "bom-ref": "hermes-vnext",
                    "name": "Hermes VNext",
                    "version": "2026.07.11",
                },
                "properties": [
                    {"name": f"hermes:lock:{path.relative_to(root)}", "value": _sha256(path)}
                    for path in lock_files
                ],
            },
            "components": sorted(components, key=lambda item: item["bom-ref"]),
            "dependencies": [{"ref": "hermes-vnext", "dependsOn": sorted(item["bom-ref"] for item in components)}],
        }
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(output)
        return {
            "status": "OK",
            "output_path": str(output),
            "components": len(components),
            "environments": sorted(environments),
            "sha256": _sha256(output),
        }

    @staticmethod
    def _collect(interpreter: Path) -> list[dict[str, str]]:
        if not interpreter.exists():
            raise FileNotFoundError(f"active environment interpreter missing: {interpreter}")
        clean_environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        completed = subprocess.run(
            [str(interpreter), "-c", COLLECT_SCRIPT],
            check=True,
            capture_output=True,
            text=True,
            env=clean_environment,
            timeout=60,
        )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, list):
            raise ValueError("SBOM collector output must be a list")
        return payload
