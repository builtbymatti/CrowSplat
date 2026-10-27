#!/usr/bin/env python3
"""Stand-in for the Brush binary, for the progress demo. No GPU, no training.

Reproduces what matters for progress parsing: ordinary log lines on stdout,
and the indicatif training bar on stderr, drawn ONLY when stderr is a
terminal and redrawn in place with "\\r" plus ANSI colors, exactly the way
the real binary behaves. On a plain pipe (the old runner) the bar is never
drawn, which is why training used to report nothing.

Template copied from the release binary:
  [{elapsed}] {bar:40.cyan/blue} {pos:>7}/{len:7} {msg} ({per_sec}, {eta} remaining)
"""

import argparse
import math
import os
import random
import struct
import sys
import time
from pathlib import Path

PLY_FIELDS = ("x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
              "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3")


def write_splat(path: Path, count: int, rng: random.Random) -> None:
    """A real binary Gaussian-splat PLY (Brush/3DGS layout), random points."""
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {count}"]
    header += [f"property float {f}" for f in PLY_FIELDS] + ["end_header"]
    rows = bytearray()
    for _ in range(count):
        r = rng.random() ** 0.5 * 2.0
        a, b = rng.uniform(0, 2 * math.pi), rng.uniform(-1, 1)
        x, y, z = r * math.cos(a) * (1 - b * b) ** 0.5, r * math.sin(a) * (1 - b * b) ** 0.5, r * b
        scale = math.log(rng.uniform(0.005, 0.05)) if rng.random() > 0.01 else 1.5  # a few giants
        rows += struct.pack("<17f", x, y, z, 0, 0, 0, rng.uniform(-1, 1), rng.uniform(-1, 1),
                            rng.uniform(-1, 1), rng.uniform(-4, 4), scale, scale, scale, 1, 0, 0, 0)
    path.write_bytes(("\n".join(header) + "\n").encode() + bytes(rows))

CYAN, BLUE, RESET, CLEAR = "\x1b[36m", "\x1b[34m", "\x1b[0m", "\x1b[2K"


def human_duration(seconds: float) -> str:
    """indicatif's HumanDuration: '12 seconds', '3 minutes', '1 hour'."""
    for unit, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        if seconds >= size or unit == "second":
            n = max(0, round(seconds / size))
            return f"{n} {unit}{'' if n == 1 else 's'}"
    return "0 seconds"


def draw(pos: int, total: int, start: float, rate: float) -> None:
    elapsed = int(time.monotonic() - start)
    filled = int(40 * pos / total)
    bar = f"{CYAN}{'█' * filled}{BLUE}{'░' * (40 - filled)}{RESET}"
    eta = (total - pos) / rate if rate > 0 else 0
    line = (f"[{elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}] {bar} "
            f"{pos:>7}/{total:<7}  ({rate:.4f}/s, {human_duration(eta)} remaining)")
    sys.stderr.write(f"\r{CLEAR}{line}")
    sys.stderr.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", nargs="?")
    ap.add_argument("--export-path", default=".")
    ap.add_argument("--total-steps", "--total-train-iters", dest="total", type=int, default=3000)
    ap.add_argument("--export-every", type=int, default=1000)
    ap.add_argument("--speed", type=float, default=110.0, help="steps per second")
    args, _unknown = ap.parse_known_args()

    is_tty = os.isatty(sys.stderr.fileno())
    print("Brush (demo stand-in) — loading dataset", flush=True)
    time.sleep(0.8)
    print("Loaded 40 images, 1 camera", flush=True)

    start = time.monotonic()
    pos, last_draw = 0, 0.0
    rng = random.Random(7)
    while pos < args.total:
        # Rate wobbles like a real run: densification slows it down mid-way.
        slowdown = 0.6 if args.total * 0.3 < pos < args.total * 0.6 else 1.0
        rate = args.speed * slowdown * rng.uniform(0.85, 1.15)
        time.sleep(0.05)
        pos = min(args.total, pos + max(1, round(rate * 0.05)))
        now = time.monotonic()
        if is_tty and (now - last_draw >= 0.1 or pos == args.total):
            draw(pos, args.total, start, rate)
            last_draw = now
        if pos % args.export_every < max(1, round(rate * 0.05)):
            if is_tty:
                sys.stderr.write("\r" + CLEAR)
            write_splat(Path(args.export_path) / f"export_{pos}.ply", 4000, rng)
            print(f"Exported checkpoint export_{pos}.ply", flush=True)
    if is_tty:
        sys.stderr.write("\n")
    write_splat(Path(args.export_path) / f"export_{args.total}.ply", 4000, rng)
    print("Training finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
