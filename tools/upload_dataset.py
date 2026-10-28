#!/usr/bin/env python3
"""Upload the CSV dataset in ``dataset/<split>/<label>/`` to Edge Impulse.

This script wraps the official ``edge-impulse-uploader`` CLI. It discovers
every ``*.csv`` file under the selected split/label folders and uploads them
with the matching Edge Impulse category ("training" or "testing") and label.

WARNING
-------
Synthetic data (for example the CSV files produced by the dataset generator
in this repository) is useful for testing the upload/training pipeline only.
A model trained on synthetic data is NOT expected to be accurate on real
hardware. Collect real sensor data from the actual device and retrain before
trusting any accuracy figure or deploying a model.

Requirements
------------
* Python 3.8+ (standard library only).
* Node.js/npm and the Edge Impulse CLI:

      npm install -g edge-impulse-cli

Usage
-----
    # API key from the environment (recommended)
    set EI_API_KEY=ei_xxxxxxxxxxxxxxxx       (Windows cmd)
    $env:EI_API_KEY="ei_xxxxxxxxxxxxxxxx"    (PowerShell)
    export EI_API_KEY=ei_xxxxxxxxxxxxxxxx    (Linux/macOS)

    python tools/upload_dataset.py --dry-run
    python tools/upload_dataset.py --split training --label fall
    python tools/upload_dataset.py --dataset "D:/data/my_set" --split both --label all

Exit codes
----------
    0   everything uploaded (or dry-run completed)
    1   uploader missing, dataset missing/empty, or an upload failed
    2   invalid command-line arguments
    130 interrupted by the user

Security notes
--------------
The Edge Impulse uploader only accepts the API key as a command-line
argument, so the key is visible to other local processes (for example via
the process list) while the uploader runs. The key is never written to disk
and is always masked in this script's output.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

UPLOADER_BASE_NAME = "edge-impulse-uploader"
INSTALL_HINT = "npm install -g edge-impulse-cli"
SPLITS = ("training", "testing")
LABELS = ("fall", "adl")

# Number of CSV paths per uploader invocation. Keeps the command line well
# below the Windows limit (~32k characters) while avoiding one process per file.
BATCH_SIZE = 50

# Placeholder used by --dry-run when no API key is supplied.
DRY_RUN_KEY_PLACEHOLDER = "<EI_API_KEY>"


def mask_key(key: Optional[str]) -> str:
    """Return a log-safe representation of an API key."""
    if not key:
        return "<missing>"
    if key.startswith("<") and key.endswith(">"):
        return key
    if len(key) <= 8:
        return "*" * len(key)
    return "{}...{}".format(key[:2], key[-4:])


def format_command(cmd: Sequence[str]) -> str:
    """Format a command list for display with the API key masked."""
    display = list(cmd)
    try:
        idx = display.index("--api-key") + 1
    except ValueError:
        pass
    else:
        if idx < len(display):
            display[idx] = mask_key(display[idx])

    if os.name == "nt":
        # Produce a command line that can be pasted into cmd.exe/PowerShell.
        return subprocess.list2cmdline(display)
    return shlex.join(display)


def find_uploader() -> Optional[str]:
    """Locate edge-impulse-uploader (including the .cmd shim on Windows)."""
    if os.name == "nt":
        extensions = (".cmd", ".exe", ".bat", "")
    else:
        extensions = ("",)

    for ext in extensions:
        found = shutil.which(UPLOADER_BASE_NAME + ext)
        if found:
            return found

    # Fallbacks for npm global installs whose bin dir is not on PATH.
    candidates: List[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm")
    candidates.extend(
        [
            Path.home() / "AppData" / "Roaming" / "npm",
            Path.home() / ".npm-global" / "bin",
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
        ]
    )

    for folder in candidates:
        for name in (UPLOADER_BASE_NAME + ".cmd", UPLOADER_BASE_NAME):
            path = folder / name
            if path.is_file():
                return str(path)
    return None


def dataset_dir_from_arg(raw: str) -> Path:
    """Resolve --dataset: absolute as-is, relative to CWD or the repo root."""
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path

    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    repo_root = Path(__file__).resolve().parent.parent
    return (repo_root / path).resolve()


def collect_jobs(
    dataset_dir: Path, splits: Iterable[str], labels: Iterable[str]
) -> List[Tuple[str, str, List[Path]]]:
    """Build (split, label, sorted csv files) jobs; skip missing/empty folders."""
    jobs: List[Tuple[str, str, List[Path]]] = []
    for split in splits:
        for label in labels:
            folder = dataset_dir / split / label
            if not folder.is_dir():
                print("[skip] {} does not exist".format(folder))
                continue
            files = sorted(p for p in folder.glob("*.csv") if p.is_file())
            if not files:
                print("[skip] {} contains no .csv files".format(folder))
                continue
            jobs.append((split, label, files))
    return jobs


def chunked(files: Sequence[Path], size: int) -> Iterable[Sequence[Path]]:
    for start in range(0, len(files), size):
        yield files[start : start + size]


def build_command(
    uploader: str, api_key: str, split: str, label: str, files: Sequence[Path]
) -> List[str]:
    return [
        uploader,
        "--api-key",
        api_key,
        "--category",
        split,  # Edge Impulse categories are "training" and "testing".
        "--label",
        label,
        *[str(path) for path in files],
    ]


def run_command(cmd: Sequence[str], file_count: int) -> Optional[int]:
    """Run one uploader invocation.

    Returns ``file_count`` on success or None on failure. Nothing is printed
    to stdout by the script for real runs; the uploader shows its own progress.
    """
    try:
        completed = subprocess.run(list(cmd), check=False)
    except OSError as exc:
        print("error: could not start uploader: {}".format(exc), file=sys.stderr)
        return None

    if completed.returncode != 0:
        print(
            "error: uploader exited with code {} for command:\n  {}".format(
                completed.returncode, format_command(cmd)
            ),
            file=sys.stderr,
        )
        return None
    return file_count


def print_summary(counts: Counter, dry_run: bool) -> None:
    print("")
    print("Summary ({})".format("dry run - nothing uploaded" if dry_run else "uploaded"))
    if not counts:
        print(
            "  no files matched the selection"
            if dry_run
            else "  no files were uploaded"
        )
        return

    def sort_key(item):
        (split, label), _count = item
        split_rank = SPLITS.index(split) if split in SPLITS else len(SPLITS)
        label_rank = LABELS.index(label) if label in LABELS else len(LABELS)
        return (split_rank, label_rank)

    total = 0
    for (split, label), count in sorted(counts.items(), key=sort_key):
        print("  {:8s} / {:4s} : {:5d} file(s)".format(split, label, count))
        total += count
    print("  total            : {:5d} file(s)".format(total))
    if dry_run:
        print("  (re-run without --dry-run to upload)")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload dataset/<split>/<label>/*.csv files to Edge Impulse. "
            "Synthetic data is for pipeline testing only; collect real data "
            "for accuracy."
        ),
        epilog=(
            "Install the uploader with: {}\n\n"
            "The API key is passed to the uploader's command line (required by "
            "the CLI) and is masked in all output from this script.".format(INSTALL_HINT)
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("EI_API_KEY"),
        help="Edge Impulse API key (default: EI_API_KEY environment variable)",
    )
    parser.add_argument(
        "--dataset",
        default="dataset",
        help="dataset root containing <split>/<label>/*.csv (default: dataset)",
    )
    parser.add_argument(
        "--split",
        choices=("training", "testing", "both"),
        default="both",
        help="which split(s) to upload (default: both)",
    )
    parser.add_argument(
        "--label",
        choices=("fall", "adl", "all"),
        default="all",
        help="which label folder(s) to upload (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the uploader commands without executing them",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    splits = ("training", "testing") if args.split == "both" else (args.split,)
    labels = ("fall", "adl") if args.label == "all" else (args.label,)

    api_key = args.api_key
    if not api_key:
        if not args.dry_run:
            print(
                "error: missing API key; pass --api-key or set EI_API_KEY",
                file=sys.stderr,
            )
            return 2
        api_key = DRY_RUN_KEY_PLACEHOLDER

    uploader = find_uploader()
    if uploader is None:
        print(
            "error: '{}' was not found on PATH.\n"
            "Install the Edge Impulse CLI first:\n"
            "  {}".format(UPLOADER_BASE_NAME, INSTALL_HINT),
            file=sys.stderr,
        )
        return 1

    dataset_dir = dataset_dir_from_arg(args.dataset)
    if not dataset_dir.is_dir():
        print(
            "error: dataset directory not found: {}\n"
            "Use --dataset to point at the folder containing training/ and "
            "testing/.".format(dataset_dir),
            file=sys.stderr,
        )
        return 1

    jobs = collect_jobs(dataset_dir, splits, labels)
    if not jobs:
        print(
            "error: no CSV files matched split={} label={} under {}".format(
                args.split, args.label, dataset_dir
            ),
            file=sys.stderr,
        )
        return 1

    print("Edge Impulse dataset upload")
    print("  uploader : {}".format(uploader))
    print("  dataset  : {}".format(dataset_dir))
    print("  splits   : {}".format(", ".join(splits)))
    print("  labels   : {}".format(", ".join(labels)))
    print("  api key  : {}".format(mask_key(api_key)))
    print("  mode     : {}".format("DRY RUN" if args.dry_run else "upload"))
    print("  NOTE     : synthetic data is for pipeline testing only; real data")
    print("             is required for meaningful accuracy.")
    print("")

    counts: Counter = Counter()
    try:
        for split, label, files in jobs:
            print("[{}/{}] {} file(s)".format(split, label, len(files)))
            for batch in chunked(files, BATCH_SIZE):
                cmd = build_command(uploader, api_key, split, label, batch)
                print("  {}".format(format_command(cmd)))
                if args.dry_run:
                    counts[(split, label)] += len(batch)
                    continue

                uploaded = run_command(cmd, len(batch))
                if uploaded is None:
                    print_summary(counts, dry_run=False)
                    return 1
                counts[(split, label)] += uploaded
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        print_summary(counts, dry_run=args.dry_run)
        return 130

    print_summary(counts, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
