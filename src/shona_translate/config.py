"""Configuration and well-known paths.

Mirrors the omarchy-voice layout so the two tools feel like one family:
XDG runtime dir for the socket/state file (never /tmp — that's world
writable and the socket would be an unauthenticated local backdoor),
XDG state dir for logs.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_FILE = CONFIG_HOME / "shona-translate" / "config.toml"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def _runtime_dir() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "shona-translate"
    return STATE_HOME / "shona-translate" / "run"


RUNTIME_DIR = _runtime_dir()
STATE_DIR = STATE_HOME / "shona-translate"
SOCKET_PATH = RUNTIME_DIR / "control.sock"
STATE_FILE = RUNTIME_DIR / "state.json"
LOG_FILE = STATE_DIR / "session.log"

# Mic-picker panel: device list + last test result, and a fast-changing
# level file (its own file, like omarchy-voice's, so a 60ms poll for a live
# meter doesn't have to re-arm a watch on every frame).
DEVICES_FILE = RUNTIME_DIR / "devices.json"
MIC_TEST_FILE = RUNTIME_DIR / "mic-test.json"
MIC_TEST_WAV = RUNTIME_DIR / "mic-test.wav"
LEVEL_FILE = RUNTIME_DIR / "level"
MIC_TEST_SECONDS = 3.0

# Recent-translations panel: last HISTORY_LIMIT turns, each with its own
# recording. Lives under STATE_HOME (not RUNTIME_DIR) on purpose — it should
# survive a reboot, the way the session log does, rather than living on
# tmpfs and vanishing with it.
HISTORY_DIR = STATE_DIR / "history"
HISTORY_FILE = STATE_DIR / "history.json"
HISTORY_LIMIT = 10

# Fixed on purpose: this tool only ever transcribes Shona and only ever
# outputs English. No language auto-detection, no other target language.
SOURCE_LANGUAGE = "sn-ZW"  # Google STT's BCP-47 code, not ISO 639-1 "sn"

# Speech-to-text step. Was faster-whisper (large-v3) running locally, but
# generic Whisper has almost no real Shona in its training data and it
# showed: garbled transcripts, and a tendency to hallucinate fluent-sounding
# English (classically "Thank you for watching") on any clip it couldn't
# make out, rather than admitting it couldn't hear it. Tested head to head
# against the same real recordings, Google's Speech-to-Text API produced
# fluent, correct-reading Shona on most clips, and on the few it couldn't
# parse confidently, returned nothing rather than a wrong confident guess.
# Costs money past 60 free minutes/month; needs an API key with the Cloud
# Speech-to-Text API enabled, restricted to that API.
GOOGLE_SPEECH_KEY_FILE = CONFIG_HOME / "shona-translate" / "google-speech-key"


def google_speech_key() -> str:
    try:
        key = GOOGLE_SPEECH_KEY_FILE.read_text().strip()
    except OSError:
        return ""
    return key

# Text-translation step (Shona text -> English text), run after Whisper's
# transcription rather than relying on Whisper's own audio "translate" task
# — see engine.py for why. NLLB-200's FLORES-200 codes, not ISO 639-1.
MT_MODEL_NAME = "facebook/nllb-200-distilled-1.3B"
MT_SOURCE_LANG = "sna_Latn"
MT_TARGET_LANG = "eng_Latn"
# The same NLLB weights converted to CTranslate2's format, so they can run on
# the GPU (which sits idle now transcription is Google's) without a CUDA
# build of torch. Converted from the Hugging Face cache on first start.
MT_CT2_DIR = DATA_HOME / "shona-translate" / "models" / "nllb-200-distilled-1.3B-ct2"
SAMPLE_RATE = 16000
DEVICE_SAMPLE_RATE = 48000  # PipeWire's native rate; recorded here then downsampled
MAX_RECORDING_SECONDS = 90  # safety valve if stop is somehow never sent


def input_device() -> str | None:
    """The mic to record from, by PortAudio device name.

    None means "whatever PipeWire's default source is". Pin a specific mic in
    ~/.config/shona-translate/config.toml:

        device = "PCM2902 Audio Codec Analog Stereo"

    Run `shona-translate mics` to see the available names and how loud each
    one currently is — useful when the system default turns out to be a
    webcam or another mic that's picking up more room noise than your voice.
    """
    try:
        data = tomllib.loads(CONFIG_FILE.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    device = data.get("device")
    return str(device) if device else None


def set_input_device(name: str) -> None:
    """Persist the chosen mic. This is the only setting, so the file is just this."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(f'device = "{name}"\n')


def dir_is_private(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return (mode & 0o077) == 0
