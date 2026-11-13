#!/usr/bin/env bash
# =============================================================================
# install.sh – NewTry auf dem Server installieren oder aktualisieren (als root).
#
# Erstinstallation UND jedes spätere Update mit derselben Zeile:
#   curl -fsSL https://raw.githubusercontent.com/giafurby/NewTry/ccr-65a9ebf1-h1kqzu/install.sh -o /root/newtry-install.sh && bash /root/newtry-install.sh
#
# Optionen:
#   --live    auf Echtgeld umschalten (fragt nach „ECHTGELD“)
#   --paper   auf Papiermodus umschalten (Simulation mit echten Kursen)
#   --keys    Binance-Schlüssel neu eingeben
#
# Ablauf: Code holen → .env (Schlüssel aus dem alten Bot übernehmen) → Python-Umgebung → Startklar-Prüfung →
# erst wenn die Prüfung bestanden ist: alten Bot abschalten, neuen Dienst und seinen Wächter (alle 5 Minuten) starten.
# Scheitert die Prüfung, bleibt der alte Bot unberührt.
# =============================================================================
set -euo pipefail

BRANCH="ccr-65a9ebf1-h1kqzu"
TARBALL="https://github.com/giafurby/NewTry/archive/refs/heads/${BRANCH}.tar.gz"
APP="/root/newtry"
OLD_ENV="/root/trading-bot/.env"
SERVICE="newtry-bot"
WANT_MODE=""
NEW_KEYS=0

if [[ -t 1 ]]; then G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; B=$'\e[34m'; N=$'\e[0m'; else G=""; Y=""; R=""; B=""; N=""; fi
info() { printf '%s▶%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '%s✔%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s⚠%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '%s✘ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) WANT_MODE="live"; shift ;;
    --paper) WANT_MODE="paper"; shift ;;
    --keys) NEW_KEYS=1; shift ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unbekannte Option: $1 (Hilfe: --help)" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."
command -v python3 >/dev/null || die "python3 fehlt: apt install -y python3 python3-venv"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10 oder neuer nötig."
command -v curl >/dev/null || die "curl fehlt: apt install -y curl"

ask() {   # ask VARIABLE "Frage" [geheim] – liest immer von der Tastatur
  local __ask_input=""
  if [[ "${3:-}" == "geheim" ]]; then
    read -r -s -p "$2" __ask_input < /dev/tty || true
    echo
  else
    read -r -p "$2" __ask_input < /dev/tty || true
  fi
  printf -v "$1" '%s' "$__ask_input"
}

env_value() {   # env_value DATEI SCHLÜSSEL – Wert lesen (Anführungszeichen und Windows-Zeilenenden werden toleriert)
  [[ -f "$1" ]] || return 0
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?${2}[[:space:]]*=[[:space:]]*//p" "$1" | tail -n 1 \
    | tr -d '\r' | sed -E "s/^[\"']//; s/[\"']$//"
}

set_env() {   # set_env SCHLÜSSEL WERT – Zeile in der .env setzen (der Wert erscheint nie auf dem Bildschirm)
  ENV_KEY="$1" ENV_VALUE="$2" python3 - "$APP/.env" <<'PY'
import os, sys
from pathlib import Path
path, key, value = Path(sys.argv[1]), os.environ["ENV_KEY"], os.environ["ENV_VALUE"]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out, done = [], False
for line in lines:
    if line.split("=", 1)[0].strip() == key:
        if not done:
            out.append(f"{key}={value}")
            done = True
        continue
    out.append(line)
if not done:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chmod 600 "$APP/.env"
}

enter_keys() {
  echo
  echo "Binance-API-Schlüssel eingeben (Binance-App → Profil → API-Verwaltung)."
  echo "Rechte: NUR 'Spot- und Margin-Handel', Auszahlungen AUS, IP-Freigabe: $(hostname -I 2>/dev/null | awk '{print $1}')"
  local key="" secret=""
  ask key "API Key: "
  ask secret "Secret Key (unsichtbar beim Tippen): " geheim
  [[ -n "$key" && -n "$secret" ]] || die "Schlüssel leer – abgebrochen."
  set_env BINANCE_API_KEY "$key"
  set_env BINANCE_API_SECRET "$secret"
  ok "Binance-Schlüssel gespeichert."
}

