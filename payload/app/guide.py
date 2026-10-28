"""Field guide for the D3400.

The steps are local and specific to this camera. A small on-device model,
when one is installed, may only rephrase those steps. It does not invent
settings. Focus and aim stay on the photographer; the body cannot autofocus
the Milky Way over USB.
"""

import json
import shutil
import subprocess
import urllib.request

CROP = 1.5


def classify(text):
    low = text.lower()
    if any(word in low for word in ("milky", "galaxy", "stars", "star trail", "night sky", "astro")):
        return "milky"
    if any(word in low for word in ("lightning", "lightening", "thunder", "storm bolt")):
        return "lightning"
    if any(word in low for word in ("timelapse", "time lapse", "time-lapse", "interval")):
        return "timelapse"
    if any(word in low for word in ("night", "low light", "dark")):
        return "night"
    if any(word in low for word in ("what can", "which control", "camera info", "everything", "status")):
        return "info"
    return "general"


def _shutter_for(focal_mm):
    """Stricter crop-sensor rule so stars stay points: 300 / (crop * focal)."""
    focal = focal_mm or 18
    seconds = 300 / (CROP * focal)
    return max(2, round(seconds))


def _focal_from_configs(configs):
    for item in configs or []:
        if item.get("key") in ("focallength", "focal-length") or "focal" in item.get("label", "").lower():
            digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in str(item.get("current", "")))
            parts = digits.split()
            if parts:
                try:
                    return float(parts[0])
                except ValueError:
                    return None
    return None


def plan(text, configs=None):
    kind = classify(text)
    focal = _focal_from_configs(configs)
    shutter = _shutter_for(focal)
    focal_label = f"{focal:g} mm" if focal else "the kit lens at 18 mm"
    builders = {
        "milky": _milky,
        "lightning": _lightning,
        "timelapse": _timelapse,
        "night": _night,
        "info": _info,
        "general": _general,
    }
    built = builders[kind](focal_label, shutter, text)
    built["kind"] = kind
    built["settings"] = built.get("settings") or {}
    return built


def _milky(focal_label, shutter, _text):
    return {
        "title": "Milky Way on the D3400",
        "ready_step": 6,
        "settings": {
            "iso": "1600",
            "f-number": "3.5",
            "shutterspeed": str(shutter),
            "whitebalance": "Daylight",
            "exposurecompensation": "0",
        },
        "speech": (
            f"We'll shoot the Milky Way on the D3400 at {focal_label}. "
            f"The shutter I want is {shutter} seconds so stars stay points on this DX body. "
            "I can set exposure over USB when the camera offers those controls. "
            "Focus and aim stay in your hands."
        ),
        "steps": [
            {
                "title": "Put the body in Manual",
                "body": "Turn the mode dial to M. Pop the lens hood off if it is a narrow one, and point the camera at the darkest part of the sky you can see.",
            },
            {
                "title": "Open the lens and switch it to manual focus",
                "body": "Zoom to 18 mm. Set the aperture ring by the body, not a lens ring: the widest this kit goes is f/3.5. Slide the lens switch from A to M. Turn VR off if the lens has that switch.",
            },
            {
                "title": "Focus on a bright star",
                "body": "Press the Lv button. Press the magnifying glass with the plus until a bright star or distant light is huge. Turn the focus ring until that point is as small and hard as you can make it. Do not touch the ring after that. USB cannot do this focus for you.",
            },
            {
                "title": "Compose",
                "body": "Put the horizon low in the frame if you want foreground, or leave it out for only sky. A 10-second test frame tells you if the aim is right before a long run.",
            },
            {
                "title": "Kill the shake",
                "body": "Use a tripod. Set Remote control (ML-L3) or the 2-second self-timer in the release-mode menu so your hand is off the body when the shutter moves. Cover the viewfinder with your hand or the cap so stray light does not fog the frame.",
            },
            {
                "title": "Exposure I will try to set",
                "body": f"ISO 1600, f/3.5, {shutter} seconds, daylight white balance. The D3400 gets ugly fast above ISO 3200, so we stay at 1600 unless the test frame is much too dark. Long-exposure noise reduction off if you plan to stack frames, on if this is a single JPEG.",
            },
            {
                "title": "Open the shutter",
                "body": "When the star is sharp and the tripod is still, tell me to apply the exposure and open the shutter. Look at the test frame: if stars trail, shorten the shutter; if the sky is mud, add one stop of ISO, not three.",
            },
        ],
    }


