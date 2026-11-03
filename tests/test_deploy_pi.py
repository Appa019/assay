"""The pi-ops contract scripts in deploy/pi, run against a fake app folder and
stubbed systemctl/curl/claude. Nothing here touches the real Pi or storage/."""

import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PI = REPO / "deploy" / "pi"


def test_contract_scripts_are_executable() -> None:
    # pi-backup and saude skip a script without the exec bit
    for name in ("deploy.sh", "install.sh", "check.sh", "health.sh", "backup.sh"):
        assert os.access(PI / name, os.X_OK), name


# --- health.sh ---------------------------------------------------------------


def _stub(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture()
def health_env(tmp_path: Path) -> dict[str, str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub(stubs, "curl", 'exit "${CURL_RC:-0}"')
    _stub(
        stubs,
        "systemctl",
        'case "$*" in\n'
        '  *list-timers*) i=0; while [ $i -lt "${TIMERS:-11}" ]; do echo t$i; i=$((i+1)); done ;;\n'
        '  *--state=failed*) [ -n "$FAILED" ] && echo "$FAILED loaded failed failed x" ;;\n'
        '  *is-active*) exit "${ACTIVE_RC:-0}" ;;\n'
        "esac\nexit 0",
    )
    claude = tmp_path / "claude-bin"
    claude.mkdir()
    _stub(claude, "claude", "exit 0")
    # HOME is fake so the script's ~/.local/bin cannot supply a real claude
    return {"HOME": str(tmp_path), "PATH": f"{stubs}:{claude}:/usr/bin:/bin"}


@pytest.mark.parametrize(
    ("extra", "drop_claude", "expected"),
    [
        ({}, False, 0),
        ({"FAILED": "investimentos-weekly.service"}, False, 2),
        ({}, True, 2),
        ({"CURL_RC": "7"}, False, 1),
        ({"TIMERS": "9"}, False, 1),
        ({"ACTIVE_RC": "3", "FAILED": "x"}, False, 1),
    ],
)
def test_health_exit_codes(
    health_env: dict[str, str], extra: dict[str, str], drop_claude: bool, expected: int
) -> None:
    env = {**health_env, **extra}
    if drop_claude:
        env["PATH"] = ":".join(p for p in env["PATH"].split(":") if "claude-bin" not in p)
    proc = subprocess.run(["bash", str(PI / "health.sh")], env=env, capture_output=True)
    assert proc.returncode == expected, proc.stderr.decode()


# --- backup.sh ---------------------------------------------------------------


@pytest.fixture()
def fake_app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "deploy" / "pi").mkdir(parents=True)
    shutil.copy2(PI / "backup.sh", root / "deploy" / "pi" / "backup.sh")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").symlink_to(sys.executable)
    storage = root / "storage"
    for sub in ("agent_workspace/tools", "agent_workspace/out", "chat_workspace/inbox", "webpush"):
        (storage / sub).mkdir(parents=True)
    (storage / "agent_workspace" / "MEMORY.md").write_text("comitê\n")
    (storage / "agent_workspace" / "tools" / "t.py").write_text("print(1)\n")
    (storage / "agent_workspace" / "out" / "etapa_01.json").write_text("{}")
    (storage / "chat_workspace" / "MEMORY.md").write_text("cliente\n")
    (storage / "chat_workspace" / "inbox" / "foto.jpg").write_bytes(b"\xff\xd8")
    (storage / "webpush" / "vapid_private.pem").write_text("KEY\n")
    (storage / "alerts_state.json").write_text("{}")
    (root / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=secret\n")
    return root


def _tree(folder: Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*")}


def test_backup_is_consistent_and_writes_only_to_dir(fake_app: Path, tmp_path: Path) -> None:
    db_path = fake_app / "storage" / "portfolio.db"
    live = sqlite3.connect(db_path)  # a live writer: committed rows still in -wal
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("CREATE TABLE t (v TEXT)")
    live.executemany("INSERT INTO t VALUES (?)", [(f"r{i}",) for i in range(300)])
    live.commit()
    assert (fake_app / "storage" / "portfolio.db-wal").stat().st_size > 0
    before = _tree(fake_app)

    out = tmp_path / "snap"
    subprocess.run([str(fake_app / "deploy" / "pi" / "backup.sh"), str(out)], check=True)
    assert _tree(fake_app) == before
    live.close()  # closing checkpoints and removes -wal, so compare before it

    assert sorted(p.name for p in out.iterdir()) == ["portfolio.db.gz", "storage-state.tgz"]
    copy = tmp_path / "copy.db"
    copy.write_bytes(gzip.decompress((out / "portfolio.db.gz").read_bytes()))
    rows = sqlite3.connect(copy).execute("SELECT count(*) FROM t").fetchone()[0]
    assert rows == 300
    with tarfile.open(out / "storage-state.tgz") as tar:
        names = set(tar.getnames())
    assert "agent_workspace/MEMORY.md" in names
    assert "webpush/vapid_private.pem" in names
    assert not any("inbox" in n or "/out" in n for n in names)


def test_backup_refuses_without_the_database(fake_app: Path, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    proc = subprocess.run(
        [str(fake_app / "deploy" / "pi" / "backup.sh"), str(out)], capture_output=True
    )
    assert proc.returncode != 0
    assert not (fake_app / "storage" / "portfolio.db").exists()
