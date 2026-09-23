"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import config as cfg
from .session import daemon_running, send_control


def cmd_run(_args) -> int:
    from .daemon import main as daemon_main
    return daemon_main()


def cmd_toggle(_args) -> int:
    try:
        print(send_control("toggle"))
    except (ConnectionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_quit(_args) -> int:
    try:
        print(send_control("quit"))
    except (ConnectionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_mics(args) -> int:
    from .audio import probe_devices
    from .config import input_device

    current = input_device()
    print(f"Currently pinned device: {current or '(system default)'}")
    print(f"Recording {args.seconds}s from each input device — stay quiet, then talk...")
    print()
    for name, rms, peak in probe_devices(seconds=args.seconds):
        marker = " <- in use" if name == current else ""
        if rms < 0:
            print(f"  {name:42s}  (could not open){marker}")
        else:
            bar = "#" * min(40, int(peak * 40))
            print(f"  {name:42s}  peak={peak:.3f}  {bar}{marker}")
    print()
    print("Pin one in ~/.config/shona-translate/config.toml, e.g.:")
    print('  device = "PCM2902 Audio Codec Analog Stereo"')
    return 0


def cmd_devices(_args) -> int:
    try:
        send_control("devices")
    except (ConnectionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if cfg.DEVICES_FILE.exists():
        print(cfg.DEVICES_FILE.read_text())
    return 0


def cmd_test_mic(args) -> int:
    name = " ".join(args.name)
    try:
        print(send_control(f"test-mic {name}", timeout=cfg.MIC_TEST_SECONDS + 5.0))
    except (ConnectionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_set_device(args) -> int:
    name = " ".join(args.name)
    try:
        print(send_control(f"set-device {name}"))
    except (ConnectionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_status(_args) -> int:
    if not daemon_running():
        print("stopped: no daemon running")
        return 1
    if cfg.STATE_FILE.exists():
        try:
            state = json.loads(cfg.STATE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
        print(f"{state.get('status', 'unknown')}: {state.get('text', '')}")
    else:
        print("running (no state yet)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shona-translate",
        description="Push-to-talk Shona -> English speech translation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="start the translation daemon (loads the model, blocks)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("toggle", help="start listening, or stop and translate")
    p.set_defaults(func=cmd_toggle)

    p = sub.add_parser("quit", help="stop a running daemon")
    p.set_defaults(func=cmd_quit)

    p = sub.add_parser("status", help="print the daemon's current state")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("mics", help="measure input level on each available microphone")
    p.add_argument("--seconds", type=float, default=1.5, help="how long to sample each device")
    p.set_defaults(func=cmd_mics)

    p = sub.add_parser("devices", help="ask the daemon to (re)write the device list")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("test-mic", help="record a few seconds from a device, play it back")
    p.add_argument("name", nargs="+", help="device name, e.g. PCM2902 Audio Codec Analog Stereo")
    p.set_defaults(func=cmd_test_mic)

    p = sub.add_parser("set-device", help="pin the mic the daemon records from")
    p.add_argument("name", nargs="+", help="device name, e.g. PCM2902 Audio Codec Analog Stereo")
    p.set_defaults(func=cmd_set_device)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
