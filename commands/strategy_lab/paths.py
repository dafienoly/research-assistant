"""Single path policy for Strategy Lab artifacts and DataHub handoff."""

from pathlib import Path

from factor_lab.datahub_access import SHARED_DATAHUB_ROOT


ROOT = Path(__file__).resolve().parents[2]
STRATEGIES = ROOT / "strategies"
OUTPUTS = ROOT / "research_outputs"
PERFORMANCE = ROOT / "performance"
INCOMING = SHARED_DATAHUB_ROOT / "incoming_from_hermes"
