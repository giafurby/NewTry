"""Einstellungen, Speicher, Telegram, Startklar-Prüfung und Hauptschleife."""
import json

import pytest

from bot import run_check
from config import ConfigError, load_settings
from exchange import Broker
from fakes import SIGNAL_CLOSE_MS, Clock, FakeExchange, FakeTelegram, make_bot, make_settings
from notifier import Telegram
from state import StateStore


def write_env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_settings_defaults_and_parsing(tmp_path):
    env = write_env(tmp_path, "MODE=live\nBINANCE_API_KEY=abc\nBINANCE_API_SECRET='xyz'\nRISK_PER_TRADE_PCT=1,5\n"
                              "COINS=eth, btc ,ETH\n# Kommentar\nTELEGRAM_BOT_TOKEN=1:2\nTELEGRAM_CHAT_ID=42\n")
    s = load_settings(env, environ={})
    assert s.live and s.api_secret == "xyz" and s.risk_per_trade_pct == 1.5
    assert s.coins == ("ETH", "BTC") and s.quote == "USDC" and s.max_positions == 3
    assert s.data_dir == tmp_path / "data"


def test_settings_reject_live_without_keys_and_bad_numbers(tmp_path):
    env = write_env(tmp_path, "MODE=live\nRISK_PER_TRADE_PCT=10\nMAX_POSITIONS=abc\n")
    with pytest.raises(ConfigError) as error:
        load_settings(env, environ={})
    text = str(error.value)
    assert "BINANCE_API_KEY" in text and "RISK_PER_TRADE_PCT" in text and "MAX_POSITIONS" in text


def test_paper_mode_needs_no_keys(tmp_path):
    s = load_settings(write_env(tmp_path, "MODE=paper\n"), environ={})
    assert not s.live


def test_state_falls_back_to_backup(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.data["realized_pnl"] = 1.0
    store.save()
    store.data["realized_pnl"] = 2.0
    store.save()
    (tmp_path / "state.json").write_text("{kaputt", encoding="utf-8")
    assert StateStore(tmp_path / "state.json").data["realized_pnl"] == 1.0


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, updates=None):
        self.calls = []
        self.updates = updates or []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        if method == "getUpdates":
            return FakeResponse({"ok": True, "result": self.updates})
        return FakeResponse({"ok": True, "result": {"username": "testbot"}})


def test_telegram_splits_long_messages_and_filters_foreign_chats():
    session = FakeSession(updates=[
        {"update_id": 5, "message": {"chat": {"id": 42}, "text": "/status"}},
        {"update_id": 6, "message": {"chat": {"id": 999}, "text": "/notverkauf_ja"}},
    ])
    telegram = Telegram("1:2", "42", session=session, sleep=lambda _s: None)
    assert telegram.send("x" * 5000)
    assert [m for m, _ in session.calls].count("sendMessage") == 2
    assert telegram.poll(0) == ["/status"]
    assert telegram.offset == 7


def test_telegram_disabled_without_token():
    telegram = Telegram("", "", session=FakeSession(), sleep=lambda _s: None)
    assert not telegram.enabled and telegram.send("hallo") is False and telegram.poll(0) == []


def test_run_check_reports_ready(tmp_path, capsys):
    exchange = FakeExchange({"USDC": 150.0, "EUR": 3.0}, {"ETH/USDC": 100.0, "BTC/USDC": 100.0})
    settings = make_settings(tmp_path, coins=("ETH", "BTC", "DOGE"))
    assert run_check(settings, Broker(exchange, "USDC", sleep=lambda _s: None), FakeTelegram()) == 0
    out = capsys.readouterr().out
    assert "ohne Markt, werden übersprungen: DOGE" in out and "150,00 USDC frei" in out and "STARTKLAR" in out


def test_run_loop_handles_commands_and_stops_cleanly(tmp_path):
    exchange = FakeExchange({"USDC": 150.0}, {"ETH/USDC": 100.0, "BTC/USDC": 100.0, "SOL/USDC": 100.0,
                                              "XRP/USDC": 100.0})
    clock = Clock(SIGNAL_CLOSE_MS - 3_600_000)
    bot, telegram = make_bot(tmp_path, exchange, clock)
    bot.startup()
    rounds = []

    def poll(_timeout):
        rounds.append(1)
        clock.advance(10)
        if len(rounds) == 1:
            return ["/status"]
        bot.running = False
        return []

    telegram.poll = poll
    bot.run()
    assert any("📊 Status" in t for t in telegram.sent)
    assert "angehalten" in telegram.sent[-1]
    assert json.loads((tmp_path / "data" / "state.json").read_text(encoding="utf-8"))["start_equity"] == 150.0
