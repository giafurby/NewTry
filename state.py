"""Gedächtnis des Bots: eine JSON-Datei (data/state.json), atomar geschrieben, mit Sicherungskopie."""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger("newtry.state")

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "positions": {},            # symbol -> offene Position
    "closed": [],               # abgeschlossene Trades (die letzten 500)
    "pending": None,            # Order, deren Ergebnis noch gebucht werden muss (Absturzschutz)
    "entered": {},              # symbol -> Signal-Kerze, auf die schon gekauft wurde (nie zweimal dieselbe)
    "dust": {},                 # symbol -> eigene Reste unter der Schrittweite (werden beim nächsten Verkauf mitverkauft)
    "last_signal_candle": 0,    # zuletzt vollständig geprüfte Signal-Kerze
    "last_dip_candle": 0,       # zuletzt geprüfte 15m-Kerze für den Crash-Kauf
    "entered_dip": {},          # symbol -> 15m-Kerze, auf die schon ein Crash-Kauf erfolgte
    "dip_cooldown": {},         # symbol -> Zeit (ms), bis zu der nach einem Notstop kein Crash-Kauf erfolgt
    "paused": False,            # /pause: keine neuen Käufe
    "halted": False,            # Notstopp: alles verkauft, keine neuen Käufe bis /weiter
    "liquidate": False,         # /notverkauf_ja: alle Positionen verkaufen, bis keine mehr offen ist
    "halt_reason": "",
    "start_equity": None,
    "started_at": None,
    "peak_equity": None,
    "day": None,
    "day_start_equity": None,
    "day_limit_hit": False,
    "last_quote_balance": None,
    "net_deposits": 0.0,        # Ein- minus Auszahlungen seit dem Start (zählen nicht als Gewinn)
    "realized_pnl": 0.0,
    "fees_paid": 0.0,
    "selftest_done": False,
    "last_report_day": None,
}


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.backup = path.with_suffix(".json.bak")
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        for candidate in (self.path, self.backup):
            if candidate.exists():
                try:
                    loaded = json.loads(candidate.read_text(encoding="utf-8"))
                    if candidate is self.backup:
                        log.warning("state.json unlesbar – Sicherungskopie geladen.")
                    return {**json.loads(json.dumps(DEFAULTS)), **loaded}
                except (OSError, ValueError) as exc:
                    log.error("%s nicht lesbar: %s", candidate, exc)
        return json.loads(json.dumps(DEFAULTS))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.data, indent=1, ensure_ascii=False, sort_keys=True)
        temp = self.path.with_suffix(".tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if self.path.exists():
            try:
                backup_temp = self.backup.with_suffix(".bak.tmp")
                shutil.copyfile(self.path, backup_temp)
                os.replace(backup_temp, self.backup)
            except OSError as exc:
                log.warning("Sicherungskopie nicht geschrieben: %s", exc)
        os.replace(temp, self.path)