def _lightning(focal_label, _shutter, _text):
    return {
        "title": "Lightning on the D3400",
        "ready_step": 4,
        "settings": {
            "iso": "200",
            "f-number": "8",
            "shutterspeed": "5",
        },
        "speech": (
            "Lightning is a dark frame that waits for the bolt. "
            f"At {focal_label}, start at ISO 200, f/8, and a 5 second shutter, then use spray mode "
            "or a light sensor on GPIO 17. The D3400 has no bulb-over-USB guarantee, so we try the "
            "fastest trigger the body accepts and tell you if it refuses."
        ),
        "steps": [
            {
                "title": "Manual, and aim where the sky is active",
                "body": "Mode dial to M. Focus once on a distant light or the horizon, then switch the lens to M so it does not hunt in the dark. Compose on the storm, not on the ground.",
            },
            {
                "title": "Exposure for a bolt, not for the daytime scene",
                "body": "ISO 100 to 400. Aperture f/8. Shutter 2 to 8 seconds. A short shutter freezes the bolt. A longer one catches more strikes and also more ambient glow. Start at 5 seconds.",
            },
            {
                "title": "Optional sensor",
                "body": "A phototransistor module with a digital output can go to GPIO 17, pin 11, 3.3 volts only. When that pin goes high the Pi fires a burst. Without the sensor, use spray: the Pi trips the shutter as fast as USB allows for as long as you leave it armed.",
            },
            {
                "title": "What USB can and cannot promise",
                "body": "A bolt is faster than a tether download. Spray mode uses trigger-capture and downloads the new frames after the burst, so the card in the camera holds them if the cable hiccups. If this firmware refuses remote release, set the D3400 release mode to Quick-response remote and we can drive an infrared LED later.",
            },
            {
                "title": "Arm it",
                "body": "Apply the exposure, then arm lightning. Stay out of the rain with the Pi, and keep the camera battery warm. Stop the run from the phone when the cell passes.",
            },
        ],
    }


def _timelapse(focal_label, _shutter, _text):
    return {
        "title": "Tripod timelapse",
        "ready_step": 3,
        "settings": {},
        "speech": (
            f"The D3400 has no interval timer of its own. The Pi will release the shutter on a cadence "
            f"and pull each frame off the card. At {focal_label}, pick an interval longer than the shutter "
            "plus about three seconds of USB time."
        ),
        "steps": [
            {
                "title": "Lock the shot down",
                "body": "Tripod, manual mode, manual focus, white balance fixed (not auto). Auto white balance flickers across a day-to-night run.",
            },
            {
                "title": "Pick the interval",
                "body": "Clouds: 3 to 5 seconds. Moving sun or a plant: 15 to 60 seconds. A night sky run: match the shutter, then add 3 seconds. The page will refuse an interval shorter than 3 seconds.",
            },
            {
                "title": "Power",
                "body": "A multi-hour run will empty the D3400 battery. Start full, and turn off image review so the screen does not stay lit after every frame.",
            },
            {
                "title": "Start it from the Timelapse panel",
                "body": "Set the count or leave it open-ended and press stop from the phone. Frames land in the Shots list as they come off the camera.",
            },
        ],
    }


def _night(focal_label, shutter, _text):
    return {
        "title": "Night exposure",
        "ready_step": 3,
        "settings": {
            "iso": "800",
            "f-number": "3.5",
            "shutterspeed": str(max(shutter, 8)),
        },
        "speech": (
            f"A general night frame at {focal_label}. ISO 800, widest aperture, "
            f"and at least {max(shutter, 8)} seconds. Take one test before you walk away."
        ),
        "steps": [
            {
                "title": "Manual focus on something with an edge",
                "body": "Live view, magnify, focus on a light, a roofline, or a star. Then switch the lens to M.",
            },
            {
                "title": "Tripod and a delayed release",
                "body": "2-second timer or the remote. The D3400's mirror slap shows up in a multi-second frame if your hand is still on the body.",
            },
            {
                "title": "Exposure",
                "body": "ISO 800, f/3.5, shutter long enough that the histogram is off the left wall but not piled on the right. I will try to set that over USB.",
            },
            {
                "title": "Open the shutter once",
                "body": "Check the frame on the phone preview. One stop at a time after that.",
            },
        ],
    }


def _info(_focal, _shutter, _text):
    return {
        "title": "What we can see",
        "ready_step": 0,
        "settings": {},
        "speech": "Every control in the Controls panel is whatever this D3400 just enumerated over USB. Read-only rows are facts. The writable rows are the ones I can change.",
        "steps": [
            {
                "title": "Plug the camera in and wake it",
                "body": "Micro-USB on the camera to the Pi's USB host port. Half-press the shutter so the body does not sleep. Then open Controls. If the list is empty, the body refused PTP remote control and the page will show the gphoto2 error.",
            }
        ],
    }


def _general(_focal, _shutter, text):
    return {
        "title": "Ask for a setup",
        "ready_step": 0,
        "settings": {},
        "speech": (
            "I can walk a Milky Way, a lightning watch, a night frame, or a tripod timelapse. "
            f"You asked: {text}"
        ),
        "steps": [
            {
                "title": "Try one of these",
                "body": "\"I want a night shot of the Milky Way.\" \"Set up for lightning.\" \"Timelapse clouds for an hour.\" \"What can you see on the camera?\"",
            }
        ],
    }


def rephrase(plan_dict):
    """Ask a local model to speak the steps. Fall back to the written speech."""
    speech = plan_dict["speech"]
    steps = "\n".join(f"{i + 1}. {step['title']}: {step['body']}" for i, step in enumerate(plan_dict["steps"]))
    prompt = (
        "You are standing at a tripod with a Nikon D3400. "
        "Rephrase the plan below in a few short sentences a person can follow in the dark. "
        "Do not add camera settings that are not written here. "
        "Do not claim you focused the lens.\n\n"
        f"{speech}\n{steps}"
    )
    spoken = _ollama(prompt)
    if spoken:
        return spoken, "ollama"
    return speech, "built-in"


def _ollama(prompt):
    if not shutil.which("ollama"):
        return None
    body = json.dumps({"model": "qwen2.5:0.5b", "prompt": prompt, "stream": False}).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode())
    except Exception:
        return None
    text = (payload.get("response") or "").strip()
    return text or None
