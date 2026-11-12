#!/usr/bin/env bash
# Lädt die Kursdaten (Binance, 10 Coins, 2017–2026) aus dem öffentlichen Datensatz Speirsy11/crypto-dataset (CC0)
# und prüft jede Datei gegen die SHA-256-Prüfsumme im Repository.
#   bash research/download.sh <Zielordner>           15m, 1h, 1d
#   bash research/download.sh <Zielordner> 1m        1-Minuten-Daten (≈ 800 MB) zusätzlich, für lab/load_1m.py
# Danach: python -I research/load.py <Zielordner>/raw <Zielordner>/cache   (Ordner der Daten nie als Arbeitsordner nutzen)
set -euo pipefail
OUT="${1:?Zielordner angeben}"
INTERVALS="${2:-1h 15m 1d}"
mkdir -p "$OUT"
SRC="$OUT/crypto-dataset"
if [[ ! -d "$SRC/.git" ]]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/Speirsy11/crypto-dataset "$SRC"
fi
REF="$(git -C "$SRC" rev-parse HEAD)"
LIST="$OUT/filelist.txt"
for i in $INTERVALS; do
  find "$SRC/data/interval_id=$i" -name '*.parquet' | sort | while read -r f; do
    printf '%s %s\n' "${f#"$SRC"/}" "$(sed -n 's/^oid sha256://p' "$f")"
  done
done > "$LIST"
fetch() {
  local rel="$1" oid="$2" out="$OUT/raw/$1"
  mkdir -p "$(dirname "$out")"
  if [[ -f "$out" ]] && echo "$oid  $out" | sha256sum -c --quiet >/dev/null 2>&1; then return 0; fi
  for try in 1 2 3; do
    if curl -sS -L -m 120 -o "$out" "https://media.githubusercontent.com/media/Speirsy11/crypto-dataset/$REF/$rel" \
       && echo "$oid  $out" | sha256sum -c --quiet >/dev/null 2>&1; then return 0; fi
    sleep $((try * 3))
  done
  echo "FEHLER $rel"; rm -f "$out"
}
export -f fetch
export OUT REF
xargs -P 8 -n 2 bash -c 'fetch "$0" "$1"' < "$LIST"
done_count=0
while read -r rel _oid; do
  if [[ -f "$OUT/raw/$rel" ]]; then done_count=$((done_count + 1)); fi
done < "$LIST"
echo "Fertig ($INTERVALS): $done_count Dateien geprüft (erwartet: $(wc -l < "$LIST"))."
