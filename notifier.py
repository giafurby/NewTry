"""Telegram: Nachrichten senden und Befehle empfangen (nur aus dem eingetragenen Chat)."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

import requests

log = logging.getLogger("newtry.telegram")

MAX_LENGTH = 3900


class Telegram:
    def __init__(self, token: str, chat_id: str, session: Any = None, sleep: Callable[[float], None] = time.sleep):
        self.token = token
        self.chat_id = str(chat_id)
        self.enabled = bool(token and chat_id)
        self.session = session or requests.Session()
        self._sleep = sleep
        self.offset: Optional[int] = None

    def _safe(self, exc: Exception) -> str:
        """Fehlertext ohne Bot-Token (requests schreibt sonst die ganze Adresse samt Token in die Meldung)."""
        text = f"{type(exc).__name__}: {exc}"
        return text.replace(self.token, "***") if self.token else text

    def _api(self, method: str, payload: dict[str, Any], timeout: float) -> Any:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        response = self.session.post(url, json=payload, timeout=timeout)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"Telegram {method}: HTTP {response.status_code}") from None
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description') or response.status_code}")
        return data.get("result")

    def send(self, text: str, silent: bool = False) -> bool:
        log.info("Telegram: %s", text.replace("\n", " | ")[:300])
        if not self.enabled:
            return False
        ok = True
        for start in range(0, max(len(text), 1), MAX_LENGTH):
            chunk = text[start:start + MAX_LENGTH]
            for attempt in range(3):
                try:
                    self._api("sendMessage", {"chat_id": self.chat_id, "text": chunk,
                                              "disable_notification": silent,
                                              "disable_web_page_preview": True}, 20)
                    break
                except Exception as exc:
                    log.warning("Telegram senden fehlgeschlagen (%s)", self._safe(exc))
                    self._sleep(2.0 * (attempt + 1))
            else:
                ok = False
        return ok

    def prepare(self, commands: list[tuple[str, str]]) -> Optional[str]:
        """Beim Start: Befehlsmenü setzen, Webhook entfernen, alte (liegengebliebene) Befehle verwerfen."""
        if not self.enabled:
            return None
        name = None
        try:
            me = self._api("getMe", {}, 20)
            name = me.get("username")
            self._api("deleteWebhook", {}, 20)
            self._api("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]}, 20)
            pending = self._api("getUpdates", {"offset": -1, "timeout": 0}, 20) or []
            if pending:
                self.offset = int(pending[-1]["update_id"]) + 1
        except Exception as exc:
            log.warning("Telegram-Vorbereitung unvollständig: %s", self._safe(exc))
        return name

    def poll(self, timeout: float) -> list[str]:
        """Wartet bis zu `timeout` Sekunden auf Befehle. Dient zugleich als Takt der Hauptschleife."""
        if not self.enabled:
            self._sleep(timeout)
            return []
        payload: dict[str, Any] = {"timeout": int(timeout), "allowed_updates": ["message"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        try:
            updates = self._api("getUpdates", payload, timeout + 15) or []
        except Exception as exc:
            log.warning("Telegram-Abfrage fehlgeschlagen: %s", self._safe(exc))
            self._sleep(min(timeout, 10))
            return []
        commands: list[str] = []
        for update in updates:
            self.offset = int(update["update_id"]) + 1
            message = update.get("message") or {}
            chat = str((message.get("chat") or {}).get("id"))
            if chat != self.chat_id:
                log.warning("Nachricht aus fremdem Chat %s ignoriert.", chat)
                continue
            text = (message.get("text") or "").strip()
            if text:
                commands.append(text)
        return commands