enter_telegram() {
  local token="" chat=""
  ask token "Telegram-Bot-Token (von @BotFather, Enter = ohne Telegram): "
  [[ -n "$token" ]] || return 0
  ask chat "Telegram-Chat-ID (von @userinfobot): "
  set_env TELEGRAM_BOT_TOKEN "$token"
  set_env TELEGRAM_CHAT_ID "$chat"
}

# ----------------------------------------------------------------------------- 1. Code
info "Hole den neuesten Stand von GitHub (${BRANCH}) …"
MAINTENANCE="/var/lib/newtry-watchdog/wartung"     # der Wächter schweigt, solange das Update läuft
mkdir -p "$(dirname "$MAINTENANCE")" && touch "$MAINTENANCE"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"; rm -f "$MAINTENANCE"' EXIT
curl -fsSL "$TARBALL" | tar -xz -C "$tmp" --strip-components=1 || die "Download fehlgeschlagen (Internet?)."
[[ -f "$tmp/bot.py" ]] || die "Download unvollständig."
mkdir -p "$APP"
cp -a "$tmp"/. "$APP"/
mkdir -p "$APP/data"
chmod 700 "$APP/data"
ok "Code liegt in ${APP}."

# ----------------------------------------------------------------------------- 2. Einstellungen
first_install=0
if [[ ! -f "$APP/.env" ]]; then
  first_install=1
  cp "$APP/.env.example" "$APP/.env"
  chmod 600 "$APP/.env"
  if [[ -f "$OLD_ENV" ]]; then
    info "Übernehme Schlüssel und Währung aus dem alten Bot (${OLD_ENV}) …"
    for key in BINANCE_API_KEY BINANCE_API_SECRET TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
      value="$(env_value "$OLD_ENV" "$key")"
      if [[ -n "$value" ]]; then set_env "$key" "$value"; fi
    done
    old_quote="$(env_value "$OLD_ENV" BINANCE_QUOTE_ASSET)"
    if [[ -n "$old_quote" ]]; then set_env QUOTE "$old_quote"; fi
    old_mode="$(env_value "$OLD_ENV" TRADING_MODE)"
    if [[ -n "$old_mode" && "$old_mode" != "live" ]]; then
      warn "Der alte Bot lief im Modus '${old_mode}' – die übernommenen Binance-Schlüssel sind evtl. Testnet-Schlüssel."
    fi
  fi
fi
if [[ "$NEW_KEYS" == 1 ]]; then
  enter_keys
fi
if [[ -z "$(env_value "$APP/.env" TELEGRAM_BOT_TOKEN)" && "$first_install" == 1 ]]; then
  warn "Kein Telegram-Zugang gefunden."
  enter_telegram
fi
# Ältere Installationen: alte Standardwerte auf die neue Strategie umstellen (selbst gewählte Werte bleiben)
if [[ "$first_install" == 0 ]]; then
  if [[ "$(env_value "$APP/.env" DAILY_LOSS_LIMIT_PCT)" == "6" ]]; then
    set_env DAILY_LOSS_LIMIT_PCT 0
    ok "Tageslimit ausgeschaltet (es würde die Crash-Käufe blockieren)."
  fi
  if [[ "$(env_value "$APP/.env" DIP_DROP_PCT)" == "10" ]]; then
    set_env DIP_DROP_PCT 9
    ok "Crash-Kauf schon ab −9 % statt −10 % (im Rückblick mehr Trades und mehr Gewinn bei gleichem Risiko)."
  fi
  old_dd="$(env_value "$APP/.env" MAX_DRAWDOWN_PCT)"
  if [[ "$old_dd" == "25" ]]; then                              # früherer Standard, lockern ist immer sicher
    set_env MAX_DRAWDOWN_PCT 30
    ok "Notstopp von −25 % auf −30 % gesetzt (größter Rückgang im Rückblick 26–28 %; danach 24 h Wartezeit)."
  elif [[ "$old_dd" == "40" ]]; then
    # Senken nur, wenn das Kapital klar innerhalb der neuen Grenze liegt – sonst würde das Update selbst den Notstopp
    # auslösen. Rückgang aus dem Gedächtnis des Bots (Positionen zum Kaufkurs bewertet, daher großer Abstand: 20 %).
    mode_now="$(env_value "$APP/.env" MODE)"
    dd_now="$(python3 - "$APP/data/state-${mode_now:-paper}.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    st = json.load(open(sys.argv[1], encoding="utf-8"))
    peak = float(st.get("peak_equity") or 0)
    equity = float(st.get("last_quote_balance") or 0) + sum(
        float(p.get("amount") or 0) * float(p.get("entry_price") or 0) for p in (st.get("positions") or {}).values())
    if peak > 0 and equity > 0:
        print(f"{max(0.0, (1 - equity / peak) * 100):.1f}")
