"""Pixels from pictures, without PIL: ffmpeg decodes a JPEG to raw bytes at a fixed size, then plain Python measures it.

brightness and aurora_score steer the aurora watch (exposure ramp, "is it actually showing").
focus_metrics is the star focus assist: how tight the brightest star is in a live-view frame.
"""

import json
import os
import subprocess
import threading

SMALL = (96, 64)          # enough to judge exposure and colour
FOCUS = (600, 400)        # the D3400 live view is about 640x424
STAR_BOX = 15             # half-width of the square measured around the brightest point

_scores_lock = threading.Lock()


class ImagingError(RuntimeError):
    pass


def decode(path, size, gray=False):
    """Raw RGB (or gray) bytes of the picture scaled to size. Width*height*(1 or 3) long."""
    w, h = size
    try:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-vf", f"scale={w}:{h}",
             "-f", "rawvideo", "-pix_fmt", "gray" if gray else "rgb24", "-"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImagingError("Couldn't read the picture: " + str(exc)) from exc
    want = w * h * (1 if gray else 3)
    if done.returncode != 0 or len(done.stdout) < want:
        raise ImagingError("Couldn't read the picture.")
    return done.stdout[:want]


def luma(r, g, b):
    return (299 * r + 587 * g + 114 * b) // 1000


def brightness(rgb):
    """Mean brightness 0-255 of an RGB buffer."""
    n = len(rgb) // 3
    if not n:
        return 0.0
    return sum(luma(rgb[i], rgb[i + 1], rgb[i + 2]) for i in range(0, n * 3, 3)) / n


def aurora_score(rgb, size=SMALL):
    """Percent of the sky (top 70% of the frame) that glows aurora green.

    Green aurora is the 557.7 nm oxygen line: green clearly above red and blue and bright enough to be more than
    sky noise. Street lights are orange or white, so they don't count.
    """
    w, h = size
    rows = int(h * 0.7)
    hits = total = 0
    for y in range(rows):
        base = y * w * 3
        for x in range(w):
            i = base + x * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            total += 1
            if g >= 35 and g > r * 1.25 and g > b * 1.1 and g < 250:
                hits += 1
    return round(100.0 * hits / total, 1) if total else 0.0


def measure(path):
    """Brightness and aurora score of a saved picture."""
    rgb = decode(path, SMALL)
    return {"mean": round(brightness(rgb), 1), "aurora": aurora_score(rgb)}


def histogram(gray, bins=32):
    counts = [0] * bins
    for v in gray:
        counts[v * bins // 256] += 1
    top = max(counts) or 1
    return [round(c / top, 3) for c in counts]


def focus_metrics(path):
    """How sharp the brightest point is. Smaller hfd = tighter star = better focus.

    hfd is the half-flux diameter in live-view pixels: the diameter of the circle holding half the star's light above
    the background. It is the measure astrophotographers focus on, steadier than "peak brightness".
    """
    return focus_from_gray(decode(path, FOCUS, gray=True), FOCUS)


def focus_from_gray(gray, size):
    w, h = size
    peak = max(gray)
    at = gray.index(peak)
    px, py = at % w, at // w
    x0, x1 = max(0, px - STAR_BOX), min(w, px + STAR_BOX + 1)
    y0, y1 = max(0, py - STAR_BOX), min(h, py + STAR_BOX + 1)
    box = [(x, y, gray[y * w + x]) for y in range(y0, y1) for x in range(x0, x1)]
    values = sorted(v for _, _, v in box)
    background = values[len(values) // 4]
    flux = [(x, y, v - background) for x, y, v in box if v > background]
    total = sum(f for _, _, f in flux)
    hfd = None
    if total > 0:
        cx = sum(x * f for x, _, f in flux) / total
        cy = sum(y * f for _, y, f in flux) / total
        # HFD = 2 * flux-weighted mean distance from the centroid.
        hfd = round(2 * sum(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 * f for x, y, f in flux) / total, 2)
    # Overall contrast for scenes without a star: mean absolute neighbour difference.
    step = 4
    edges = n = 0
    for y in range(0, h - step, step):
        row = y * w
        for x in range(0, w - step, step):
            v = gray[row + x]
            edges += abs(v - gray[row + x + step]) + abs(v - gray[row + step * w + x])
            n += 2
    return {
        "hfd": hfd,
        "peak": peak,
        "saturated": peak >= 250,
        "x": round(px / w, 4),
        "y": round(py / h, 4),
        "contrast": round(edges / n, 2) if n else 0,
        "background": background,
        "histogram": histogram(gray),
        "star": peak - background >= 40,
    }


# Scores of saved pictures, keyed by file name, so the page and the app can show "aurora" badges and the best frames.

def scores_path(shots_dir):
    return os.path.join(os.path.dirname(shots_dir.rstrip("/")), "scores.json")


def load_scores(shots_dir):
    try:
        with open(scores_path(shots_dir)) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_score(shots_dir, name, score):
    with _scores_lock:
        data = load_scores(shots_dir)
        data[name] = score
        tmp = scores_path(shots_dir) + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, scores_path(shots_dir))


def forget_scores(shots_dir, names):
    with _scores_lock:
        data = load_scores(shots_dir)
        changed = False
        for name in names:
            if data.pop(name, None) is not None:
                changed = True
        if changed:
            with open(scores_path(shots_dir), "w") as handle:
                json.dump(data, handle)
