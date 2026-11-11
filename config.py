"""Einstellungen aus der Datei .env (Zeilen der Form SCHLUESSEL=WERT)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COINS = (
    "BTC,ETH,SOL,BNB,XRP,ADA,DOGE,TRX,LTC,LINK,"
    "AVAX,DOT,ATOM,ETC,XLM,NEAR,UNI,FIL,APT,ARB,OP,SUI,HBAR,AAVE,ALGO"
)
# Crash-Kauf nur in den 10 großen Coins, auf denen die Regel geprüft wurde (research/ERGEBNISSE.md)
DEFAULT_DIP_COINS = "BTC,ETH,SOL,BNB,XRP,TRX,DOGE,ZEC,ADA,BCH"


class ConfigError(Exception):
    """Die .env ist unvollständig oder enthält ungültige Werte."""


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    mode: str                     # "live" = Echtgeld, "paper" = Simulation mit echten Kursen
    api_key: str
    api_secret: str
    telegram_token: str
    telegram_chat_id: str
    quote: str                    # Währung, mit der gekauft wird (z. B. USDC)
    coins: tuple[str, ...]
    risk_per_trade_pct: float     # Trend: so viel % des Kapitals darf ein Trade bis zum Stop verlieren
    max_positions: int            # Trend: höchstens so viele Positionen
    max_position_pct: float       # Trend: höchstens so viel % des Kapitals in einer Position
    daily_loss_limit_pct: float   # Tagesverlust, ab dem heute nichts mehr gekauft wird (0 = aus)
    max_drawdown_pct: float       # Rückgang vom Höchststand, ab dem alles verkauft und angehalten wird
    dip_enabled: bool             # Crash-Kauf an/aus
    dip_coins: tuple[str, ...]
    dip_drop_pct: float           # so tief muss der Kurs in 4 Stunden fallen
    dip_position_pct: float       # Größe je Crash-Kauf in % des Kapitals
    dip_max_positions: int
    dip_stop_pct: float           # Notstop unter dem Einstieg
    dip_hold_hours: float         # nach so vielen Stunden wird verkauft
    dip_cooldown_hours: float     # Sperre für den Coin nach einem Notstop
    exchange_stop: bool           # Notbremse: Stop-Order direkt bei Binance, hält auch ohne Bot und Server
    exchange_stop_buffer_pct: float   # so viel % unter dem Bot-Stop löst die Notbremse aus
    exchange_stop_gap_pct: float      # so viel % unter dem Auslöser liegt ihr Mindestpreis
    selftest_trade: bool          # einmaliger Funktionstest (Kauf + Verkauf ~7 USDC) beim ersten Echtgeld-Start
    scan_reports: bool            # nach jeder 4h-Prüfung eine stille Telegram-Nachricht
    report_hour: int              # Uhrzeit des Tagesberichts (Ortszeit)
    timezone: str
    paper_start_balance: float
    data_dir: Path
    dip_max_slippage_pct: float = 0.35   # Crash-Kauf aussetzen, wenn Käufe so viel schlechter sind als simuliert (0 = aus)
    slippage_window: int = 10            # … gemessen über so viele Crash-Käufe
    earn_enabled: bool = False           # ungenutztes Guthaben in Binance Simple Earn Flexible verzinsen
    earn_reserve: float = 60.0           # so viel Quote-Währung bleibt immer frei im Spot-Konto (für Crash-Käufe)
    earn_redeem_wait_s: float = 20.0     # so lange auf eine Rücknahme warten, bevor mit der Reserve gekauft wird
    halt_wait_hours: float = 24.0        # nach einem Notstopp erst nach so vielen Stunden wieder /weiter

    @property
    def live(self) -> bool:
        return self.mode == "live"


def _number(values: dict[str, str], key: str, default: float, low: float, high: float, errors: list[str]) -> float:
    raw = values.get(key, "").strip()
    if not raw:
        return default
    try:
        number = float(raw.replace(",", "."))
    except ValueError:
        errors.append(f"{key}={raw!r} ist keine Zahl.")
        return default
    if not low <= number <= high:
        errors.append(f"{key}={raw} liegt außerhalb von {low:g} bis {high:g}.")
        return default
    return number


def _flag(values: dict[str, str], key: str, default: bool, errors: list[str]) -> bool:
    raw = values.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "ja", "yes", "an", "on"):
        return True
    if raw in ("0", "false", "nein", "no", "aus", "off"):
        return False
    errors.append(f"{key}={raw!r}: erlaubt sind true oder false.")
    return default


def load_settings(env_path: Path | str = ".env", environ: dict[str, str] | None = None) -> Settings:
    env_path = Path(env_path)
    values = read_env_file(env_path)
    values.update({k: v for k, v in (os.environ if environ is None else environ).items() if k in _KEYS})
    errors: list[str] = []

    mode = values.get("MODE", "paper").strip().lower() or "paper"
    if mode not in ("live", "paper"):
        errors.append(f"MODE={mode!r}: erlaubt sind live oder paper.")
    api_key = values.get("BINANCE_API_KEY", "").strip()
    api_secret = values.get("BINANCE_API_SECRET", "").strip()
    if mode == "live" and not (api_key and api_secret):
        errors.append("Für MODE=live fehlen BINANCE_API_KEY und/oder BINANCE_API_SECRET.")

    quote = values.get("QUOTE", "USDC").strip().upper() or "USDC"
    coins = tuple(dict.fromkeys(c.strip().upper() for c in values.get("COINS", DEFAULT_COINS).split(",") if c.strip()))
    if not coins:
        errors.append("COINS ist leer.")
    bad = [c for c in coins if not c.isalnum() or c == quote]
    if bad:
        errors.append(f"COINS enthält ungültige Einträge: {', '.join(bad)}.")
    bad_dip = [c for c in values.get("DIP_COINS", DEFAULT_DIP_COINS).split(",") if c.strip() and not c.strip().isalnum()]
    if bad_dip:
        errors.append(f"DIP_COINS enthält ungültige Einträge: {', '.join(bad_dip)}.")

    settings = Settings(
        mode=mode,
        api_key=api_key,
        api_secret=api_secret,
        telegram_token=values.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=values.get("TELEGRAM_CHAT_ID", "").strip(),
        quote=quote,
        coins=coins,
        risk_per_trade_pct=_number(values, "RISK_PER_TRADE_PCT", 1.0, 0.1, 3.0, errors),
        max_positions=int(_number(values, "MAX_POSITIONS", 3, 1, 10, errors)),
        max_position_pct=_number(values, "MAX_POSITION_PCT", 33.0, 5.0, 100.0, errors),
        daily_loss_limit_pct=_number(values, "DAILY_LOSS_LIMIT_PCT", 0.0, 0.0, 50.0, errors),
        max_drawdown_pct=_number(values, "MAX_DRAWDOWN_PCT", 30.0, 5.0, 90.0, errors),
        dip_enabled=_flag(values, "DIP_ENABLED", True, errors),
        dip_coins=tuple(dict.fromkeys(c.strip().upper() for c in values.get("DIP_COINS", DEFAULT_DIP_COINS).split(",")
                                      if c.strip())),
        dip_drop_pct=_number(values, "DIP_DROP_PCT", 9.0, 3.0, 50.0, errors),
        dip_position_pct=_number(values, "DIP_POSITION_PCT", 20.0, 2.0, 50.0, errors),
        dip_max_positions=int(_number(values, "DIP_MAX_POSITIONS", 3, 1, 10, errors)),
        dip_stop_pct=_number(values, "DIP_STOP_PCT", 15.0, 2.0, 50.0, errors),
        dip_hold_hours=_number(values, "DIP_HOLD_HOURS", 4.0, 0.5, 72.0, errors),
        dip_cooldown_hours=_number(values, "DIP_COOLDOWN_HOURS", 24.0, 0.0, 336.0, errors),
        exchange_stop=_flag(values, "EXCHANGE_STOP", True, errors),
        exchange_stop_buffer_pct=_number(values, "EXCHANGE_STOP_BUFFER_PCT", 1.0, 0.1, 5.0, errors),
        exchange_stop_gap_pct=_number(values, "EXCHANGE_STOP_GAP_PCT", 3.0, 0.5, 20.0, errors),
        selftest_trade=_flag(values, "SELFTEST_TRADE", True, errors),
        scan_reports=_flag(values, "SCAN_REPORTS", True, errors),
        report_hour=int(_number(values, "REPORT_HOUR", 9, 0, 23, errors)),
        timezone=values.get("TIMEZONE", "Europe/Berlin").strip() or "Europe/Berlin",
        paper_start_balance=_number(values, "PAPER_START_BALANCE", 150.0, 10.0, 1_000_000.0, errors),
        data_dir=Path(values.get("DATA_DIR", "").strip() or env_path.resolve().parent / "data"),
        dip_max_slippage_pct=_number(values, "DIP_MAX_SLIPPAGE_PCT", 0.35, 0.0, 5.0, errors),
        slippage_window=int(_number(values, "SLIPPAGE_WINDOW", 10, 3, 50, errors)),
        earn_enabled=_flag(values, "EARN_ENABLED", False, errors),
        earn_reserve=_number(values, "EARN_RESERVE_USDC", 60.0, 10.0, 1_000_000.0, errors),
        earn_redeem_wait_s=_number(values, "EARN_REDEEM_WAIT_S", 20.0, 0.0, 120.0, errors),
        halt_wait_hours=_number(values, "HALT_WAIT_HOURS", 24.0, 0.0, 168.0, errors),
    )
    if settings.telegram_token and not settings.telegram_chat_id:
        errors.append("TELEGRAM_CHAT_ID fehlt (TELEGRAM_BOT_TOKEN ist gesetzt).")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(settings.timezone)
    except Exception:
        errors.append(f"TIMEZONE={settings.timezone!r} ist unbekannt.")
    if errors:
        raise ConfigError("\n".join(f"  • {e}" for e in errors))
    return settings


_KEYS = {
    "MODE", "BINANCE_API_KEY", "BINANCE_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "QUOTE", "COINS",
    "RISK_PER_TRADE_PCT", "MAX_POSITIONS", "MAX_POSITION_PCT", "DAILY_LOSS_LIMIT_PCT", "MAX_DRAWDOWN_PCT",
    "SELFTEST_TRADE", "SCAN_REPORTS", "REPORT_HOUR", "TIMEZONE", "PAPER_START_BALANCE", "DATA_DIR",
    "DIP_ENABLED", "DIP_COINS", "DIP_DROP_PCT", "DIP_POSITION_PCT", "DIP_MAX_POSITIONS", "DIP_STOP_PCT",
    "DIP_HOLD_HOURS", "DIP_COOLDOWN_HOURS", "EXCHANGE_STOP", "EXCHANGE_STOP_BUFFER_PCT", "EXCHANGE_STOP_GAP_PCT",
    "DIP_MAX_SLIPPAGE_PCT", "SLIPPAGE_WINDOW", "EARN_ENABLED", "EARN_RESERVE_USDC", "EARN_REDEEM_WAIT_S",
    "HALT_WAIT_HOURS",
}
