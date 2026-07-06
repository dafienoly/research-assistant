"""V4.4 Kill Switch / Risk Sentinel — Incident Event Log

Structured incident event logging for risk events.
Each incident is recorded with timestamp, severity, rule triggered,
source context, and optional recovery tracking.

Incidents are stored as JSON lines (.jsonl) for append-only audit trail.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Incident Record
# ---------------------------------------------------------------------------
@dataclass
class IncidentRecord:
    """A single risk incident record.

    Each incident captures a rule violation or risk event.
    Immutable after creation — status transitions create new records
    with `related_incident_id` links.
    """

    incident_id: str = ""
    rule_name: str = ""
    severity: str = "warning"
    status: str = "open"  # open / acknowledged / resolving / resolved / closed
    message: str = ""
    category: str = "data"
    source: str = "risk_sentinel"
    triggered_at: str = ""
    acknowledged_at: str = ""
    resolved_at: str = ""
    acknowledged_by: str = ""
    resolution: str = ""
    details: dict = field(default_factory=dict)
    related_incident_id: str = ""  # Link to previous related incident
    tags: list = field(default_factory=list)

    def __post_init__(self):
        if not self.triggered_at:
            self.triggered_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def acknowledge(self, by: str = "", notes: str = ""):
        """Mark incident as acknowledged."""
        self.status = "acknowledged"
        self.acknowledged_at = datetime.now(CST).isoformat()
        self.acknowledged_by = by
        if notes:
            self.details["acknowledged_notes"] = notes

    def resolve(self, resolution: str = "", by: str = ""):
        """Mark incident as resolved."""
        self.status = "resolved"
        self.resolved_at = datetime.now(CST).isoformat()
        self.resolution = resolution
        if by:
            self.acknowledged_by = by
        self.details["resolved"] = True

    def close(self):
        """Close a resolved incident."""
        self.status = "closed"

    def reopen(self, reason: str = ""):
        """Re-open a closed incident."""
        self.status = "open"
        self.resolved_at = ""
        self.resolution = ""
        if reason:
            self.details["reopen_reason"] = reason


# ---------------------------------------------------------------------------
# Incident Log
# ---------------------------------------------------------------------------
class IncidentLog:
    """Append-only incident event log.

    Stores incidents as JSONL for audit trail, plus provides in-memory
    access for real-time querying.

    Usage:
        log = IncidentLog(output_dir="/path/to/logs")
        incident = log.record("data_freshness", "critical",
                              "Data stale for 10 minutes")
        log.save()
    """

    def __init__(self, output_dir: str = ""):
        self.incidents: list[IncidentRecord] = []
        self._output_dir = output_dir
        self._incident_counter: int = 0

    def record(self, rule_name: str, severity: str = "warning",
               message: str = "", category: str = "data",
               source: str = "risk_sentinel",
               details: dict = None,
               tags: list = None,
               related_incident_id: str = "") -> IncidentRecord:
        """Record a new incident.

        Args:
            rule_name: Name of the rule that triggered
            severity: info / warning / critical / blocker
            message: Human-readable description
            category: data / account / execution / loss / system
            source: Source component name
            details: Optional structured context
            tags: Optional list of tags
            related_incident_id: Link to related incident

        Returns:
            IncidentRecord
        """
        self._incident_counter += 1
        incident = IncidentRecord(
            incident_id=f"INC_{self._incident_counter:06d}_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}",
            rule_name=rule_name,
            severity=severity,
            message=message,
            category=category,
            source=source,
            triggered_at=datetime.now(CST).isoformat(),
            details=details or {},
            tags=tags or [],
            related_incident_id=related_incident_id,
        )
        self.incidents.append(incident)
        self._auto_save()
        return incident

    def acknowledge(self, incident_id: str, by: str = "",
                    notes: str = "") -> bool:
        """Acknowledge an open incident."""
        incident = self.find(incident_id)
        if incident and incident.status == "open":
            incident.acknowledge(by, notes)
            self._auto_save()
            return True
        return False

    def resolve(self, incident_id: str, resolution: str = "",
                by: str = "") -> bool:
        """Resolve an acknowledged or open incident."""
        incident = self.find(incident_id)
        if incident and incident.status in ("open", "acknowledged", "resolving"):
            incident.resolve(resolution, by)
            self._auto_save()
            return True
        return False

    def close(self, incident_id: str) -> bool:
        """Close a resolved incident."""
        incident = self.find(incident_id)
        if incident and incident.status == "resolved":
            incident.close()
            return True
        return False

    def reopen(self, incident_id: str, reason: str = "") -> bool:
        """Re-open a closed incident."""
        incident = self.find(incident_id)
        if incident and incident.status == "closed":
            incident.reopen(reason)
            self._auto_save()
            return True
        return False

    def find(self, incident_id: str) -> Optional[IncidentRecord]:
        """Find an incident by ID."""
        for inc in self.incidents:
            if inc.incident_id == incident_id:
                return inc
        return None

    def find_by_rule(self, rule_name: str,
                     status: str = "") -> list[IncidentRecord]:
        """Find incidents by rule name, optionally filtered by status."""
        results = []
        for inc in self.incidents:
            if inc.rule_name == rule_name:
                if status and inc.status != status:
                    continue
                results.append(inc)
        return results

    def get_open_incidents(self, severity: str = "") -> list[IncidentRecord]:
        """Get all open incidents, optionally filtered by severity."""
        results = []
        for inc in self.incidents:
            if inc.status in ("open", "acknowledged", "resolving"):
                if severity and inc.severity != severity:
                    continue
                results.append(inc)
        return results

    def get_active_blockers(self) -> list[IncidentRecord]:
        """Get all currently blocking incidents (open + blocker severity)."""
        return [
            inc for inc in self.incidents
            if inc.status in ("open", "acknowledged")
            and inc.severity == "blocker"
        ]

    def summary(self) -> dict:
        """Generate summary of incident log state."""
        n_open = sum(1 for i in self.incidents if i.status == "open")
        n_acknowledged = sum(1 for i in self.incidents
                             if i.status == "acknowledged")
        n_resolving = sum(1 for i in self.incidents
                          if i.status == "resolving")
        n_resolved = sum(1 for i in self.incidents
                         if i.status == "resolved")
        n_closed = sum(1 for i in self.incidents if i.status == "closed")
        n_blockers = sum(1 for i in self.incidents
                         if i.severity == "blocker"
                         and i.status in ("open", "acknowledged"))
        n_critical = sum(1 for i in self.incidents
                         if i.severity == "critical"
                         and i.status in ("open", "acknowledged"))
        n_warnings = sum(1 for i in self.incidents
                         if i.severity == "warning"
                         and i.status in ("open", "acknowledged"))

        return {
            "n_total": len(self.incidents),
            "n_open": n_open,
            "n_acknowledged": n_acknowledged,
            "n_resolving": n_resolving,
            "n_resolved": n_resolved,
            "n_closed": n_closed,
            "active_blockers": n_blockers,
            "active_critical": n_critical,
            "active_warnings": n_warnings,
            "has_active_blockers": n_blockers > 0,
        }

    # -- Persistence -----------------------------------------------------

    def save(self, output_dir: str = "") -> str:
        """Save incidents as JSONL to output_dir.

        Returns the path to the saved file.
        """
        directory = output_dir or self._output_dir
        if not directory:
            return ""

        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "incidents.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for inc in self.incidents:
                f.write(json.dumps(inc.to_dict(), ensure_ascii=False) + "\n")
        return path

    def load(self, path: str):
        """Load incidents from a JSONL file."""
        if not os.path.exists(path):
            return
        self.incidents.clear()
        self._incident_counter = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self.incidents.append(IncidentRecord(**data))
                self._incident_counter += 1

    def clear(self):
        """Clear all incidents (for testing)."""
        self.incidents.clear()
        self._incident_counter = 0

    def _auto_save(self):
        """Auto-save if output_dir is configured."""
        if self._output_dir:
            self.save(self._output_dir)

    def get_recent(self, n: int = 20) -> list[IncidentRecord]:
        """Get the most recent N incidents."""
        return self.incidents[-n:]

    def to_dict_list(self) -> list[dict]:
        """Export all incidents as dicts (for serialization)."""
        return [inc.to_dict() for inc in self.incidents]
