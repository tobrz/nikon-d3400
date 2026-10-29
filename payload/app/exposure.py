"""Exposure that follows the light: a ladder of (shutter, ISO) steps from dark to bright, moved one rung at a time
by how bright the last frame came out (the rpi-timelapse approach, in third stops).

The shutter lengthens first (cleaner files), then the ISO climbs once the shutter is at its longest. Needs the mode
dial on M.
"""

# Brightness bands (mean 0-255 of the frame) that look right.
NIGHT = (35, 80)      # aurora: dark sky, glow and stars visible, nothing blown out
DAY = (95, 140)       # timelapse: a normal-looking scene


def shutters(longest, shortest=1 / 4000):
    """Third-stop shutter times from shortest up to exactly longest, as seconds. The camera snaps each to its
    nearest real speed."""
    out = []
    k = 0
    while True:
        t = longest * 2 ** (-k / 3)
        if t < shortest * 0.9:
            break
        out.append(round(t, 6))
        k += 1
    return sorted(out)


def ladder(longest, base_iso=100, max_iso=6400, shortest=1 / 4000):
    """Rungs from darkest to brightest: every shutter at base ISO, then the longest shutter at higher ISOs."""
    times = shutters(longest, shortest)
    rungs = [(t, base_iso) for t in times]
    # ISO in third stops as well, so every rung is the same 1/3 stop (the body snaps to its nearest ISO).
    k = 1
    while base_iso * 2 ** (k / 3) <= max_iso * 1.01:
        rungs.append((times[-1], round(base_iso * 2 ** (k / 3))))
        k += 1
    return rungs


def nearest_rung(rungs, seconds, iso):
    target = seconds * iso
    return min(range(len(rungs)), key=lambda i: abs(rungs[i][0] * rungs[i][1] - target) / target)


class Ramp:
    def __init__(self, rungs, start, band):
        self.rungs = rungs
        self.index = max(0, min(len(rungs) - 1, start))
        self.low, self.high = band

    @property
    def current(self):
        return self.rungs[self.index]

    def step(self, mean):
        """Move toward the band after a frame of brightness mean. Far off moves 3 rungs (a full stop), else 1."""
        if mean is None:
            return self.current
        if mean < self.low:
            jump = 3 if mean < self.low / 2 else 1
            self.index = min(len(self.rungs) - 1, self.index + jump)
        elif mean > self.high:
            jump = 3 if mean > min(250, self.high * 1.6) else 1
            self.index = max(0, self.index - jump)
        return self.current

    def at_limit(self, mean):
        return (mean < self.low and self.index == len(self.rungs) - 1) or (mean > self.high and self.index == 0)
