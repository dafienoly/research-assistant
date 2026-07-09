"""Conftest for data tests - sets up Python path"""
import sys
from pathlib import Path

# Add commands/ to path so universes module is importable
BASE = Path(__file__).resolve().parent.parent.parent  # research-assistant/
COMMANDS_DIR = BASE / "commands"
if str(COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(COMMANDS_DIR))
