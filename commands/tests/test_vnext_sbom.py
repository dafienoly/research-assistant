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
