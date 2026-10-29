"""Northern lights: NOAA's forecast for the saved location, where to aim, and whether it is dark enough.

Sources (no key): the SWPC OVATION model, a 30-90 minute aurora probability on a 1° grid, and the 1-minute planetary
Kp index. "Visible" is the strongest probability in the sky you can see from here: aurora sits about 100-300 km up,
so a band up to ~1000 km away still shows low on the horizon. The aim is the compass bearing to that strongest point.
"""
import json
import math
import time
import urllib.request
from datetime import datetime, timezone

OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
EARTH_KM = 6371.0
AURORA_KM = 110.0          # lower edge of the glow
VIEW_KM = 1000.0           # how far away aurora still clears the horizon in practice
CACHE_SECONDS = 300

_cache = {"ovation": (0.0, None), "kp": (0.0, None)}


class AuroraError(Exception):
    pass


def _fetch(url, key, timeout=20):
    stamp, value = _cache[key]
    if value is not None and time.time() - stamp < CACHE_SECONDS:
        return value
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            value = json.loads(resp.read().decode())
    except Exception as exc:
        if value is not None:
            return value            # keep the last good copy through a short outage
        raise AuroraError("Can't reach NOAA's space weather feed. The Pi needs internet (house Wi-Fi or Starlink).") from exc
    _cache[key] = (time.time(), value)
    return value


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2):
    """Initial compass bearing in degrees, 0 = north, 90 = east."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def cardinal(deg):
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((deg % 360) / 22.5 + 0.5) % 16]


def elevation(dist_km, height_km=AURORA_KM):
    """Angle above the horizon of a point height_km up, dist_km away along the ground."""
    theta = dist_km / EARTH_KM
    return math.degrees(math.atan2(math.cos(theta) - EARTH_KM / (EARTH_KM + height_km), math.sin(theta)))


def sun_altitude(lat, lon, when=None):
    """Sun's altitude in degrees (NOAA's simplified solar position). Below -12 is dark enough for aurora."""
    when = when or datetime.now(timezone.utc)
    day = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    solar_minutes = hour * 60 + eqtime + 4 * lon
    ha = math.radians(solar_minutes / 4 - 180)
    phi = math.radians(lat)
    cos_zen = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))


def sky(lat, lon, coordinates):
    """Visible chance, overhead chance, and where the strongest visible aurora is, from OVATION points."""
    best = None
    overhead = 0
    for clon, clat, prob in coordinates:
        if prob <= 0 or abs(clat - lat) > 12:
            continue
        clon = clon - 360 if clon > 180 else clon
        d = distance_km(lat, lon, clat, clon)
        if d < 60:
            overhead = max(overhead, prob)
        if d > VIEW_KM:
            continue
        # Nearer glow is higher in the sky and easier to see; far glow only counts near its full strength.
        weight = prob * (1 - 0.35 * d / VIEW_KM)
        if best is None or weight > best[0]:
            best = (weight, prob, clat, clon, d)
    if best is None:
        return {"visible": 0, "overhead": overhead, "bearing": None, "direction": "", "elevation": None, "distance_km": None}
    _, prob, clat, clon, d = best
    b = bearing(lat, lon, clat, clon)
    return {
        "visible": int(prob),
        "overhead": int(overhead),
        "bearing": round(b),
        "direction": cardinal(b),
        "elevation": round(max(0.0, elevation(d)), 1),
        "distance_km": round(d),
    }


def outlook(lat, lon, now=None):
    """Everything the app shows: chance, Kp, aim, darkness, and a sentence."""
    if lat is None or lon is None:
        raise AuroraError("Save a location first (Place, or Use this device's location).")
    data = _fetch(OVATION_URL, "ovation")
    result = sky(float(lat), float(lon), data.get("coordinates") or [])
    kp_now = None
    try:
        kp = _fetch(KP_URL, "kp")
        if kp:
            kp_now = kp[-1].get("estimated_kp", kp[-1].get("kp_index"))
    except AuroraError:
        pass
    sun = sun_altitude(float(lat), float(lon), now)
    dark = sun < -12
    result.update({
        "kp": kp_now,
        "forecast_time": data.get("Forecast Time"),
        "observed_time": data.get("Observation Time"),
        "sun_altitude": round(sun, 1),
        "dark": dark,
        "lat": float(lat),
        "lon": float(lon),
    })
    result["summary"] = summary(result)
    return result


def summary(r):
    chance = r["visible"]
    if not r["bearing"] and chance == 0:
        line = "No aurora in view from here right now."
    else:
        aim = f"Aim {r['direction']} ({r['bearing']}°)"
        if r["elevation"] is not None:
            aim += ", low on the horizon" if r["elevation"] < 15 else f", about {round(r['elevation'])}° up"
        line = f"{chance}% chance in view. {aim}."
    if not r["dark"]:
        line += " Not dark yet (sun at %s°)." % r["sun_altitude"]
    return line
