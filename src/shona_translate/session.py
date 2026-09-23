"""Unix control socket shared by the daemon and the CLI / bar widget.

`shona-translate toggle` (and the bar-widget click) talk to the running
daemon through this socket rather than launching a fresh process per click —
the whisper model stays loaded on the GPU between clicks, which is most of
why this feels instant.
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
from typing import Callable

from .config import RUNTIME_DIR, SOCKET_PATH, dir_is_private


class ControlServer:
    """A tiny Unix socket so a keybinding/click can talk to a running daemon."""

    def __init__(self, handler: Callable[[str], str]):
        self.handler = handler
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        try:
            RUNTIME_DIR.chmod(0o700)
        except OSError:
            pass
        if not dir_is_private(RUNTIME_DIR):
            raise PermissionError(
                f"{RUNTIME_DIR} is not owner-only (mode 700); refusing to bind "
                "an unauthenticated control socket")
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with contextlib.suppress(OSError):
            SOCKET_PATH.unlink()

    def _serve(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            SOCKET_PATH.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET_PATH))
        try:
            os.chmod(SOCKET_PATH, 0o600)
        except OSError:
            server.close()
            with contextlib.suppress(OSError):
                SOCKET_PATH.unlink()
            raise
        server.listen(4)
        server.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                try:
                    command = conn.recv(65536).decode().strip()
                except (OSError, UnicodeError):
                    continue
                try:
                    reply = self.handler(command)
                except Exception as exc:  # a bad control message must not kill the daemon
                    reply = f"error: {type(exc).__name__}: {exc}"
                with contextlib.suppress(OSError):
                    conn.sendall(reply.encode())
        server.close()
        with contextlib.suppress(FileNotFoundError):
            SOCKET_PATH.unlink()


def daemon_running() -> bool:
    """A socket file can outlive the daemon that made it, so connect to check."""
    if not SOCKET_PATH.exists():
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(str(SOCKET_PATH))
        return True
    except OSError:
        with contextlib.suppress(OSError):
            SOCKET_PATH.unlink()
        return False
    finally:
        probe.close()


def send_control(command: str, timeout: float = 5.0) -> str:
    """Talk to a running daemon from the CLI/bar widget."""
    if not daemon_running():
        raise ConnectionError("no shona-translate daemon is running")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(str(SOCKET_PATH))
    client.sendall(command.encode())
    reply = client.recv(65536).decode()
    client.close()
    return reply
