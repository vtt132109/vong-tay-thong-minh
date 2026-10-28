#!/usr/bin/env python3
"""Capture labeled 6-axis IMU trials from the ESP32-S3 Bio-Band.

The firmware exposes GET/POST /capture?seconds=N. While a capture is active it
streams CSV lines "ax,ay,az,gx,gy,gz" at 50 Hz on USB Serial, suppresses other
logs, and stops after N seconds. GET /capture?on=0 stops it immediately. That
stream has no header and no timestamps; this tool adds both.

For every trial the tool:
  1. opens (or reuses) the serial port before the HTTP request, clears stale
     input, then calls http://<host>/capture?seconds=<seconds>;
  2. reads exactly-six-field numeric lines until the trial deadline or the
     firmware's "# CAPTURE_END" marker, ignoring boot logs and other text;
  3. calls /capture?on=0 as a safety stop and drains/clears the serial buffer;
  4. writes <out>/training/<label>/<label>_<subject>_<trial:03d>.csv with the
     header timestamp,ax,ay,az,gx,gy,gz and timestamps 0, 20, 40, ... ms.

Output is ready for tools/upload_dataset.py. This script never uploads data.

SAFETY AND ETHICS
-----------------
Real fall data must be collected safely and with consent:
  * simulate falls only onto a thick mattress; never attempt a real injurious
    fall;
  * have a trained spotter/supervisor present for every fall trial and stop
    immediately if the participant feels pain or discomfort;
  * obtain informed consent from every participant and explain how the data
    will be used.
Synthetic data is not a substitute for real, consented measurements from the
people and hardware the model must work with.

Requirements
------------
* Python 3.8+ (standard library only, except pyserial).
* pyserial:  python -m pip install pyserial
  If pyserial is missing, the script prints this install hint. --help,
  --dry-run, and argument validation work without pyserial.

Usage
-----
    python tools/capture_labeled.py --list-ports
    python tools/capture_labeled.py --host 192.168.4.1 --port COM5 \\
        --label fall --subject S01 --trials 10 --seconds 10
    python tools/capture_labeled.py --host 192.168.4.1 --port /dev/ttyACM0 \\
        --label adl --subject S02 --trials 15 --seconds 10
    python tools/capture_labeled.py --host 192.168.4.1 --port COM5 \\
        --label fall --dry-run

Connect the PC to the board's Wi-Fi AP ("BioBand-Setup", 192.168.4.1) or the
same LAN, close any serial monitor / Data Forwarder using the port, and run the
tool. If stdin is a TTY the operator presses Enter before each trial and starts
the action only after the tool prints "CAPTURE STARTED". If stdin is not a TTY
(for scripted runs) the trial starts immediately. Every file starts at 0 ms and
advances 20 ms per saved sample, independent of USB arrival jitter.

Output (default):
    dataset/training/fall/fall_S01_001.csv
    dataset/training/fall/fall_S01_002.csv
    ...
    dataset/training/adl/adl_S01_001.csv

Exit codes
----------
    0   all requested trials saved (or dry-run/list-ports completed)
    1   missing pyserial, HTTP/serial/file error, or no usable samples
    2   invalid command-line arguments
    130 interrupted by Ctrl+C

Notes
-----
* One reader per port. The firmware suppresses logs during capture, but another
  serial monitor or Edge Impulse Data Forwarder must not open the port.
* The port stays open between trials and its input buffer is cleared before
  each HTTP start. This avoids missing the first samples without toggling
  DTR/RTS (which can reset some boards).
* Serial and HTTP operations are strictly sequential: a new capture is started
  only after the previous one ended and its safety stop was sent.
* The firmware clamps capture durations below 5 s, so --seconds accepts the
  range 5-300 to keep the requested duration and the actual stream consistent.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

SAMPLE_RATE_HZ = 50.0
SAMPLE_PERIOD_MS = 1000.0 / SAMPLE_RATE_HZ
CSV_HEADER = ["timestamp", "ax", "ay", "az", "gx", "gy", "gz"]
CAPTURE_END_MARKER = "# CAPTURE_END"

SERIAL_READ_TIMEOUT_S = 0.1
HTTP_TIMEOUT_S = 5.0
STOP_HTTP_TIMEOUT_S = 3.0
STOP_HTTP_TIMEOUT_ON_INTERRUPT_S = 1.5
HTTP_STOP_ATTEMPTS = 2
READ_GRACE_S = 1.0
FIRST_SAMPLE_TIMEOUT_S = 5.0
POST_STOP_DRAIN_S = 0.3
DEFAULT_BAUD = 115200
PYSERIAL_HINT = "python -m pip install pyserial"

# Standard decimal/scientific notation only. float() alone would also accept
# "nan", "inf", and "1_000", which are not valid sensor fields.
_NUMERIC_RE = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM{}".format(index) for index in range(1, 10)]
    + ["LPT{}".format(index) for index in range(1, 10)]
)


class CaptureError(Exception):
    """A setup, HTTP, serial, or file error that should stop the session."""


@dataclass
class CaptureResult:
    """Samples and diagnostics from one capture window."""

    rows: List[List[str]]
    marker_seen: bool
    ignored_lines: int
    elapsed_s: float


@dataclass
class TrialRecord:
    """A trial CSV that was written successfully."""

    number: int
    path: Path
    samples: int
    elapsed_s: float
    marker_seen: bool


# ---------------------------------------------------------------------------
# Argument handling and filesystem-safe names
# ---------------------------------------------------------------------------
def _int_between(low: int, high: Optional[int], what: str):
    """Build an argparse type that accepts an integer in [low, high]."""

    def convert(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(
                "{} must be an integer (got {!r})".format(what, text)
            )
        if value < low or (high is not None and value > high):
            if high is None:
                raise argparse.ArgumentTypeError(
                    "{} must be >= {}".format(what, low)
                )
            raise argparse.ArgumentTypeError(
                "{} must be between {} and {}".format(what, low, high)
            )
        return value

    return convert


def sanitize_component(raw: str, what: str) -> str:
    """Return a safe single path component for a label or subject.

    Path separators, spaces, and anything outside [A-Za-z0-9._-] become '_'.
    Leading/trailing dots, dashes, and underscores are removed to avoid hidden
    files and Windows trailing-dot issues. Windows device names get a suffix.
    """
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", raw.strip())
    text = re.sub(r"_{2,}", "_", text).strip(" ._-")
    if not text:
        raise ValueError("{} must contain at least one letter or digit".format(what))
    if text.upper() in _RESERVED_NAMES:
        text += "_"
    return text


def normalize_host(raw: str) -> str:
    """Return http(s)://host[:port] from an IP, host name, or base URL."""
    text = raw.strip()
    if not text:
        raise ValueError("must not be empty")
    if "://" not in text:
        text = "http://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("only http:// and https:// URLs are supported")
    if not parts.hostname:
        raise ValueError("missing host name or IP address")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(
            "expected only http://<ip>[:port], without a path or query"
        )
    try:
        _ = parts.port  # Raises ValueError for a malformed port.
    except ValueError as exc:
        raise ValueError("invalid TCP port in host") from exc
    return "{}://{}".format(parts.scheme.lower(), parts.netloc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record labeled 6-axis IMU trials from the ESP32-S3 Bio-Band over "
            "USB Serial. Starts/stops /capture over HTTP, adds timestamps and "
            "a header, and writes CSVs ready for tools/upload_dataset.py. "
            "This tool never uploads to Edge Impulse."
        ),
        epilog=(
            "examples:\n"
            "  python tools/capture_labeled.py --list-ports\n"
            "  python tools/capture_labeled.py --host 192.168.4.1 --port COM5 "
            "--label fall --subject S01 --trials 10 --seconds 10\n"
            "  python tools/capture_labeled.py --host 192.168.4.1 --port "
            "/dev/ttyACM0 --label adl --subject S02 --trials 15 --seconds 10\n"
            "  python tools/capture_labeled.py --host 192.168.4.1 --port COM5 "
            "--label fall --dry-run\n"
            "\n"
            "pyserial: {}\n"
            "\n"
            "SAFETY: collect real fall data only on a mattress, with a "
            "supervisor present\n"
            "and informed consent from every participant. Never attempt a "
            "real injurious\n"
            "fall. Synthetic data is not a substitute for consented real "
            "measurements.".format(PYSERIAL_HINT)
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        help=(
            "ESP32 IP address or base URL, e.g. 192.168.4.1 "
            "(required unless --list-ports)"
        ),
    )
    parser.add_argument(
        "--port",
        help="serial port of the ESP32, e.g. COM5 or /dev/ttyACM0",
    )
    parser.add_argument(
        "--label",
        help="class label used in the folder and file name, e.g. fall or adl",
    )
    parser.add_argument(
        "--subject",
        default="S01",
        help="subject/session identifier used in file names (default: S01)",
    )
    parser.add_argument(
        "--trials",
        type=_int_between(1, 10000, "trial count"),
        default=10,
        help="number of trials to capture (default: 10)",
    )
    parser.add_argument(
        "--seconds",
        type=_int_between(5, 300, "duration"),
        default=10,
        help="capture duration per trial in seconds, 5-300 (default: 10)",
    )
    parser.add_argument(
        "--out",
        default="dataset",
        help=(
            "dataset root; files go to <out>/training/<label>/ "
            "(default: dataset, relative to the current directory)"
        ),
    )
    parser.add_argument(
        "--baud",
        type=_int_between(1, 4000000, "baud rate"),
        default=DEFAULT_BAUD,
        help="serial baud rate (default: 115200; USB CDC usually ignores it)",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="list available serial ports and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate arguments and print URLs/paths without serial or HTTP",
    )
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)

    # --list-ports is useful on its own, so required arguments are enforced
    # here rather than with argparse's required=True.
    if args.list_ports:
        return args

    missing = [
        "--" + name
        for name in ("host", "port", "label")
        if not str(getattr(args, name) or "").strip()
    ]
    if missing:
        parser.error("the following arguments are required: " + ", ".join(missing))

    try:
        args.base_url = normalize_host(args.host)
    except ValueError as exc:
        parser.error("--host: {}".format(exc))

    try:
        args.label_safe = sanitize_component(args.label, "--label")
    except ValueError as exc:
        parser.error(str(exc))

    try:
        args.subject_safe = sanitize_component(args.subject, "--subject")
    except ValueError as exc:
        parser.error(str(exc))

    raw_out = str(args.out or "").strip()
    if not raw_out:
        parser.error("--out must not be empty")
    try:
        args.out_dir = Path(raw_out).expanduser().resolve()
    except OSError as exc:
        parser.error("--out: {}".format(exc))
    if args.out_dir.exists() and not args.out_dir.is_dir():
        parser.error("--out is not a directory: {}".format(args.out_dir))

    return args


