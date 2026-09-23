"""The long-running process: loads the model once, then answers clicks.

State machine is deliberately small: idle -> listening -> processing -> idle.
Recording and translating both happen off the control-socket thread so a
click is answered immediately and the bar never blocks waiting on the GPU.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
import time
import traceback

import numpy as np

from .audio import Recorder, list_device_names, record_with_level, save_wav
from .config import (
    DEVICES_FILE,
    LEVEL_FILE,
    LOG_FILE,
    MIC_TEST_FILE,
    MIC_TEST_SECONDS,
    MIC_TEST_WAV,
    RUNTIME_DIR,
    STATE_DIR,
    input_device,
    set_input_device,
)
from .engine import Engine
from .session import ControlServer
from . import history, status


def _write_json(path, payload: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


def _log(line: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


class Daemon:
    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self._phase = "loading"  # loading -> idle -> listening -> processing -> idle
        self._recorder = Recorder(device=input_device())
        self._recorder.on_max_duration = self._max_duration_reached
        self._engine: Engine | None = None
        self._server = ControlServer(self._handle)
        self._stop_event = threading.Event()

    # -- lifecycle ------------------------------------------------------

    def run(self) -> int:
        status.write("loading")
        _log(f"mic: {self._recorder.device or 'system default'}")
        self._write_devices()
        self._server.start()
        signal.signal(signal.SIGTERM, lambda *_: self._stop_event.set())
        signal.signal(signal.SIGINT, lambda *_: self._stop_event.set())
        try:
            _log("loading model")
            self._engine = Engine()
            with self._state_lock:
                self._phase = "idle"
            status.write("idle")
            _log("model loaded, ready")
        except Exception as exc:
            _log(f"model load failed: {exc}\n{traceback.format_exc()}")
            status.write("error", f"model failed to load: {exc}")
            return 1
        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)
        self._server.stop()
        status.write("stopped")
        return 0

    # -- control socket handler -----------------------------------------

    def _handle(self, command: str) -> str:
        command = command.strip()
        if command == "toggle":
            return self._toggle()
        if command == "quit":
            self._stop_event.set()
            return "ok: stopping"
        if command == "status":
            with self._state_lock:
                return self._phase
        if command == "devices":
            self._write_devices()
            return "ok"
        if command.startswith("test-mic "):
            return self._test_mic(command[len("test-mic "):])
        if command.startswith("set-device "):
            return self._set_device(command[len("set-device "):])
        return f"error: unknown command {command!r}"

    def _write_devices(self) -> None:
        try:
            names = list_device_names()
        except Exception as exc:
            _log(f"device list failed: {exc}")
            names = []
        _write_json(DEVICES_FILE, {
            "current": self._recorder.device,
            "devices": names,
            "updated": time.time(),
        })

    def _test_mic(self, name: str) -> str:
        with self._state_lock:
            # Microphone capture does not use either translation model.
            # Keep tests available while those models load or download.
            if self._phase not in ("idle", "loading"):
                return "error: busy, try again once the current recording finishes"
        try:
            audio = record_with_level(name, MIC_TEST_SECONDS, LEVEL_FILE)
            peak = float(np.abs(audio).max()) if audio.size else 0.0
            save_wav(MIC_TEST_WAV, audio)
        except Exception as exc:
            _log(f"mic test failed for {name!r}: {exc}\n{traceback.format_exc()}")
            return f"error: {exc}"
        subprocess.Popen(
            ["paplay", str(MIC_TEST_WAV)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _write_json(MIC_TEST_FILE, {
            "device": name, "peak": peak, "wav": str(MIC_TEST_WAV), "updated": time.time(),
        })
        _log(f"mic test: {name} peak={peak:.3f}")
        return f"ok: peak={peak:.3f}"

    def _set_device(self, name: str) -> str:
        set_input_device(name)
        self._recorder.device = name
        self._write_devices()
        _log(f"mic set to: {name}")
        return "ok"

    def _toggle(self) -> str:
        with self._state_lock:
            phase = self._phase
            if phase == "loading":
                return "error: model still loading"
            if phase == "processing":
                return "error: still translating the last clip, hang on"
            if phase == "idle":
                self._phase = "listening"
                start_listening = True
            else:  # listening
                self._phase = "processing"
                start_listening = False
        if start_listening:
            self._recorder.start()
            status.write("listening")
            _log("listening")
            return "ok: listening"
        threading.Thread(target=self._finish_and_translate, daemon=True).start()
        return "ok: translating"

    def _max_duration_reached(self) -> None:
        with self._state_lock:
            if self._phase != "listening":
                return
            self._phase = "processing"
        _log("max recording length reached, translating")
        self._finish_and_translate()

    def _finish_and_translate(self) -> None:
        status.write("processing")
        audio = self._recorder.stop()
        try:
            assert self._engine is not None
            shona_text, text = self._engine.transcribe_and_translate(audio)
        except Exception as exc:
            _log(f"translate failed: {exc}\n{traceback.format_exc()}")
            with self._state_lock:
                self._phase = "idle"
            status.write("error", f"translation failed: {exc}")
            return
        if not text:
            text = "(no speech detected)"
        _log(f"heard: {shona_text!r} -> translated: {text!r}")
        if shona_text:
            try:
                history.add(shona_text, text, audio)
            except Exception as exc:
                _log(f"history save failed: {exc}\n{traceback.format_exc()}")
        with self._state_lock:
            self._phase = "idle"
        status.write("idle", text)


def main() -> int:
    return Daemon().run()


if __name__ == "__main__":
    sys.exit(main())
