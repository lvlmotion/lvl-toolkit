#!/usr/bin/env python3
"""
vicon_trigger.py — standalone Vicon Nexus capture-trigger UDP tool.

The Python twin of the Kotlin `ViconUdpListener` / `ViconUdpSender` in
app-sensor-desktop. It speaks the same "RemoteStartStop" wire format, byte for
byte, so it interoperates with both Nexus and our Kotlin app:

    - `listen`   — bind a UDP port and print every capture trigger received.
                   Use it to prove Nexus is broadcasting (and on which port /
                   what XML), independent of the Kotlin app.
    - `start` / `stop` / `complete`
                 — SEND one trigger to Nexus (or to our Kotlin listener). Use it
                   to prove Nexus arms from our packets, or as a manual master.
    - `simulate` — send Start, wait, send Stop: impersonate Nexus to desk-test
                   the Kotlin app's slave listener with no Vicon hardware.

Why this exists: on the Vicon PC there may be no build toolchain to rebuild the
Kotlin exe. This script is field-editable with a text editor + python, and lets
you bisect "Nexus config vs network/port vs our code" without the app.

Wire format (confirmed against Nexus 2.5 / 2.19): one UDP datagram of
null-terminated XML. Root names the event (<CaptureStart>/<CaptureStop>/
<CaptureComplete>); each field is a `<Tag VALUE="..."/>` child; CaptureStop
carries RESULT="SUCCESS|FAIL|CANCEL" on the root. No XML escaping — values must
not contain a double-quote (DatabasePath backslashes are fine).

PORT NOTE: Nexus's default trigger port is 30. On Windows (the Vicon PC) binding
30 is fine. On Linux, port 30 is privileged (<1024) — use a high port (e.g.
30030) and set the SAME value in Nexus and in the app.

Examples:
    # Prove Nexus is broadcasting (run with the Kotlin app DISARMED — one port,
    # one binder). Nexus Prefs -> UDP capture broadcast -> 127.0.0.1:30, Arm on.
    python vicon_trigger.py listen --port 30

    # Arm / stop a real Nexus (co-resident):
    python vicon_trigger.py start --name Trial01
    python vicon_trigger.py stop  --name Trial01 --result SUCCESS

    # Two-machine rig: send to the Nexus PC:
    python vicon_trigger.py start --name Trial01 --host 192.168.1.50 --port 30

    # Desk-test the Kotlin app's listener with no Vicon (Arm the app first):
    python vicon_trigger.py simulate --name desk01 --seconds 8
"""

import argparse
import re
import socket
import sys
import time

DEFAULT_PORT = 30                 # Nexus default; see PORT NOTE above.
DEFAULT_SEND_HOST = "127.0.0.1"   # co-resident with Nexus by default.
MAX_PACKET_BYTES = 8192

# ── Wire format: encode / parse (mirror of ViconUdpListener) ──────────────────

_VALUE_RE_CACHE = {}


def _field(xml: str, tag: str):
    """VALUE of a `<Tag ... VALUE="..."/>` child, or None. Mirror of `field()`."""
    rx = _VALUE_RE_CACHE.get(tag)
    if rx is None:
        rx = re.compile(r'<' + re.escape(tag) + r'\b[^>]*\bVALUE\s*=\s*"([^"]*)"',
                        re.IGNORECASE)
        _VALUE_RE_CACHE[tag] = rx
    m = rx.search(xml)
    return m.group(1) if m else None


_RESULT_RE = re.compile(r'RESULT\s*=\s*"([^"]*)"', re.IGNORECASE)
_START_RE = re.compile(r'<CaptureStart\b', re.IGNORECASE)
_STOP_RE = re.compile(r'<CaptureStop\b', re.IGNORECASE)
_COMPLETE_RE = re.compile(r'<CaptureComplete\b', re.IGNORECASE)


def _tag(name: str, value: str) -> str:
    """A `<Tag VALUE="..."/>` child — inverse of _field."""
    return '<{n} VALUE="{v}"/>'.format(n=name, v=value)