# ---------------------------------------------------------------------------
# Serial port helpers
# ---------------------------------------------------------------------------
def require_pyserial():
    """Import and return pyserial, raising a friendly install hint."""
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise CaptureError(
            "pyserial is required but is not installed.\n"
            "Install it with:\n"
            "  {}\n"
            "Use the same Python interpreter that runs this script (for "
            "example, the project's virtualenv).".format(PYSERIAL_HINT)
        ) from exc
    return serial


def command_list_ports() -> int:
    """Print pyserial's serial port list and return an exit code."""
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        print(
            "error: pyserial is required to list serial ports.\n"
            "Install it with:\n"
            "  {}".format(PYSERIAL_HINT),
            file=sys.stderr,
        )
        return 1

    try:
        ports = sorted(list_ports.comports(), key=lambda port: port.device)
    except Exception as exc:  # Port enumeration can fail on odd drivers.
        print("error: could not enumerate serial ports: {}".format(exc), file=sys.stderr)
        return 1

    if not ports:
        print("No serial ports found.")
        print("Connect the ESP32 with a USB data cable and try again.")
        return 0

    print("Available serial ports:")
    for port in ports:
        description = port.description or ""
        print("  {:<20} {}".format(port.device, description).rstrip())
        if port.hwid:
            print("  {:<20} {}".format("", port.hwid).rstrip())
    print("")
    print("Use the device name with --port, for example --port COM5.")
    return 0


