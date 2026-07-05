"""Core CLI V2.14.2 — 统一 CommandRegistry"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommandOption:
    name: str
    type: str = "str"
    default: any = None
    help: str = ""


@dataclass
class CommandDef:
    name: str
    handler: str = ""
    description: str = ""
    options: list = field(default_factory=list)
    category: str = ""


COMMON_OPTIONS = [
    CommandOption("--latest", type="bool", help="Use latest run"),
    CommandOption("--run-id", type="str", help="Specific run ID"),
    CommandOption("--candidate", type="str", help="Candidate name"),
    CommandOption("--start", type="str", help="Start date YYYY-MM-DD"),
    CommandOption("--end", type="str", help="End date YYYY-MM-DD"),
    CommandOption("--last", type="int", help="Last N days"),
    CommandOption("--strict", type="bool", help="Strict mode"),
    CommandOption("--dry-run", type="bool", default=True, help="Dry run"),
    CommandOption("--confirm", type="bool", help="Confirm action"),
    CommandOption("--rollback", type="str", help="Rollback run ID"),
]


class CommandRegistry:
    def __init__(self):
        self.commands = {}

    def register(self, cmd: CommandDef):
        self.commands[cmd.name] = cmd

    def get(self, name: str) -> Optional[CommandDef]:
        return self.commands.get(name)

    def list_by_category(self, category: str):
        return [c for c in self.commands.values() if c.category == category]