except Exception:
    pass
PY
)"
    if [[ -n "$dd_now" ]] && python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) < 20 else 1)' "$dd_now"; then
      set_env MAX_DRAWDOWN_PCT 30
      ok "Notstopp von −40 % auf −30 % gesetzt (dein Kapital liegt gerade etwa ${dd_now/./,} % unter dem Höchststand; danach 24 h Wartezeit)."
    else
      if [[ -n "$dd_now" ]]; then
        warn "Notstopp bleibt bei −40 %: Dein Kapital liegt gerade etwa ${dd_now/./,} % unter dem Höchststand – zu nah an 30 %."
      else
        warn "Notstopp bleibt bei −40 %: Der Abstand zum Höchststand ist gerade nicht lesbar."
      fi
      warn "  Empfohlen sind 30 %. Umstellen, sobald /status weniger als 20 % Abstand zeigt:"
      warn "  sed -i 's/^MAX_DRAWDOWN_PCT=.*/MAX_DRAWDOWN_PCT=30/' $APP/.env && systemctl restart newtry-bot"
    fi
  fi
fi
quote="$(env_value "$APP/.env" QUOTE)"
quote="${quote:-USDC}"

current_mode="$(env_value "$APP/.env" MODE)"
if [[ -z "$WANT_MODE" && "$first_install" == 1 ]]; then
  cat <<TEXT

  ${Y}Mit ECHTGELD handeln?${N}
  * Der Bot kauft und verkauft dann mit dem ${quote}-Guthaben auf deinem Binance-Konto.
  * Trend: 1 % Risiko je Trade, höchstens 3 Positionen. Crash-Kauf: 20 % je Kauf, höchstens 3, Notstop −15 %.
  * Notstopp für alles bei −30 % vom Höchststand, danach 24 Stunden Pause (größter Rückgang im Rückblick: 26–28 %).
  * Beim ersten Start macht er einen Funktionstest: Kauf und sofortiger Verkauf für ca. 7 ${quote}.
  * Gewinne sind NICHT garantiert. Setze nur Geld ein, dessen Verlust du verkraften kannst.

TEXT
  answer=""
  ask answer "Tippe ECHTGELD für echtes Geld – oder nur Enter für den Papiermodus (Simulation): "
  if [[ "$answer" == "ECHTGELD" ]]; then WANT_MODE="live"; else WANT_MODE="paper"; fi
elif [[ "$WANT_MODE" == "live" && "$current_mode" != "live" ]]; then
  answer=""
  ask answer "Auf ECHTGELD umschalten? Tippe ECHTGELD: "
  [[ "$answer" == "ECHTGELD" ]] || die "Abgebrochen – nichts umgeschaltet."
fi
if [[ -n "$WANT_MODE" ]]; then set_env MODE "$WANT_MODE"; fi
mode="$(env_value "$APP/.env" MODE)"
if [[ "$mode" == "live" && ( -z "$(env_value "$APP/.env" BINANCE_API_KEY)" || -z "$(env_value "$APP/.env" BINANCE_API_SECRET)" ) ]]; then
  warn "Für Echtgeld fehlen die Binance-Schlüssel."
  enter_keys
fi
ok "Modus: $([[ "$mode" == live ]] && echo "${R}ECHTGELD${N}" || echo "PAPIER (Simulation)") · Währung ${quote}"