def open_serial(port: str, baud: int):
    """Open the serial port and clear any stale input."""
    serial = require_pyserial()
    try:
        handle = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=SERIAL_READ_TIMEOUT_S,
            write_timeout=1.0,
        )
    except (serial.SerialException, ValueError, OSError) as exc:
        raise CaptureError(
            "could not open serial port {!r} at {} baud: {}\n"
            "  - close Arduino IDE's Serial Monitor, Edge Impulse Data "
            "Forwarder, or any other program using this port\n"
            "  - run with --list-ports to find the correct device name\n"
            "  - on Linux, add your user to the 'dialout' group and log in "
            "again".format(port, baud, exc)
        ) from exc

    try:
        handle.reset_input_buffer()
    except (serial.SerialException, OSError) as exc:
        close_serial(handle)
        raise CaptureError(
            "could not clear the input buffer of {!r}: {}".format(port, exc)
        ) from exc
    return handle


def close_serial(handle: Any) -> None:
    """Close the serial port, ignoring shutdown errors."""
    if handle is None:
        return
    try:
        if getattr(handle, "is_open", False):
            handle.close()
    except OSError:
        pass


def ensure_serial_open(handle: Any, port: str, baud: int):
    """Reuse an open handle or reopen the port for the next trial."""
    try:
        if handle is not None and handle.is_open:
            return handle
    except OSError:
        pass
    close_serial(handle)
    print("  serial port was closed; reopening {} ...".format(port), flush=True)
    return open_serial(port, baud)


