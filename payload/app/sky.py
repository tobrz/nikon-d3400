"""Clouds, moon and the 3-night aurora planner.

Clouds come from Open-Meteo (free, no key). Kp comes from NOAA's 3-day forecast. The moon is computed here from a
low-precision formula (good to about a degree), which is plenty for "is it up and how bright".
"""

import json
import math
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import aurora

CLOUD_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat:.3f}&longitude={lon:.3f}"
             "&hourly=cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high&forecast_days=4&timezone=UTC")
KP_FORECAST_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
CACHE_SECONDS = 1800
# Geomagnetic north pole (IGRF, mid-2020s). A dipole is close enough to say how far the aurora oval is from here.
POLE_LAT, POLE_LON = 80.8, -72.6

_cache = {}


class SkyError(RuntimeError):
    pass


def _fetch(url, timeout=20):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nikon-d3400-pi"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            value = json.loads(resp.read().decode())
    except Exception as exc:
        if hit:
            return hit[1]
        raise SkyError("Can't reach the forecast. The Pi needs internet.") from exc
    _cache[url] = (time.time(), value)
    return value


def _parse_utc(text):
    text = text.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(text)


# ---- clouds

def clouds(lat, lon):
    """Hourly cloud cover, {hour (UTC datetime): {"total", "low", "mid", "high"}}."""
    data = _fetch(CLOUD_URL.format(lat=float(lat), lon=float(lon)))
    hourly = data.get("hourly") or {}
    out = {}
    for i, t in enumerate(hourly.get("time") or []):
        def at(key):
            values = hourly.get(key) or []
            return values[i] if i < len(values) and values[i] is not None else None
        out[_parse_utc(t)] = {"total": at("cloud_cover"), "low": at("cloud_cover_low"),
                              "mid": at("cloud_cover_mid"), "high": at("cloud_cover_high")}
    return out


def cloud_now(lat, lon, now=None):
    now = now or datetime.now(timezone.utc)
    hour = now.replace(minute=0, second=0, microsecond=0)
    return clouds(lat, lon).get(hour)


# ---- Kp forecast

def kp_forecast():
    """[(start UTC, kp, observed/estimated/predicted)] in 3-hour blocks."""
    rows = _fetch(KP_FORECAST_URL)
    if rows and isinstance(rows[0], list):
        head = rows[0]
        rows = [dict(zip(head, row)) for row in rows[1:]]
    out = []
    for row in rows:
        try:
            out.append((_parse_utc(row["time_tag"]), float(row["kp"]), row.get("observed") or ""))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def kp_at(blocks, when):
    best = None
    for start, kp, _ in blocks:
        if start <= when < start + timedelta(hours=3):
            return kp
        if start <= when:
            best = kp
    return best


# ---- geomagnetism

def magnetic_latitude(lat, lon):
    p, pl = math.radians(lat), math.radians(POLE_LAT)
    dl = math.radians(lon - POLE_LON)
    return math.degrees(math.asin(math.sin(p) * math.sin(pl) + math.cos(p) * math.cos(pl) * math.cos(dl)))


def kp_needed(lat, lon):
    """Kp at which the aurora usually shows low on the northern horizon from here.

    The oval's equator-side edge sits near magnetic latitude 66.5 - 2*Kp, and a camera picks up glow about 5° of
    magnetic latitude (~550 km) beyond that.
    """
    return max(0.0, min(9.0, (61.5 - abs(magnetic_latitude(lat, lon))) / 2))


def kp_chance(kp, needed):
    """0-100: how likely the aurora is in a camera's view at this Kp. 50% right at the needed Kp."""
    if kp is None:
        return 0
    return round(100 / (1 + math.exp(-1.6 * (kp - needed))))


# ---- moon

def _julian(when):
    return when.timestamp() / 86400.0 + 2440587.5


