"""Writes the state file the bar widget and caption overlay watch.

Same shape as omarchy-voice's feedback.state(): a small JSON blob, written
atomically (tmp file + rename) so the QML FileView watcher never reads a
half-written file.
"""

from __future__ import annotations

import json
import time

from .config import RUNTIME_DIR, STATE_DIR, STATE_FILE

# Reuses omarchy-voice's icon glyphs (same Nerd Font, already proven to
# render in the bar) rather than picking new ones sight-unseen.
ICONS = {
    "stopped": "󰍭",
    "loading": "󱚟",
    "idle": "󰍬",
    "listening": "󰍬",
    "processing": "󱚟",
    "error": "󰍭",
}


def write(status: str, text: str = "") -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "icon": ICONS.get(status, ICONS["idle"]),
        "text": text,
        "updated": time.time(),
    }
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(STATE_FILE)
