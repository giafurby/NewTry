#!/usr/bin/env bash
# =============================================================================
# Wächter für den NewTry-Bot – läuft alle 5 Minuten (newtry-watchdog.timer).
#
# Alarm per Telegram (derselbe Alarm höchstens stündlich, Entwarnung sobald alles wieder läuft), wenn
#   * der Dienst newtry-bot eingeschaltet ist, aber nicht läuft (Absturz, Startfehler),
#   * er läuft, sein Lebenszeichen (data/heartbeat) aber älter als 10 Minuten ist (Bot hängt),
#   * die Festplatte zu mindestens 90 % voll ist.
# Läuft der Bot nicht oder hängt er, startet der Wächter ihn neu – höchstens einmal pro Stunde.
# Kein Alarm, wenn du den Bot bewusst abgeschaltet hast (systemctl disable --now newtry-bot) oder während eines Updates.
#
# Liest TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID aus der .env, zeigt sie nie an und übergibt sie nicht als Argument.
# =============================================================================
set -uo pipefail

APP="${NEWTRY_DIR:-/root/newtry}"
SERVICE="${NEWTRY_SERVICE:-newtry-bot}"
STATE_DIR="${WATCHDOG_STATE_DIR:-/var/lib/newtry-watchdog}"
MAX_HEARTBEAT_AGE="${WATCHDOG_MAX_AGE:-600}"     # Sekunden ohne Lebenszeichen, bis "hängt" gemeldet wird
STARTUP_GRACE="${WATCHDOG_GRACE:-600}"           # nach einem (Neu-)Start so lange keine Lebenszeichen-Prüfung
DISK_LIMIT="${WATCHDOG_DISK_LIMIT:-90}"          # Prozent
REPEAT_SECONDS=3600                              # derselbe Alarm höchstens stündlich
RESTART_PAUSE=3600                               # höchstens ein Neustart pro Stunde
MAINTENANCE_SECONDS=1800                         # Wartungsmarke (Update) gilt höchstens so lange

ENV_FILE="${APP}/.env"
HEARTBEAT="${APP}/data/heartbeat"
ALARM_FILE="${STATE_DIR}/alarm"
RESTART_FILE="${STATE_DIR}/neustart"
MAINTENANCE_FILE="${STATE_DIR}/wartung"
mkdir -p "$STATE_DIR"
now="$(date +%s)"

env_value() {
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?${1}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" 2>/dev/null | tail -n 1 \
    | tr -d '\r' | sed -E "s/^[\"']//; s/[\"']$//"
}

send_telegram() {
  local token chat
  token="$(env_value TELEGRAM_BOT_TOKEN)"
  chat="$(env_value TELEGRAM_CHAT_ID)"
  if [[ -z "$token" || -z "$chat" ]]; then
    echo "Telegram nicht eingerichtet – Meldung nur im Systemprotokoll: $1" >&2
    return 1
  fi
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" \
    | curl -s -m 20 --config - --data-urlencode "chat_id=${chat}" --data-urlencode "text=$1" -o /dev/null
}

if [[ -f "$MAINTENANCE_FILE" ]] && (( now - $(stat -c %Y "$MAINTENANCE_FILE") < MAINTENANCE_SECONDS )); then
  exit 0                                          # Update läuft
fi

problems=()
kinds=()
restart=0
enabled="$(systemctl is-enabled "$SERVICE" 2>/dev/null || true)"
active="$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
if [[ "$active" != "active" && "$active" != "activating" && "$active" != "reloading" ]]; then
  if [[ "$enabled" == "enabled" ]]; then
    problems+=("Der Bot läuft nicht (Status: ${active:-unbekannt}).")
    kinds+=("aus")
    restart=1
  fi
else
  since="$(systemctl show "$SERVICE" -p ActiveEnterTimestamp --value 2>/dev/null || true)"
  since_s="$(date -d "$since" +%s 2>/dev/null || echo "$now")"
  if (( now - since_s > STARTUP_GRACE )); then
    if [[ -f "$HEARTBEAT" ]]; then
      age=$(( now - $(stat -c %Y "$HEARTBEAT") ))
    else
      age=$(( now - since_s ))
    fi
    if (( age > MAX_HEARTBEAT_AGE )); then
      problems+=("Der Bot reagiert nicht mehr: letztes Lebenszeichen vor $(( age / 60 )) Minuten.")
      kinds+=("haengt")
      restart=1
    fi
  fi
fi
disk="$(df -P "$APP" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')"
if [[ -n "$disk" ]] && (( disk >= DISK_LIMIT )); then
  problems+=("Die Festplatte ist zu ${disk} % voll.")
  kinds+=("platte")
fi

if (( ${#problems[@]} == 0 )); then
  if [[ -f "$ALARM_FILE" ]]; then
    send_telegram "✅ NewTry-Wächter: Alles wieder in Ordnung – der Bot läuft." && rm -f "$ALARM_FILE"
  fi
  exit 0
fi

action=""
if (( restart )); then
  last_restart=0
  [[ -f "$RESTART_FILE" ]] && last_restart="$(stat -c %Y "$RESTART_FILE")"
  if (( now - last_restart >= RESTART_PAUSE )); then
    touch "$RESTART_FILE"
    if systemctl restart "$SERVICE" >/dev/null 2>&1; then
      action=" Ich habe ihn neu gestartet."
    else
      action=" Der Neustart ist fehlgeschlagen."
    fi
  else
    action=" Ein Neustart wurde in der letzten Stunde schon versucht."
  fi
fi
key="${kinds[*]}"
message="🚨 NewTry-Wächter: ${problems[*]}${action} Prüfen auf dem Server: journalctl -u ${SERVICE} -n 50 --no-pager"
previous=""
last_alarm=0
if [[ -f "$ALARM_FILE" ]]; then
  previous="$(cat "$ALARM_FILE")"
  last_alarm="$(stat -c %Y "$ALARM_FILE")"
fi
if [[ "$previous" != "$key" ]] || (( now - last_alarm >= REPEAT_SECONDS )); then
  send_telegram "$message" || true
  printf '%s' "$key" > "$ALARM_FILE"
fi
echo "$message" >&2
exit 0
