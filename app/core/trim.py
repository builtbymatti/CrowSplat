"""Shared trim-window helper (no Qt, no project imports)."""


def trim_window(start, end):
    """(start, duration) in seconds for a requested range, or (None, None).

    A pair that does not describe a forward span is ignored rather than
    passed on: ffmpeg would accept a zero or negative ``-t`` and produce no
    frames at all, which reads as a broken extraction rather than a bad
    setting.
    """
    if start is None and end is None:
        return None, None
    start = max(0.0, float(start or 0.0))
    if end is None:
        return (start or None), None
    end = float(end)
    if end <= start:
        return None, None
    return (start or None), end - start