def encode_start(name, packet_id, notes="", description="", database_path="",
                 delay_ms=0) -> bytes:
    xml = ("<CaptureStart>"
           + _tag("Name", name)
           + _tag("Notes", notes)
           + _tag("Description", description)
           + _tag("DatabasePath", database_path)
           + _tag("Delay", str(delay_ms))
           + _tag("PacketID", str(packet_id))
           + "</CaptureStart>")
    return (xml + "\x00").encode("utf-8")


def encode_stop(name, packet_id, result="SUCCESS", database_path="") -> bytes:
    xml = ('<CaptureStop RESULT="{r}">'.format(r=result)
           + _tag("Name", name)
           + _tag("DatabasePath", database_path)
           + _tag("PacketID", str(packet_id))
           + "</CaptureStop>")
    return (xml + "\x00").encode("utf-8")


def encode_complete(name, packet_id, database_path="") -> bytes:
    xml = ("<CaptureComplete>"
           + _tag("Name", name)
           + _tag("DatabasePath", database_path)
           + _tag("PacketID", str(packet_id))
           + "</CaptureComplete>")
    return (xml + "\x00").encode("utf-8")


def parse(xml: str):
    """Parse a datagram's XML into a dict, or None. Mirror of `parse()`."""
    def _int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    if _START_RE.search(xml):
        return {
            "type": "Start",
            "name": _field(xml, "Name") or "",
            "notes": _field(xml, "Notes") or "",
            "description": _field(xml, "Description") or "",
            "databasePath": _field(xml, "DatabasePath") or "",
            "delayMs": _int(_field(xml, "Delay"), 0),
            "packetId": _int(_field(xml, "PacketID"), -1),
        }
    if _STOP_RE.search(xml):
        m = _RESULT_RE.search(xml)
        return {
            "type": "Stop",
            "name": _field(xml, "Name") or "",
            "result": (m.group(1).upper() if m else "SUCCESS"),
            "databasePath": _field(xml, "DatabasePath") or "",
            "packetId": _int(_field(xml, "PacketID"), -1),
        }
    if _COMPLETE_RE.search(xml):
        return {
            "type": "Complete",
            "name": _field(xml, "Name") or "",
            "databasePath": _field(xml, "DatabasePath") or "",
            "packetId": _int(_field(xml, "PacketID"), -1),
        }
    return None


# ── Commands ──────────────────────────────────────────────────────────────────

def _send(payload: bytes, host: str, port: int, label: str):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # allow bcast host
        s.sendto(payload, (host, port))
    xml = payload.rstrip(b"\x00").decode("utf-8", "replace")
    print("SENT {label} -> udp:{h}:{p}  ({n} bytes)".format(
        label=label, h=host, p=port, n=len(payload)))
    print("     {xml}".format(xml=xml))


def cmd_start(a):
    _send(encode_start(a.name, a.packet_id, a.notes, a.description,
                       a.database_path, a.delay_ms),
          a.host, a.port, "CaptureStart '{}'".format(a.name))


def cmd_stop(a):
    _send(encode_stop(a.name, a.packet_id, a.result, a.database_path),
          a.host, a.port, "CaptureStop '{}' ({})".format(a.name, a.result))


def cmd_complete(a):
    _send(encode_complete(a.name, a.packet_id, a.database_path),
          a.host, a.port, "CaptureComplete '{}'".format(a.name))


def cmd_simulate(a):
    """Impersonate Nexus: Start, wait, Stop — desk-test the Kotlin listener."""
    print("Simulating a Nexus trial '{}' on udp:{}:{} ...".format(
        a.name, a.host, a.port))
    _send(encode_start(a.name, 0, delay_ms=0), a.host, a.port,
          "CaptureStart '{}'".format(a.name))
    print("  ...recording for {}s (Ctrl-C to stop early)...".format(a.seconds))
    try:
        time.sleep(a.seconds)
    except KeyboardInterrupt:
        print("  (interrupted)")
    _send(encode_stop(a.name, 1, a.result), a.host, a.port,
          "CaptureStop '{}' ({})".format(a.name, a.result))
    print("Done. If the app was Armed with a sensor connected, a session folder "
          "should exist (or be discarded on FAIL/CANCEL).")


