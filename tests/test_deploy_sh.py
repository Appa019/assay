"""deploy/pi/deploy.sh against a throwaway git app: every path (healthy, pinned sha, foreign
sha, install/check/restart/health failing, check saying 'not now', TERM mid-deploy) with
stubbed install/check/health/systemctl/pip/pnpm, in the style of pi-ops tests/run.
Nothing here touches the real Pi, storage/ or the network (the origin is a local bare repo)."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy" / "pi" / "deploy.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_NOSYSTEM": "1",
}

# Stubs read their behaviour from env vars that deploy.sh passes through untouched.
INSTALL = """#!/bin/sh
cd "$(dirname "$0")/../.."
echo "install $(git rev-parse --short HEAD)" >>"$LOG"
[ "$(git rev-parse HEAD)" = "${INSTALL_FAILS_AT:-none}" ] && exit 1
exit 0
"""
CHECK = """#!/bin/sh
cd "$(dirname "$0")/../.."
echo "check $(git rev-parse --short HEAD)" >>"$LOG"
[ "${CHECK_RC:-0}" = 75 ] && exit 75
mkdir -p frontend/.next-build && git rev-parse HEAD >frontend/.next-build/BUILD
[ -n "$CHECK_DIRTIES" ] && echo dirty >>version
[ -n "$CHECK_SENDS_TERM" ] && kill -TERM "$PPID"
exit "${CHECK_RC:-0}"
"""
HEALTH = '#!/bin/sh\necho health >>"$LOG"\nexit "${HEALTH_RC:-0}"\n'
SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >>"$LOG"
case "$*" in *restart*) [ -n "$RESTART_FAILS" ] && exit 1 ;; esac
exit 0
"""
PIP = '#!/bin/sh\necho "pip $*" >>"$LOG"\n'
PNPM = '#!/bin/sh\necho "pnpm $*" >>"$LOG"\n'


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True
    )
    return out.stdout.decode().strip()