def clear_serial_input(handle: Any) -> None:
    try:
        handle.reset_input_buffer()
    except OSError as exc:
        raise CaptureError(
            "serial port error while clearing stale input: {}".format(exc)
        ) from exc


def drain_and_clear(handle: Any, duration: float = POST_STOP_DRAIN_S) -> None:
    """Consume trailing lines after a stop and discard anything left."""
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            handle.readline()
        handle.reset_input_buffer()
    except OSError:
        # A persistent problem is reported by the next trial's clear/open.
        pass


# ---------------------------------------------------------------------------
# HTTP start / safety stop
# ---------------------------------------------------------------------------
def http_get(url: str, timeout: float) -> Tuple[int, str]:
    """GET *url* with a timeout and return (status, short text body)."""
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "capture_labeled.py",
            "Cache-Control": "no-store",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(256).decode("utf-8", "replace").strip()
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(256).decode("utf-8", "replace").strip()
        except Exception:
            pass
        finally:
            exc.close()
        message = "HTTP {} from {}".format(exc.code, url)
        if detail:
            message += ": {}".format(detail)
        if exc.code == 503:
            message += (
                "\nThe ESP32 is busy (another capture or client may be "
                "active). Wait a moment and retry."
            )
        elif exc.code == 404:
            message += (
                "\nCheck --host and that this firmware exposes /capture."
            )
        raise CaptureError(message) from exc
    except urllib.error.URLError as exc:
        raise CaptureError(
            "could not reach the ESP32 at {}: {}\n"
            "  - join the board's Wi-Fi AP (BioBand-Setup, 192.168.4.1) or "
            "the same LAN\n"
            "  - check --host; the HTTP API listens on port 80\n"
            "  - make sure no other client is capturing from the board".format(
                url, exc.reason
            )
        ) from exc
    except TimeoutError as exc:
        raise CaptureError(
            "timed out after {:.0f} s waiting for {}\n"
            "The board may be busy; wait a moment and retry.".format(
                timeout, url
            )
        ) from exc
    except OSError as exc:
        raise CaptureError(
            "network error while contacting {}: {}".format(url, exc)
        ) from exc

    if status < 200 or status >= 300:
        raise CaptureError(
            "unexpected HTTP status {} from {}: {!r}".format(status, url, body)
        )
    return status, body


def start_capture(base_url: str, seconds: int) -> str:
    """Send GET /capture?seconds=N and return the response body."""
    url = "{}/capture?seconds={}".format(base_url, seconds)
    _status, body = http_get(url, HTTP_TIMEOUT_S)
    if body.upper().startswith("BUSY"):
        raise CaptureError(
            "the ESP32 rejected the start request: {!r}\n"
            "Wait for any previous capture to finish and retry.".format(body)
        )
    return body


def stop_capture(
    base_url: str, timeout: float = STOP_HTTP_TIMEOUT_S
) -> Tuple[bool, str]:
    """Send GET /capture?on=0 with retries. Never raises."""
    url = "{}/capture?on=0".format(base_url)
    last_error = ""
    for attempt in range(HTTP_STOP_ATTEMPTS):
        try:
            _status, body = http_get(url, timeout)
            return True, body or "OK"
        except CaptureError as exc:
            last_error = str(exc)
            if attempt + 1 < HTTP_STOP_ATTEMPTS:
                time.sleep(0.3)
    return False, last_error


