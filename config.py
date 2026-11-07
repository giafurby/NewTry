"""Einstellungen aus der Datei .env (Zeilen der Form SCHLUESSEL=WERT)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COINS = (
    "BTC,ETH,SOL,BNB,XRP,ADA,DOGE,TRX,LTC,LINK,"
    "AVAX,DOT,ATOM,ETC,XLM,NEAR,UNI,FIL,APT,ARB,OP,SUI,HBAR,AAVE,ALGO"
)


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
    risk_per_trade_pct: float     # so viel % des Kapitals darf ein einzelner Trade bis zum Stop verlieren
    max_positions: int
    max_position_pct: float       # höchstens so viel % des Kapitals in einer Position
    daily_loss_limit_pct: float   # Tagesverlust, ab dem heute nichts mehr gekauft wird
    max_drawdown_pct: float       # Rückgang vom Höchststand, ab dem alles verkauft und angehalten wird
    selftest_trade: bool          # einmaliger Funktionstest (Kauf + Verkauf ~7 USDC) beim ersten Echtgeld-Start
    scan_reports: bool            # nach jeder 4h-Prüfung eine stille Telegram-Nachricht
    report_hour: int              # Uhrzeit des Tagesberichts (Ortszeit)
    timezone: str
    paper_start_balance: float
    data_dir: Path

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
        daily_loss_limit_pct=_number(values, "DAILY_LOSS_LIMIT_PCT", 6.0, 1.0, 50.0, errors),
        max_drawdown_pct=_number(values, "MAX_DRAWDOWN_PCT", 25.0, 5.0, 90.0, errors),
        selftest_trade=_flag(values, "SELFTEST_TRADE", True, errors),
        scan_reports=_flag(values, "SCAN_REPORTS", True, errors),
        report_hour=int(_number(values, "REPORT_HOUR", 9, 0, 23, errors)),
        timezone=values.get("TIMEZONE", "Europe/Berlin").strip() or "Europe/Berlin",
        paper_start_balance=_number(values, "PAPER_START_BALANCE", 150.0, 10.0, 1_000_000.0, errors),
        data_dir=Path(values.get("DATA_DIR", "").strip() or env_path.resolve().parent / "data"),
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
}
