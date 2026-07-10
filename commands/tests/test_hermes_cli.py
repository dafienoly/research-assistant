import json
import os
import subprocess
import sys
from pathlib import Path


def test_hermes_cli_help_lists_vnext_commands():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "commands" / "hermes_cli.py"), "help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "report:vnext-premarket" in result.stdout


def test_hermes_cli_loads_project_env_without_shell_export(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token-from-dotenv\n"
        "TELEGRAM_CHAT_ID=test-chat-from-dotenv\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)
    env.pop("TELEGRAM_CHAT_ID", None)
    env["HERMES_ENV_FILE"] = str(env_file)

    result = subprocess.run(
        [
            sys.executable,
            str(root / "commands" / "hermes_cli.py"),
            "approval:telegram-test",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["credentials_configured"] is True
    assert payload["dry_run"] is True


def test_shell_environment_takes_precedence_over_project_env(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=dotenv-token\nTELEGRAM_CHAT_ID=dotenv-chat\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HERMES_ENV_FILE"] = str(env_file)
    env["TELEGRAM_BOT_TOKEN"] = "shell-token"
    env.pop("TELEGRAM_CHAT_ID", None)

    script = (
        "import os, runpy, sys; "
        f"sys.argv=[{str(root / 'commands' / 'hermes_cli.py')!r}, 'help']; "
        f"runpy.run_path({str(root / 'commands' / 'hermes_cli.py')!r}, run_name='__main__'); "
        "print('TOKEN_SOURCE=' + os.environ['TELEGRAM_BOT_TOKEN'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "TOKEN_SOURCE=shell-token" in result.stdout