# ---------------------------------------------------------------------------
# Capture parsing and writing
# ---------------------------------------------------------------------------
def parse_sample_line(line: str) -> Optional[List[str]]:
    """Return six numeric field strings, or None for any non-data line."""
    fields = [field.strip() for field in line.split(",")]
    if len(fields) != 6:
        return None
    for field in fields:
        if not field or _NUMERIC_RE.fullmatch(field) is None:
            return None
    try:
        values = [float(field) for field in fields]
    except ValueError:
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return fields


def read_capture(handle: Any, seconds: int) -> CaptureResult:
    """Read validated samples until the deadline or '# CAPTURE_END'."""
    started = time.monotonic()
    # The extra second is only a grace period for the end marker; max_samples
    # keeps the saved file at exactly the requested duration if the firmware
    # overruns or the stop request is late.
    hard_deadline = started + seconds + READ_GRACE_S
    first_sample_deadline = min(
        started + FIRST_SAMPLE_TIMEOUT_S, hard_deadline
    )
    max_samples = int(round(seconds * SAMPLE_RATE_HZ))
    rows: List[List[str]] = []
    ignored_lines = 0
    marker_seen = False

    while True:
        now = time.monotonic()
        if now >= hard_deadline:
            break
        if not rows and now >= first_sample_deadline:
            break

        try:
            raw = handle.readline()
        except OSError as exc:
            raise CaptureError(
                "serial read failed: {}\n"
                "  - check that the USB cable is connected and the board is "
                "powered\n"
                "  - do not unplug the board during a trial".format(exc)
            ) from exc
        if not raw:
            continue

        line = raw.decode("ascii", "replace").strip()
        if not line:
            continue
        if line.startswith("#"):
            if CAPTURE_END_MARKER in line:
                marker_seen = True
                break
            ignored_lines += 1
            continue

        fields = parse_sample_line(line)
        if fields is None:
            ignored_lines += 1
            continue
        if len(rows) < max_samples:
            rows.append(fields)

    return CaptureResult(
        rows=rows,
        marker_seen=marker_seen,
        ignored_lines=ignored_lines,
        elapsed_s=time.monotonic() - started,
    )


def write_trial_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    """Write one trial atomically with header and 0, 20, 40, ... ms stamps."""
    temp_path = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(CSV_HEADER)
            for index, fields in enumerate(rows):
                timestamp_ms = int(round(index * SAMPLE_PERIOD_MS))
                writer.writerow([timestamp_ms, *fields])
        temp_path.replace(path)
    except (OSError, csv.Error) as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise CaptureError("could not write {}: {}".format(path, exc)) from exc


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------
def print_plan(
    args: argparse.Namespace, trial_paths: Sequence[Path]
) -> int:
    """Print a dry-run plan without creating directories or opening anything."""
    label_dir = args.out_dir / "training" / args.label_safe
    expected = int(round(args.seconds * SAMPLE_RATE_HZ))
    last_timestamp = int(round((expected - 1) * SAMPLE_PERIOD_MS))

    print("Capture plan (DRY RUN - no serial or HTTP access)")
    print("  host          : {}".format(args.host.strip()))
    print("  base URL      : {}".format(args.base_url))
    print("  serial port   : {} @ {} baud".format(args.port, args.baud))
    print("  label         : {}".format(args.label_safe))
    print("  subject       : {}".format(args.subject_safe))
    if args.label_safe != str(args.label).strip():
        print("  note          : label sanitized from {!r}".format(args.label))
    if args.subject_safe != str(args.subject).strip():
        print("  note          : subject sanitized from {!r}".format(args.subject))
    print("  trials        : {} x {} s".format(args.trials, args.seconds))
    print("  output root   : {}".format(args.out_dir))
    print("  target folder : {}".format(label_dir))
    print(
        "  start URL     : {}/capture?seconds={}".format(
            args.base_url, args.seconds
        )
    )
    print("  safety stop   : {}/capture?on=0".format(args.base_url))
    print("  CSV header    : {}".format(",".join(CSV_HEADER)))
    print(
        "  expected      : ~{} samples/trial, timestamps 0..{} ms".format(
            expected, last_timestamp
        )
    )
    print("  files:")
    for number, path in enumerate(trial_paths, 1):
        suffix = "  [exists, would be overwritten]" if path.exists() else ""
        print("    {:03d}  {}{}".format(number, path, suffix))
    print("")
    print("No directories were created, no serial port was opened, and no HTTP")
    print("request was sent. Re-run without --dry-run to capture.")
    return 0


