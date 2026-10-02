"""Minimal, self-contained helper for the native macOS bundle."""
import argparse
import sys
from pathlib import Path

from keytrack import agent, console, doctor, kev_rime_bridge, kev_rime_setup, kev_switch, rime_setup, runner


def main():
    if len(sys.argv) > 1 and Path(sys.argv[1]).name == "kev_bridge.marker":
        return kev_rime_bridge.main(sys.argv[2:])
    parser = argparse.ArgumentParser(prog="keytrack-helper")
    parser.add_argument("command", choices=("console-native", "record", "install-agent", "setup-ime", "setup-kev-rime", "doctor", "kev", "ui"))
    parser.add_argument("argument", nargs="?")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "console-native":
        console.native_serve(demo=args.demo)
        return 0
    if args.command == "record":
        runner.run()
        return 0
    if args.command == "doctor":
        return 0 if doctor.command(args.json) else 1
    if args.command == "kev":
        if args.argument not in ("on", "off", "status", "toggle"):
            parser.error("kev requires on/off/status/toggle")
        return 0 if kev_switch.command(args.argument) else 1
    command = {"install-agent": agent.install, "setup-ime": rime_setup.setup,
               "setup-kev-rime": kev_rime_setup.setup, "ui": console.launch}[args.command]
    return 0 if command() else 1


if __name__ == "__main__":
    raise SystemExit(main())
