#!/usr/bin/env bash
# Installs shona-translate: a venv under ~/.local/share, a launcher symlinked
# into ~/.local/bin, the quickshell bar-widget + caption plugins under
# ~/.config/omarchy/plugins, and a systemd --user service that keeps the
# model loaded on the GPU in the background.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$HOME/.local/share/shona-translate"
BINDIR="$HOME/.local/bin"
PLUGINDIR="$HOME/.config/omarchy/plugins"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "==> Installing shona-translate to $PREFIX"

mkdir -p "$PREFIX"
rsync -a --delete "$ROOT/src" "$ROOT/bin" "$PREFIX/"
chmod +x "$PREFIX/bin/shona-translate"

if [ ! -d "$PREFIX/venv" ]; then
  echo "==> Creating venv"
  python3 -m venv "$PREFIX/venv"
fi

echo "==> Installing Python dependencies (this downloads several hundred MB of CUDA libraries on first run)"
"$PREFIX/venv/bin/pip" install --upgrade pip -q
"$PREFIX/venv/bin/pip" install -q \
  faster-whisper sounddevice numpy \
  nvidia-cublas-cu12 nvidia-cudnn-cu12

# The Shona->English text-translation model runs on CPU (see engine.py) —
# it's a small model translating one short sentence at a time, and keeping
# it off the GPU avoids VRAM contention with Whisper on this box's 8GB card.
# The CPU-only wheel is a fraction of the size of the CUDA build, since it
# skips bundling a duplicate set of nvidia-*-cu12 libraries.
"$PREFIX/venv/bin/pip" install -q \
  --index-url https://download.pytorch.org/whl/cpu torch
"$PREFIX/venv/bin/pip" install -q transformers sentencepiece

echo "==> Linking $BINDIR/shona-translate"
mkdir -p "$BINDIR"
ln -sf "$PREFIX/bin/shona-translate" "$BINDIR/shona-translate"

echo "==> Installing quickshell plugins"
mkdir -p "$PLUGINDIR"
rsync -a --delete "$ROOT/plugin/shona.indicator" "$PLUGINDIR/"
rsync -a --delete "$ROOT/plugin/shona.caption" "$PLUGINDIR/"
rsync -a --delete "$ROOT/plugin/shona.settings" "$PLUGINDIR/"
rsync -a --delete "$ROOT/plugin/shona.history" "$PLUGINDIR/"

echo "==> Installing systemd user service"
mkdir -p "$SYSTEMD_USER_DIR"
cp "$ROOT/share/shona-translate.service" "$SYSTEMD_USER_DIR/shona-translate.service"

systemctl --user daemon-reload
systemctl --user enable --now shona-translate.service

if command -v omarchy-shell >/dev/null 2>&1; then
  echo "==> Enabling plugins in the running Omarchy shell"
  omarchy-shell -q shell putBarWidget shona.indicator '{"section":"right"}' || true
  omarchy-shell -q shell setPluginEnabled shona.caption true || true
  omarchy-shell -q shell setPluginEnabled shona.settings true || true
fi

cat <<'EOF'

==> Installed.

First launch downloads the large-v3 Whisper model (~3GB) — check progress with:
  journalctl --user -u shona-translate -f

If the mic icon isn't in the bar yet (e.g. Omarchy's shell wasn't running
during install), enable it yourself:
  omarchy-shell shell putBarWidget shona.indicator '{"section":"right"}'
  omarchy-shell shell setPluginEnabled shona.caption true
  omarchy-shell shell setPluginEnabled shona.settings true

Left-click the mic icon in the bar to start listening in Shona, click again
to translate. The result also shows in a small overlay above the bar for a
few seconds. Right-click the mic icon for a settings panel to test and pick
which microphone it uses.

Manage the daemon:
  systemctl --user status shona-translate
  systemctl --user restart shona-translate
  systemctl --user stop shona-translate
EOF