def cmd_listen(a):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((a.host, a.port))
    except OSError as e:
        print("ERROR binding {}:{} — {}".format(a.host, a.port, e), file=sys.stderr)
        if a.port < 1024:
            print("  (port <1024 is privileged on Linux; try a high port e.g. "
                  "30030 and set the same in Nexus + the app.)", file=sys.stderr)
        print("  (or: the Kotlin app is Armed on this port — only one process "
              "can bind it. Disarm the app to listen here.)", file=sys.stderr)
        sys.exit(1)
    print("Listening for Vicon capture triggers on udp:{}:{}  (Ctrl-C to quit)"
          .format(a.host, a.port))
    try:
        while True:
            data, addr = sock.recvfrom(MAX_PACKET_BYTES)
            xml = data.decode("utf-8", "replace").rstrip("\x00").strip()
            evt = parse(xml)
            ts = time.strftime("%H:%M:%S")
            if evt is None:
                print("[{}] from {}: UNRECOGNIZED ({} bytes): {!r}"
                      .format(ts, addr[0], len(data), xml[:200]))
            else:
                print("[{}] from {}: {}".format(ts, addr[0], evt))
    except KeyboardInterrupt:
        print("\n(stopped)")
    finally:
        sock.close()


def build_parser():
    p = argparse.ArgumentParser(
        description="Standalone Vicon Nexus capture-trigger UDP tool "
                    "(send / listen / simulate).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_send_args(sp, need_name=True):
        sp.add_argument("--host", default=DEFAULT_SEND_HOST,
                        help="destination (Nexus PC IP, or a broadcast addr). "
                             "Default 127.0.0.1.")
        sp.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="Nexus trigger port. Default {}.".format(DEFAULT_PORT))
        sp.add_argument("--packet-id", type=int, default=0,
                        help="PacketID stamped into the packet. Default 0.")
        sp.add_argument("--database-path", default="",
                        help="Nexus DatabasePath field.")
        sp.add_argument("--name", required=need_name, default="",
                        help="Trial name (the c3d filename / IMU join key).")

    sp = sub.add_parser("start", help="send a CaptureStart")
    add_send_args(sp)
    sp.add_argument("--notes", default="")
    sp.add_argument("--description", default="")
    sp.add_argument("--delay-ms", type=int, default=0,
                    help="Delay Nexus should wait before capture. Default 0.")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="send a CaptureStop")
    add_send_args(sp)
    sp.add_argument("--result", default="SUCCESS",
                    choices=["SUCCESS", "FAIL", "CANCEL"],
                    help="take result. Default SUCCESS.")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("complete", help="send a CaptureComplete")
    add_send_args(sp)
    sp.set_defaults(func=cmd_complete)

    sp = sub.add_parser("simulate",
                        help="impersonate Nexus: Start, wait, Stop (desk test)")
    sp.add_argument("--host", default=DEFAULT_SEND_HOST)
    sp.add_argument("--port", type=int, default=DEFAULT_PORT)
    sp.add_argument("--name", default="desk01", help="trial name. Default desk01.")
    sp.add_argument("--seconds", type=float, default=8.0,
                    help="seconds between Start and Stop. Default 8.")
    sp.add_argument("--result", default="SUCCESS",
                    choices=["SUCCESS", "FAIL", "CANCEL"])
    sp.set_defaults(func=cmd_simulate)

    sp = sub.add_parser("listen", help="print received capture triggers")
    sp.add_argument("--host", default="0.0.0.0",
                    help="bind address. Default 0.0.0.0 (all interfaces).")
    sp.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="port to listen on. Default {}.".format(DEFAULT_PORT))
    sp.set_defaults(func=cmd_listen)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
