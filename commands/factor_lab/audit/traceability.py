"""
Traceability Mapping — agent 产出的需求→代码映射文件处理

格式 (agent_tasks/traceability/latest_mapping.json):
```json
{
  "requirements": [
    {
      "id": "R1",
      "title": "fetch real-time price from Tencent API",
      "code_locations": [
        {"file": "commands/factor_lab/market/tencent.py",
         "function": "fetch_realtime_price",
         "line": 42}
      ],
      "expected_keywords": ["qt.gtimg.cn", "requests.get"],
      "behavior": "HTTP GET → Tencent stock API → parse JSON response",
      "verified": false
    }
  ]
}
```
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field


TRACE_DIR = Path.home() / ".hermes" / "research-assistant" / "agent_tasks" / "traceability"
MAPPING_FILE = TRACE_DIR / "latest_mapping.json"


@dataclass
class CodeLocation:
    file: str
    function: str = ""
    line: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "CodeLocation":
        return cls(file=d.get("file", ""), function=d.get("function", ""), line=d.get("line", 0))

    def to_dict(self) -> dict:
        return {"file": self.file, "function": self.function, "line": self.line}


@dataclass
class Requirement:
    id: str = ""
    title: str = ""
    description: str = ""
    code_locations: list[CodeLocation] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    behavior: str = ""
    verified: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Requirement":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", d.get("description", "")),
            description=d.get("behavior", d.get("description", "")),
            code_locations=[CodeLocation.from_dict(loc) for loc in d.get("code_locations", [])],
            expected_keywords=d.get("expected_keywords", []),
            behavior=d.get("behavior", ""),
            verified=d.get("verified", False),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "code_locations": [loc.to_dict() for loc in self.code_locations],
            "expected_keywords": self.expected_keywords,
            "behavior": self.behavior,
            "verified": self.verified,
        }


@dataclass
class TraceabilityMapping:
    requirements: list[Requirement] = field(default_factory=list)
    source: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "TraceabilityMapping":
        return cls(
            requirements=[Requirement.from_dict(r) for r in d.get("requirements", [])],
            source=d.get("source", ""),
        )

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["TraceabilityMapping"]:
        fp = path or MAPPING_FILE
        if not fp.is_file():
            return None
        try:
            data = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, Exception):
            return None

    def to_dict(self) -> dict:
        return {
            "requirements": [r.to_dict() for r in self.requirements],
            "source": self.source,
        }

    def save(self, path: Optional[Path] = None):
        fp = path or MAPPING_FILE
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
