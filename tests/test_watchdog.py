"""Wächter (deploy/watchdog.sh) mit nachgebautem systemctl und curl – ohne Netz, ohne echten Dienst."""
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "watchdog.sh"

FAKE_SYSTEMCTL = """#!/bin/bash
echo "$*" >> "$FAKE_DIR/systemctl.log"
case "$1" in
  is-enabled) cat "$FAKE_DIR/enabled"; [[ "$(cat "$FAKE_DIR/enabled")" == enabled ]] ;;
  is-active) cat "$FAKE_DIR/active"; [[ "$(cat "$FAKE_DIR/active")" == active ]] ;;
  show) cat "$FAKE_DIR/since" ;;
  restart) exit 0 ;;
esac
"""
FAKE_CURL = """#!/bin/bash
cat > /dev/null
for arg in "$@"; do
  case "$arg" in text=*) printf '%s\\n' "${arg#text=}" >> "$FAKE_DIR/telegram.log" ;; esac
done
"""


@pytest.fixture
def world(tmp_path):
    fake = tmp_path / "fake"
    (fake / "bin").mkdir(parents=True)
    for name, body in (("systemctl", FAKE_SYSTEMCTL), ("curl", FAKE_CURL)):
        path = fake / "bin" / name
        path.write_text(body)
        path.chmod(0o755)
    app = tmp_path / "newtry"
    (app / "data").mkdir(parents=True)
    (app / ".env").write_text("TELEGRAM_BOT_TOKEN=1:2\nTELEGRAM_CHAT_ID=42\n")

    def set_state(active="active", enabled="enabled", since_age=3600, heartbeat_age=10):
        (fake / "active").write_text(active)
        (fake / "enabled").write_text(enabled)
        (fake / "since").write_text(f"@{int(time.time()) - since_age}")
        hb = app / "data" / "heartbeat"
        if heartbeat_age is None:
            hb.unlink(missing_ok=True)
        else:
            hb.write_text("x")
            stamp = time.time() - heartbeat_age
            os.utime(hb, (stamp, stamp))

    def run(disk_limit="101"):
        env = {**os.environ, "PATH": f"{fake / 'bin'}:{os.environ['PATH']}", "FAKE_DIR": str(fake),
               "NEWTRY_DIR": str(app), "WATCHDOG_STATE_DIR": str(tmp_path / "state"), "WATCHDOG_DISK_LIMIT": disk_limit}
        result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return result

    def telegram():
        log = fake / "telegram.log"
        return log.read_text().splitlines() if log.exists() else []

    def restarts():
        log = fake / "systemctl.log"
        return [line for line in (log.read_text().splitlines() if log.exists() else []) if line.startswith("restart")]

    return set_state, run, telegram, restarts, tmp_path


def test_healthy_bot_is_quiet(world):
    set_state, run, telegram, restarts, _ = world
    set_state()
    run()
    assert telegram() == [] and restarts() == []


def test_hanging_bot_is_reported_and_restarted_once(world):
    set_state, run, telegram, restarts, _ = world
    set_state(heartbeat_age=1200)
    run()
    assert len(telegram()) == 1 and "reagiert nicht mehr" in telegram()[0] and "neu gestartet" in telegram()[0]
    assert restarts() == ["restart newtry-bot"]
    run()                                                         # 5 Minuten später: kein Spam, kein Dauer-Neustart
    assert len(telegram()) == 1 and len(restarts()) == 1
    set_state(heartbeat_age=5)
    run()
    assert "Alles wieder in Ordnung" in telegram()[-1]


def test_crashed_bot_is_restarted(world):
    set_state, run, telegram, restarts, _ = world
    set_state(active="failed")
    run()
    assert "läuft nicht" in telegram()[0] and restarts() == ["restart newtry-bot"]


def test_deliberately_disabled_bot_is_left_alone(world):
    set_state, run, telegram, restarts, _ = world
    set_state(active="inactive", enabled="disabled")
    run()
    assert telegram() == [] and restarts() == []


def test_quiet_during_update_and_after_fresh_start(world):
    set_state, run, telegram, restarts, tmp_path = world
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "wartung").write_text("")
    set_state(active="failed")
    run()
    assert telegram() == [] and restarts() == []
    (tmp_path / "state" / "wartung").unlink()
    set_state(since_age=60, heartbeat_age=None)                   # gerade gestartet, noch kein Lebenszeichen
    run()
    assert telegram() == [] and restarts() == []


def test_full_disk_is_reported_without_restart(world):
    set_state, run, telegram, restarts, _ = world
    set_state()
    run(disk_limit="0")
    assert "Festplatte" in telegram()[0] and restarts() == []
