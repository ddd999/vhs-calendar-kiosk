#!/usr/bin/env bash
# Deploy the laser kiosk on Raspberry Pi OS Trixie (Debian 13, labwc).
# Usage: ./deploy.sh [--no-kiosk]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8000
TAG="# laser-kiosk"
KIOSK=1
[[ "${1:-}" == "--no-kiosk" ]] && KIOSK=0

if [[ $EUID -eq 0 ]]; then
  echo "Run this as your normal user, not root (it uses sudo where needed)." >&2
  exit 1
fi

for f in index.html update_calendar.py; do
  [[ -f "$APP_DIR/$f" ]] || { echo "Missing $f in $APP_DIR" >&2; exit 1; }
done

echo "==> Installing system packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv cron curl
if [[ $KIOSK -eq 1 ]]; then
  sudo apt-get install -y chromium
fi

# Trixie doesn't always ship or enable cron by default
sudo systemctl enable --now cron

echo "==> Creating Python virtualenv and installing dependencies"
# Trixie's system Python is "externally managed" (PEP 668), so use a venv
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install icalendar recurring-ical-events

echo "==> Installing crontab entries"
PY="$APP_DIR/.venv/bin/python"
# Keep existing entries, drop any previous laser-kiosk ones (idempotent re-runs)
EXISTING="$(crontab -l 2>/dev/null | grep -v -F "$TAG" || true)"
{
  if [[ -n "$EXISTING" ]]; then printf '%s\n' "$EXISTING"; fi
  echo "* * * * * $PY $APP_DIR/update_calendar.py 2>&1 | logger -t laser-kiosk $TAG"
  echo "@reboot cd $APP_DIR && /usr/bin/python3 -m http.server $PORT --bind 127.0.0.1 >/dev/null 2>&1 $TAG"
} | crontab -

echo "==> Running the updater once to create status.json"
"$PY" "$APP_DIR/update_calendar.py" || echo "WARNING: updater failed; check the iCal URL in update_calendar.py"

echo "==> Starting the web server now (it will also start on boot)"
if ! curl -fs "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
  (cd "$APP_DIR" && nohup /usr/bin/python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &)
fi

if [[ $KIOSK -eq 1 ]]; then
  echo "==> Writing kiosk.sh"
 cat > "$APP_DIR/kiosk.sh" <<EOF
#!/usr/bin/env bash
# Wait for the local web server
until curl -fs http://127.0.0.1:$PORT/ >/dev/null 2>&1; do sleep 1; done

# Wait up to 60 s for the network/DNS to come up
for i in \$(seq 1 60); do
  getent hosts calendar.google.com >/dev/null 2>&1 && break
  sleep 1
done

# Refresh the data once so the first screen is current
$APP_DIR/.venv/bin/python $APP_DIR/update_calendar.py || true

exec chromium --kiosk --noerrdialogs --disable-infobars --password-store=basic \\
  --check-for-update-interval=31536000 http://127.0.0.1:$PORT/
EOF
  chmod +x "$APP_DIR/kiosk.sh"

  echo "==> Configuring labwc autostart"
  AUTOSTART="$HOME/.config/labwc/autostart"
  mkdir -p "$(dirname "$AUTOSTART")"
  touch "$AUTOSTART"
  grep -v -F "$TAG" "$AUTOSTART" > "$AUTOSTART.tmp" || true
  echo "$APP_DIR/kiosk.sh & $TAG" >> "$AUTOSTART.tmp"
  mv "$AUTOSTART.tmp" "$AUTOSTART"

  echo "==> Installing blank cursor theme"
  mkdir -p "$HOME/.icons/blank/cursors"
  printf '[Icon Theme]\nName=blank\n' > "$HOME/.icons/blank/index.theme"
  python3 - <<'PYEOF'
import struct, os
img = struct.pack("<9I", 36, 0xfffd0002, 1, 1, 1, 1, 0, 0, 0) + struct.pack("<I", 0)
hdr = b"Xcur" + struct.pack("<3I", 16, 0x10000, 1) + struct.pack("<3I", 0xfffd0002, 1, 28)
d = os.path.expanduser("~/.icons/blank/cursors")
open(f"{d}/left_ptr", "wb").write(hdr + img)
for n in ["default","arrow","pointer","hand1","hand2","text","xterm","watch","wait",
          "crosshair","grab","grabbing","move","fleur","top_left_arrow","progress"]:
    p = f"{d}/{n}"
    if not os.path.lexists(p):
        os.symlink("left_ptr", p)
PYEOF

  ENVF="$HOME/.config/labwc/environment"
  touch "$ENVF"
  sed -i '/^XCURSOR_THEME=/d;/^XCURSOR_SIZE=/d' "$ENVF"
  printf 'XCURSOR_THEME=blank\nXCURSOR_SIZE=1\n' >> "$ENVF"

  # Disable screen blanking
  sudo raspi-config nonint do_blanking 1 || true
fi

echo
echo "Done."
echo "  Cron:    crontab -l"
echo "  Logs:    journalctl -t laser-kiosk"
echo "  Status:  cat $APP_DIR/status.json"
if [[ $KIOSK -eq 1 ]]; then
  echo "  Reboot to start the kiosk: sudo reboot"
fi