def _write(path: Path, body: str, exe: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    if exe:
        path.chmod(0o755)


@dataclass
class App:
    root: Path
    work: Path
    log: Path
    env: dict[str, str]
    v1: str
    v2: str

    def deploy(self, *args: str, **extra: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["bash", str(self.root / "deploy" / "pi" / "deploy.sh"), *args],
            env={**self.env, **extra},
            capture_output=True,
            timeout=60,
        )

    def head(self) -> str:
        return _git(self.root, "rev-parse", "HEAD")

    def live_build(self) -> str:
        return (self.root / "frontend" / ".next" / "BUILD").read_text().strip()

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def push(self, change: str, message: str) -> str:
        if change == "requirements":
            _write(self.work / "requirements.txt", f"pkg=={message}\n")
        else:
            _write(self.work / "version", f"{message}\n")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-qm", message)
        _git(self.work, "push", "-q", "origin", "HEAD:main")
        return _git(self.work, "rev-parse", "HEAD")


@pytest.fixture()
def app(tmp_path: Path) -> App:
    origin, work, root = tmp_path / "origin.git", tmp_path / "work", tmp_path / "app"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    pi = work / "deploy" / "pi"
    pi.mkdir(parents=True)
    shutil.copy2(DEPLOY, pi / "deploy.sh")
    (pi / "deploy.sh").chmod(0o755)
    _write(pi / "install.sh", INSTALL, exe=True)
    _write(pi / "check.sh", CHECK, exe=True)
    _write(pi / "health.sh", HEALTH, exe=True)
    _write(work / "requirements.txt", "pkg==1\n")
    _write(work / "frontend" / "pnpm-lock.yaml", "lock: 1\n")
    _write(work / ".gitignore", ".env\n.venv/\nfrontend/.next*/\n")
    _write(work / "version", "v1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "v1")
    _git(work, "push", "-q", "origin", "HEAD:main")
    v1 = _git(work, "rev-parse", "HEAD")
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(root))

    # the live app: secrets, a venv and the build of v1
    (root / ".env").write_text("X=1\n")
    _write(root / ".venv" / "bin" / "python", PIP, exe=True)
    _write(root / "frontend" / ".next" / "BUILD", f"{v1}\n")
    stubs = tmp_path / "stubs"
    _write(stubs / "systemctl", SYSTEMCTL, exe=True)
    _write(stubs / "pnpm", PNPM, exe=True)
    log = tmp_path / "calls.log"
    env = {
        **GIT_ENV,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{stubs}:/usr/bin:/bin",
        "XDG_RUNTIME_DIR": str(tmp_path),
        "LOG": str(log),
    }
    a = App(root=root, work=work, log=log, env=env, v1=v1, v2="")
    a.v2 = a.push("version", "v2")
    return a


def _rolled_back(app: App) -> None:
    assert app.head() == app.v1
    assert app.live_build() == app.v1
    assert not (app.root / "frontend" / ".next-build").exists()
    assert _git(app.root, "status", "--porcelain") == ""


def test_healthy_deploy_goes_live(app: App) -> None:
    proc = app.deploy()
    assert proc.returncode == 0, proc.stderr.decode()
    assert app.head() == app.v2
    assert app.live_build() == app.v2
    assert not (app.root / "frontend" / ".next-old").exists()
    assert "systemctl --user restart investimentos-backend investimentos-frontend" in app.calls()


def test_health_warning_keeps_the_deploy(app: App) -> None:
    assert app.deploy(HEALTH_RC="2").returncode == 0
    assert app.head() == app.v2


def test_only_the_reviewed_sha_goes_live(app: App) -> None:
    later = app.push("version", "v3")
    assert app.deploy(app.v2).returncode == 0
    assert app.head() == app.v2 != later


def test_a_sha_outside_origin_main_is_refused(app: App) -> None:
    proc = app.deploy("0123456789abcdef0123456789abcdef01234567")
    assert proc.returncode != 0
    assert app.head() == app.v1
    assert not any(c.startswith(("install", "check")) for c in app.calls())


@pytest.mark.parametrize(
    "extra",
    [
        {"CHECK_RC": "1"},
        {"CHECK_RC": "1", "CHECK_DIRTIES": "1"},  # reset --keep alone would refuse
        {"HEALTH_RC": "1"},
        {"RESTART_FAILS": "1"},
        {"CHECK_SENDS_TERM": "1"},  # the guardian's unit stopped mid-deploy
    ],
)
def test_every_failure_puts_v1_back_and_running(app: App, extra: dict[str, str]) -> None:
    proc = app.deploy(**extra)
    assert proc.returncode == 1, proc.stderr.decode()
    _rolled_back(app)
    calls = app.calls()
    # the previous commit's units are refreshed and the services restarted on it
    assert calls[-2:] == [
        f"install {app.v1[:7]}",
        "systemctl --user restart investimentos-backend investimentos-frontend",
    ]


def test_install_failing_puts_v1_back(app: App) -> None:
    proc = app.deploy(INSTALL_FAILS_AT=app.v2)
    assert proc.returncode == 1
    _rolled_back(app)
    assert not any(c.startswith("check") for c in app.calls())


def test_not_now_restarts_nothing(app: App) -> None:
    proc = app.deploy(CHECK_RC="75")
    assert proc.returncode == 75
    _rolled_back(app)
    assert not any("restart" in c for c in app.calls())


def test_rollback_reinstalls_the_previous_packages(app: App) -> None:
    app.push("requirements", "v3")
    assert app.deploy(CHECK_RC="1").returncode == 1
    calls = app.calls()
    assert "pip -m pip install -q -r requirements.txt" in calls
    assert "pnpm install --frozen-lockfile" in calls
    assert (app.root / "requirements.txt").read_text() == "pkg==1\n"


@pytest.mark.parametrize(("lock_rc", "expected"), [("0", 75), ("1", None)])
def test_check_says_not_now_before_touching_the_venv(
    tmp_path: Path, lock_rc: str, expected: int | None
) -> None:
    root = tmp_path / "app"
    (root / "deploy" / "pi").mkdir(parents=True)
    shutil.copy2(REPO / "deploy" / "pi" / "check.sh", root / "deploy" / "pi" / "check.sh")
    # -c = the committee lock probe (0 = a run holds it); anything else = pip
    _write(
        root / ".venv" / "bin" / "python",
        '#!/bin/sh\n[ "$1" = -c ] && exit "$LOCK_RC"\necho "pip $*" >>"$LOG"\nexit 9\n',
        exe=True,
    )
    log = tmp_path / "calls.log"
    proc = subprocess.run(
        ["bash", str(root / "deploy" / "pi" / "check.sh")],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "LOG": str(log), "LOCK_RC": lock_rc},
        capture_output=True,
    )
    if expected == 75:
        assert proc.returncode == 75
        assert not log.exists(), "pip ran while the committee held the lock"
    else:
        # no run: the install goes ahead (the stub then fails it, ending the check)
        assert proc.returncode == 9
        assert "pip -m pip install -q -r requirements.txt" in log.read_text()


def test_rollback_skips_packages_when_the_lockfiles_did_not_change(app: App) -> None:
    assert app.deploy(CHECK_RC="1").returncode == 1
    assert not any(c.startswith(("pip", "pnpm")) for c in app.calls())
