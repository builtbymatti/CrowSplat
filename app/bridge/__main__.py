"""Entry point the CrowSplat app launches: ``python -m app.bridge <command>``.

    probe                 machine, tools and engine status (one "done" event)
    install <engine>      install one engine, streaming its output
    run <job.json | ->    run a job (see jobs.JOBS), streaming events

Cancel a run with SIGTERM: the running engine is stopped, the job reports
``done`` with ``"cancelled": true`` and the process exits 130.
"""

import argparse
import json
import logging
import signal
import sys
import traceback

from app.bridge.events import open_channel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.bridge")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("probe")
    inst = sub.add_parser("install")
    inst.add_argument("engine")
    run = sub.add_parser("run")
    run.add_argument("job", help="path to a job JSON file, or - for stdin")
    args = ap.parse_args(argv)

    channel = open_channel()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")

    if args.command == "probe":
        from app.bridge.probe import probe
        channel.done(True, **probe())
        return 0

    if args.command == "install":
        from app.bridge.probe import install
        channel.begin("install", f"Installing {args.engine}", 0, 1)
        ok = install(args.engine, channel)
        channel.done(ok, "" if ok else f"Could not install {args.engine}.", engine=args.engine)
        return 0 if ok else 1

    from app.bridge.jobs import JOBS, Cancelled, JobContext

    raw = sys.stdin.read() if args.job == "-" else open(args.job, encoding="utf-8").read()
    job = json.loads(raw)
    runner = JOBS.get(job.get("job"))
    if runner is None:
        channel.done(False, f"Unknown job: {job.get('job')!r}")
        return 2

    ctx = JobContext(channel)
    channel.on_broken = ctx.cancel
    # The app closing its pipe must not kill us mid-write; on_broken cancels.
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: ctx.cancel())
    signal.signal(signal.SIGINT, lambda *_: ctx.cancel())
    try:
        result = runner(ctx, job)
        channel.done(True, "", **(result or {}))
        return 0
    except Cancelled:
        channel.done(False, "Cancelled", cancelled=True)
        return 130
    except Exception as e:
        traceback.print_exc()
        if ctx.cancelled.is_set():
            channel.done(False, "Cancelled", cancelled=True)
            return 130
        channel.done(False, str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