def moon(lat, lon, when=None):
    """Altitude (degrees) and illuminated fraction (0-1) of the moon."""
    when = when or datetime.now(timezone.utc)
    d = _julian(when) - 2451545.0
    rad = math.radians
    L = rad((218.316 + 13.176396 * d) % 360)
    M = rad((134.963 + 13.064993 * d) % 360)
    F = rad((93.272 + 13.229350 * d) % 360)
    lam = L + rad(6.289) * math.sin(M)
    beta = rad(5.128) * math.sin(F)
    eps = rad(23.439 - 0.0000004 * d)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    gmst = rad((280.46061837 + 360.98564736629 * d) % 360)
    ha = gmst + rad(lon) - ra
    phi = rad(lat)
    alt = math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(ha))
    # Sun's ecliptic longitude, for the phase.
    g = rad((357.529 + 0.98560028 * d) % 360)
    sun = rad((280.459 + 0.98564736 * d) % 360) + rad(1.915) * math.sin(g) + rad(0.020) * math.sin(2 * g)
    elong = math.acos(max(-1.0, min(1.0, math.cos(beta) * math.cos(lam - sun))))
    return {"altitude": round(math.degrees(alt), 1), "illumination": round((1 - math.cos(elong)) / 2, 2)}


# ---- planner

def night_hours(lat, lon, start, end):
    """Half-past UTC hours between start and end when the sun is below -12°."""
    hours = []
    t = start.replace(minute=30, second=0, microsecond=0)
    if t < start:
        t += timedelta(hours=1)
    while t < end:
        if aurora.sun_altitude(lat, lon, t) < -12:
            hours.append(t)
        t += timedelta(hours=1)
    return hours


def hour_score(chance, cloud, moon_alt, moon_illum):
    clear = 1 - (cloud if cloud is not None else 50) / 100.0
    moonlight = 1 - 0.5 * moon_illum if moon_alt > 0 else 1.0
    return round(chance * clear * moonlight)


def verdict(score):
    if score >= 40:
        return "Good"
    if score >= 15:
        return "Maybe"
    return "Poor"


def plan(lat, lon, nights=3, now=None):
    """The next few nights from here: best hour, Kp, clouds, moon, and a one-word verdict."""
    lat, lon = float(lat), float(lon)
    now = now or datetime.now(timezone.utc)
    blocks = kp_forecast()
    try:
        cover = clouds(lat, lon)
        cloud_note = ""
    except SkyError:
        cover, cloud_note = {}, "No cloud forecast (offline?)."
    needed = kp_needed(lat, lon)
    out = []
    # Each "night" runs from one local solar noon to the next; tonight starts now.
    noon_offset = timedelta(hours=lon / 15.0)
    day = (now + noon_offset).replace(hour=12, minute=0, second=0, microsecond=0) - noon_offset
    if day > now:
        day -= timedelta(days=1)
    for n in range(nights):
        start = max(now, day + timedelta(days=n))
        dark = night_hours(lat, lon, start, day + timedelta(days=n + 1))
        hours = []
        for t in dark:
            kp = kp_at(blocks, t)
            c = cover.get(t.replace(minute=0))
            total = c["total"] if c else None
            m = moon(lat, lon, t)
            chance = kp_chance(kp, needed)
            hours.append({
                "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "kp": kp, "chance": chance, "cloud": total,
                "moon_altitude": m["altitude"], "moon": m["illumination"],
                "score": hour_score(chance, total, m["altitude"], m["illumination"]),
            })
        best = max(hours, key=lambda h: h["score"]) if hours else None
        known_clouds = [h["cloud"] for h in hours if h["cloud"] is not None]
        mid = dark[len(dark) // 2] if dark else start
        out.append({
            "date": (day + timedelta(days=n) + noon_offset).strftime("%Y-%m-%d"),
            "dark_start": dark[0].strftime("%Y-%m-%dT%H:%M:%SZ") if dark else None,
            "dark_end": (dark[-1] + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ") if dark else None,
            "kp_max": max((h["kp"] for h in hours if h["kp"] is not None), default=None),
            "cloud_mean": round(sum(known_clouds) / len(known_clouds)) if known_clouds else None,
            "moon": moon(lat, lon, mid)["illumination"],
            "best": best,
            "score": best["score"] if best else 0,
            "verdict": verdict(best["score"]) if best else "No dark hours",
            "hours": hours,
        })
    return {"kp_needed": round(needed, 1), "magnetic_latitude": round(magnetic_latitude(lat, lon), 1),
            "nights": out, "note": cloud_note}
