from __future__ import annotations

import json
from pathlib import Path

from factor_lab.vnext.sbom import CycloneDXGenerator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cyclonedx_sbom_covers_core_and_isolated_vectorbt(tmp_path: Path) -> None:
    output = tmp_path / "sbom.cdx.json"
    result = CycloneDXGenerator().generate(PROJECT_ROOT, output_path=output)
    document = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "OK"
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    vectorbt = [item for item in document["components"] if item["name"].lower() == "vectorbt"]
    assert len(vectorbt) == 1
    assert vectorbt[0]["licenses"][0]["license"]["name"] == "Apache-2.0-WITH-Commons-Clause-1.0"
    assert {prop["value"] for item in document["components"] for prop in item["properties"]} == {
        "hermes-core",
        "hermes-research-vectorbt",
    }
    assert not any(item["name"].lower() in {"vnpy", "openbb", "finrl"} for item in document["components"])


def test_core_hashed_lock_covers_every_exact_pin() -> None:
    plain = [
        line.strip()
        for line in (PROJECT_ROOT / "requirements" / "core.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    hashed = (PROJECT_ROOT / "requirements" / "core.hashed.lock").read_text(encoding="utf-8")
    for pin in plain:
        marker = f"{pin} \\\n"
        assert marker in hashed
        block = hashed.split(marker, 1)[1].split("\n", 1)[0]
        assert "--hash=sha256:" in block