# ----------------------------------------------------------------------------- 3. Python
info "Richte die Python-Umgebung ein (1–2 Minuten) …"
if [[ ! -x "$APP/.venv/bin/pip" ]]; then
  rm -rf "$APP/.venv"
  if ! python3 -m venv "$APP/.venv" >/dev/null 2>&1; then
    rm -rf "$APP/.venv"
    apt-get update -qq && apt-get install -y -qq python3-venv >/dev/null
    python3 -m venv "$APP/.venv"
  fi
fi
"$APP/.venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$APP/.venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$APP/requirements.txt"
ok "Python-Umgebung bereit."

# ----------------------------------------------------------------------------- 4. Startklar-Prüfung
info "Startklar-Prüfung: Binance, Kontostand, Schlüsselrechte, Telegram …"
until (cd "$APP" && .venv/bin/python bot.py --check); do
  echo
  warn "Die Prüfung ist nicht bestanden (Grund steht oben). Der alte Bot läuft unverändert weiter."
  choice=""
  ask choice "1 = Binance-Schlüssel neu eingeben · 2 = Telegram neu eingeben · Enter = abbrechen: "
  case "$choice" in
    1) enter_keys ;;
    2) enter_telegram ;;
    *) die "Abgebrochen. Nach dem Beheben einfach erneut starten: bash /root/newtry-install.sh" ;;
  esac
done

# ----------------------------------------------------------------------------- 5. Alten Bot abschalten
for unit in trading-bot.service trading-bot-watchdog.timer trading-bot-watchdog.service trading-dashboard.service; do
  if systemctl cat "$unit" >/dev/null 2>&1; then
    if systemctl is-active --quiet "$unit" || systemctl is-enabled --quiet "$unit" 2>/dev/null; then
      systemctl disable --now "$unit" >/dev/null 2>&1 || systemctl stop "$unit" >/dev/null 2>&1 || true
      ok "Alter Dienst abgeschaltet: ${unit} (Code und Daten in /root/trading-bot bleiben erhalten)"
    fi
  fi
done

# ----------------------------------------------------------------------------- 6. Neuen Dienst starten
cp "$APP/deploy/newtry-bot.service" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
info "Warte 25 Sekunden und prüfe, ob der Bot stabil läuft …"
sleep 25
if ! systemctl is-active --quiet "$SERVICE"; then
  journalctl -u "$SERVICE" -n 40 --no-pager -o cat || true
  die "Der Bot läuft nicht – siehe Protokoll oben."
fi
cp "$APP/deploy/newtry-watchdog.service" /etc/systemd/system/newtry-watchdog.service
cp "$APP/deploy/newtry-watchdog.timer" /etc/systemd/system/newtry-watchdog.timer
systemctl daemon-reload
systemctl enable --now newtry-watchdog.timer >/dev/null 2>&1
ok "Wächter aktiv: prüft alle 5 Minuten, ob der Bot läuft, meldet sich per Telegram und startet ihn bei Bedarf neu."
journalctl -u "$SERVICE" -n 12 --no-pager -o cat || true
echo
ok "NewTry LÄUFT · $([[ "$mode" == live ]] && echo "${R}ECHTGELD${N}" || echo "PAPIERMODUS")"
cat <<TEXT

  In Telegram: Startmeldung$([[ "$mode" == live ]] && echo " und Funktionstest (echter Kauf + Verkauf)"), danach
  nach jedem 4h-Kerzenschluss eine kurze Prüfmeldung und eine Meldung bei jedem Crash-Kauf.
  Befehle: /status /markt /trades /pause /weiter /notverkauf

  Auf dem Server:
    Läuft er?          systemctl is-active ${SERVICE}
    Live-Protokoll     journalctl -u ${SERVICE} -f        (beenden mit Strg+C)
    Anhalten           systemctl disable --now ${SERVICE}   (nur "stop" reicht nicht: dann startet ihn der Wächter neu)
    Wieder starten     systemctl enable --now ${SERVICE}
    Wächter läuft?     systemctl list-timers newtry-watchdog.timer
    Update             bash /root/newtry-install.sh
    Papier/Echtgeld    bash /root/newtry-install.sh --paper   /   --live
TEXT
