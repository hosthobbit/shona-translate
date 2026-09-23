"""Last few translations, each with its recording, so a turn can be
replayed or its text copied out after the caption card has faded.

Written atomically (tmp + rename) for the same reason status.py is: the
history panel's QML FileView watches this file and must never catch it
half-written.
"""

from __future__ import annotations

import json
import time
import uuid

import numpy as np

from .audio import save_wav
from .config import HISTORY_DIR, HISTORY_FILE, HISTORY_LIMIT


def add(shona_text: str, english_text: str, audio: np.ndarray) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    entry_id = uuid.uuid4().hex[:12]
    wav_path = HISTORY_DIR / f"{entry_id}.wav"
    save_wav(wav_path, audio)

    entries = _read()
    entries.insert(0, {
        "id": entry_id,
        "updated": time.time(),
        "shona": shona_text,
        "english": english_text,
        "wav": str(wav_path),
    })

    # Prune anything past the limit, and delete its recording too — otherwise
    # the wav files would outlive the entries that reference them forever.
    keep, drop = entries[:HISTORY_LIMIT], entries[HISTORY_LIMIT:]
    for stale in drop:
        try:
            HISTORY_DIR.joinpath(f"{stale['id']}.wav").unlink(missing_ok=True)
        except OSError:
            pass

    _write(keep)


def _read() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _write(entries: list[dict]) -> None:
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries))
    tmp.replace(HISTORY_FILE)