def prepare_trial(
    number: int,
    total: int,
    label: str,
    seconds: int,
    path: Path,
) -> bool:
    """Show the pre-trial prompt. Return False if stdin was closed."""
    interactive = sys.stdin.isatty()
    print("")
    if interactive:
        print(
            "Trial {}/{} - prepare; press Enter to start".format(number, total)
        )
    else:
        print(
            "Trial {}/{} - stdin is not a TTY; starting immediately".format(
                number, total
            )
        )
    print(
        "  label={}  duration={} s  file={}".format(
            label, seconds, path.name
        )
    )
    print(
        "  WARNING: perform the action ONLY AFTER the tool prints "
        "CAPTURE STARTED."
    )
    print("           Do not start the action during this prompt.")

    if not interactive:
        return True
    try:
        input("  Press Enter when you are ready... ")
    except EOFError:
        print("  stdin closed; stopping before this trial.")
        return False
    return True


def print_summary(
    records: Sequence[TrialRecord],
    planned: int,
    label: str,
    subject: str,
    label_dir: Path,
    interrupted: bool,
) -> None:
    """Print the session summary, including after Ctrl+C or an error."""
    print("")
    print("Capture summary{}".format(" (interrupted)" if interrupted else ""))
    print("  label/subject : {}/{}".format(label, subject))
    print("  trials saved  : {}/{}".format(len(records), planned))
    total_samples = sum(record.samples for record in records)
    total_elapsed = sum(record.elapsed_s for record in records)
    print("  samples       : {}".format(total_samples))
    if records:
        print("  read time     : {:.1f} s".format(total_elapsed))
    print("  folder        : {}".format(label_dir))
    if not records:
        print("  no CSV files were written")
        return

    print("  files:")
    for record in records:
        note = "" if record.marker_seen else "  (deadline stop)"
        print(
            "    {:03d}  {:6d} samples  {}{}".format(
                record.number, record.samples, record.path.name, note
            )
        )
    print("  next          : review the CSVs, then use tools/upload_dataset.py")
    print("                  (this tool does not upload anything)")


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.list_ports:
        return command_list_ports()

    label_dir = args.out_dir / "training" / args.label_safe
    trial_paths = [
        label_dir
        / "{}_{}_{:03d}.csv".format(
            args.label_safe, args.subject_safe, number
        )
        for number in range(1, args.trials + 1)
    ]

    if args.dry_run:
        return print_plan(args, trial_paths)

    # Fail before creating folders or warnings if the dependency is missing.
    try:
        require_pyserial()
    except CaptureError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1

    if args.label_safe != str(args.label).strip():
        print(
            "note: label {!r} sanitized to {!r} for filesystem safety.".format(
                args.label, args.label_safe
            )
        )
    if args.subject_safe != str(args.subject).strip():
        print(
            "note: subject {!r} sanitized to {!r} for filesystem safety.".format(
                args.subject, args.subject_safe
            )
        )

    try:
        label_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            "error: could not create {}: {}".format(label_dir, exc),
            file=sys.stderr,
        )
        return 1

    print("Labeled IMU capture")
    print("  target       : {}".format(args.base_url))
    print("  serial       : {} @ {} baud".format(args.port, args.baud))
    print(
        "  label/subject: {}/{}".format(args.label_safe, args.subject_safe)
    )
    print("  trials       : {} x {} s".format(args.trials, args.seconds))
    print("  output       : {}".format(label_dir))
    print(
        "  SAFETY       : simulate falls only on a mattress, with a "
        "supervisor present"
    )
    print("                 and informed consent from every participant.")
    print("")

    existing = [path for path in trial_paths if path.exists()]
    if existing:
        print(
            "warning: {} target file(s) already exist and will be "
            "overwritten:".format(len(existing))
        )
        for path in existing[:5]:
            print("  {}".format(path.name))
        if len(existing) > 5:
            print("  ... and {} more".format(len(existing) - 5))
        print("")

    records: List[TrialRecord] = []
    serial_handle: Any = None
    capture_active = False
    interrupted = False
    exit_code = 0
    expected_samples = args.seconds * int(SAMPLE_RATE_HZ)

    try:
        print(
            "Opening serial port {} ...".format(args.port),
            flush=True,
        )
        serial_handle = open_serial(args.port, args.baud)
        print(
            "Serial port open. Keep other serial monitors closed.",
            flush=True,
        )

        for number, path in enumerate(trial_paths, 1):
            if not prepare_trial(
                number, args.trials, args.label_safe, args.seconds, path
            ):
                break

            serial_handle = ensure_serial_open(
                serial_handle, args.port, args.baud
            )
            clear_serial_input(serial_handle)

            print("  Starting capture ...", flush=True)
            # Mark active before the request: if Ctrl+C lands mid-request the
            # outer handler still sends a safety stop.
            capture_active = True
            start_capture(args.base_url, args.seconds)
            print(
                "  CAPTURE STARTED - perform the '{}' action NOW.".format(
                    args.label_safe
                ),
                flush=True,
            )
            print(
                "  Reading ~{} s at 50 Hz ...".format(args.seconds),
                flush=True,
            )

            result = read_capture(serial_handle, args.seconds)

            stop_ok, stop_detail = stop_capture(args.base_url)
            capture_active = False
            if stop_ok:
                print("  Safety stop sent (/capture?on=0).", flush=True)
            else:
                print(
                    "  warning: safety stop failed: {}".format(stop_detail),
                    file=sys.stderr,
                )
                if not result.marker_seen:
                    raise CaptureError(
                        "the capture could not be stopped and '# CAPTURE_END' "
                        "was not seen; aborting before the next trial to avoid "
                        "overlapping captures.\n"
                        "Wait for the firmware's own timeout or power-cycle "
                        "the board, then retry."
                    )

            drain_and_clear(serial_handle)

            if not result.rows:
                raise CaptureError(
                    "no valid 6-column CSV samples received on {!r} "
                    "({} ignored line(s), {:.1f} s).\n"
                    "  - close any serial monitor or Data Forwarder using "
                    "this port\n"
                    "  - verify the port with --list-ports\n"
                    "  - confirm the HTTP start returned OK and the firmware "
                    "streams ax,ay,az,gx,gy,gz at 50 Hz\n"
                    "  - try another USB cable/port; some cables are "
                    "power-only".format(
                        args.port, result.ignored_lines, result.elapsed_s
                    )
                )

            write_trial_csv(path, result.rows)
            records.append(
                TrialRecord(
                    number=number,
                    path=path,
                    samples=len(result.rows),
                    elapsed_s=result.elapsed_s,
                    marker_seen=result.marker_seen,
                )
            )
            print(
                "  saved {} samples ({:.1f} s) -> {}".format(
                    len(result.rows), result.elapsed_s, path
                ),
                flush=True,
            )
            if not result.marker_seen:
                print(
                    "  note: '# CAPTURE_END' was not seen; stopped at the "
                    "read deadline.",
                    flush=True,
                )
            if len(result.rows) < int(expected_samples * 0.8):
                print(
                    "  warning: expected about {} samples but got {}. "
                    "Check the serial connection.".format(
                        expected_samples, len(result.rows)
                    ),
                    file=sys.stderr,
                )

    except KeyboardInterrupt:
        interrupted = True
        exit_code = 130
        print("\nInterrupted by user.", file=sys.stderr)
        if capture_active:
            print(
                "Sending safety stop (/capture?on=0) ...", file=sys.stderr
            )
            ok, detail = stop_capture(
                args.base_url,
                timeout=STOP_HTTP_TIMEOUT_ON_INTERRUPT_S,
            )
            capture_active = False
            if ok:
                print("Safety stop sent.", file=sys.stderr)
            else:
                print(
                    "warning: safety stop failed: {}\n"
                    "The firmware still stops on its own after the requested "
                    "duration.".format(detail),
                    file=sys.stderr,
                )
    except CaptureError as exc:
        exit_code = 1
        print("error: {}".format(exc), file=sys.stderr)
        if capture_active:
            print(
                "Sending safety stop (/capture?on=0) ...", file=sys.stderr
            )
            ok, _detail = stop_capture(
                args.base_url,
                timeout=STOP_HTTP_TIMEOUT_ON_INTERRUPT_S,
            )
            capture_active = False
            if not ok:
                print(
                    "warning: safety stop also failed; the firmware still "
                    "stops after its own timeout.",
                    file=sys.stderr,
                )
    finally:
        close_serial(serial_handle)
        print_summary(
            records,
            args.trials,
            args.label_safe,
            args.subject_safe,
            label_dir,
            interrupted,
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
