"""Microphone capture for one push-to-talk turn.

Records at 48kHz — PipeWire's native rate, and the only rate most of this
machine's input devices will open at directly — then downsamples to the
16kHz Whisper expects. Records mono float32 throughout.
"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from .config import DEVICE_SAMPLE_RATE, MAX_RECORDING_SECONDS, SAMPLE_RATE


def save_wav(path: Path, audio: np.ndarray, samplerate: int = SAMPLE_RATE) -> None:
    """16-bit PCM, so `paplay`/any player can open it with no extra args."""
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(samplerate)
        wav.writeframes(pcm16.tobytes())


def _downsample_to_whisper_rate(audio: np.ndarray) -> np.ndarray:
    """48kHz -> 16kHz by averaging groups of 3 samples (an exact integer ratio).

    A plain box-average acts as a cheap low-pass before the implied decimation,
    which is enough for speech-grade audio without pulling in scipy just for
    a 3:1 resample.
    """
    ratio = DEVICE_SAMPLE_RATE // SAMPLE_RATE
    usable = (len(audio) // ratio) * ratio
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    return audio[:usable].reshape(-1, ratio).mean(axis=1).astype(np.float32)


def list_device_names() -> list[str]:
    """Input device names, in the same form `pactl list sources` shows them."""
    names = []
    jack = _jack_hostapi_index()
    for idx in range(len(sd.query_devices())):
        info = sd.query_devices(idx)
        if info["max_input_channels"] >= 1 and info["hostapi"] == jack:
            names.append(info["name"])
    return names


def record_with_level(device: str | None, seconds: float, level_path: Path) -> np.ndarray:
    """Record from one device, updating level_path a few times a second.

    Used by the mic picker's live meter: level_path is watched by the QML
    panel while a test is running, separately from the (bursty) final result.
    """
    frames: list[np.ndarray] = []
    lock = threading.Lock()
    last_write = 0.0

    def callback(indata, count, time_info, status) -> None:
        nonlocal last_write
        with lock:
            frames.append(indata[:, 0].copy())
        now = time.monotonic()
        if now - last_write >= 0.05:
            last_write = now
            peak = float(np.abs(indata).max())
            tmp = level_path.with_suffix(".tmp")
            tmp.write_text(f"{peak:.4f}")
            tmp.replace(level_path)

    stream = sd.InputStream(
        samplerate=DEVICE_SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=device,
        callback=callback,
    )
    with stream:
        sd.sleep(int(seconds * 1000))
    with lock:
        collected = frames
    if not collected:
        return np.zeros(0, dtype=np.float32)
    return _downsample_to_whisper_rate(np.concatenate(collected))


def probe_devices(seconds: float = 1.5) -> list[tuple[str, float, float]]:
    """Briefly record every named input device and report its level.

    Named devices here come through PipeWire's JACK-compat host API, so
    "USB 2.0 Camera Mono" or "PCM2902 Audio Codec Analog Stereo" match the
    same names `pactl list sources` shows. Useful for spotting a mic that's
    quietly picking up more room noise than voice: run this, say something
    normally, and see which device's peak actually moves.
    """
    results = []
    for idx in range(len(sd.query_devices())):
        info = sd.query_devices(idx)
        if info["max_input_channels"] < 1 or info["hostapi"] != _jack_hostapi_index():
            continue
        name = info["name"]
        try:
            rec = sd.rec(
                int(seconds * DEVICE_SAMPLE_RATE),
                samplerate=DEVICE_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=idx,
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
            peak = float(np.abs(rec).max())
        except Exception:
            rms, peak = -1.0, -1.0
        results.append((name, rms, peak))
    return results


def _jack_hostapi_index() -> int:
    for i, api in enumerate(sd.query_hostapis()):
        if "JACK" in api["name"]:
            return i
    return -1


class Recorder:
    """Start it, talk, stop it, get back one 16kHz mono numpy array."""

    def __init__(self, device: str | None = None) -> None:
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._auto_stop: threading.Timer | None = None
        self.on_max_duration = None  # set by caller: called if the safety valve trips

    def _callback(self, indata, frames, time_info, status) -> None:
        with self._lock:
            self._frames.append(indata[:, 0].copy())

    def start(self) -> None:
        with self._lock:
            self._frames = []
        self._stream = sd.InputStream(
            samplerate=DEVICE_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        self._auto_stop = threading.Timer(MAX_RECORDING_SECONDS, self._trip_safety_valve)
        self._auto_stop.daemon = True
        self._auto_stop.start()

    def _trip_safety_valve(self) -> None:
        if self.on_max_duration is not None:
            self.on_max_duration()

    def stop(self) -> np.ndarray:
        if self._auto_stop is not None:
            self._auto_stop.cancel()
            self._auto_stop = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return _downsample_to_whisper_rate(np.concatenate(frames))
