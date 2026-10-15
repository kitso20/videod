#!/data/data/com.termux/files/usr/bin/bash
# viDeoD — one-time Termux (Android) setup.
# Usage:  bash termux-setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/4] Installing system packages (python, ffmpeg, rust toolchain)..."
pkg update -y
pkg upgrade -y
pkg install -y python python-pip ffmpeg maturin rust

echo "[2/4] Installing Python packages..."
echo "      pydantic-core compiles from source — the first run takes ~5-15 min."
echo "      Keep the screen on and Termux in the foreground while this runs."
python -m pip install --break-system-packages --upgrade pip
python -m pip install --no-build-isolation --break-system-packages \
  "fastapi==0.115.6" \
  "uvicorn==0.34.0" \
  "yt-dlp>=2025.1.15" \
  "python-multipart==0.0.20"

echo "[3/4] Creating launcher commands..."
APP_DIR="$PWD"
cat > "$PREFIX/bin/videod" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$APP_DIR"
termux-wake-lock >/dev/null 2>&1 || true
echo "viDeoD running at http://127.0.0.1:8765 (Ctrl+C to stop)"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
EOF

cat > "$PREFIX/bin/videod-update" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$APP_DIR"
python -m pip install --no-build-isolation --break-system-packages -U yt-dlp
echo "yt-dlp updated. Restart videod to use it."
EOF

chmod +x "$PREFIX/bin/videod" "$PREFIX/bin/videod-update"

echo "[4/4] Done."
echo
echo "Start the app:  videod"
echo "Update yt-dlp:  videod-update   (run when TikTok/YouTube/etc break)"
echo
echo "IMPORTANT: Android > Settings > Apps > Termux > Battery > Unrestricted,"
echo "otherwise the OS kills downloads when the screen is off."
