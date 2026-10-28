"""Replace the installed console from the public git repo.

Pictures, the Wi-Fi list, and the page password live under /var/lib/nikon-d3400
and are left in place. The standalone access point has no route to GitHub.
"""

import os
import shutil
import subprocess

REPO = "https://github.com/tobrz/nikon-d3400.git"
BRANCH = "main"


class UpdateError(Exception):
    pass


def install_root():
    return os.environ.get("NIKON_INSTALL", "/opt/nikon-d3400")


def cache_root():
    data = os.environ.get("NIKON_DATA", "/var/lib/nikon-d3400")
    return os.environ.get("NIKON_SRC", os.path.join(data, "src"))


def revision_path():
    data = os.environ.get("NIKON_DATA", "/var/lib/nikon-d3400")
    return os.path.join(data, "revision")


def read_revision():
    try:
        with open(revision_path()) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def write_revision(rev):
    path = revision_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write((rev or "") + "\n")


def has_default_route(route_text):
    return any(line.startswith("default") for line in route_text.splitlines())


def copy_payload(payload_dir, install_dir):
    """Copy a repo payload/ tree onto the install directory."""
    if not os.path.isdir(os.path.join(payload_dir, "app")):
        raise UpdateError("The checkout has no payload/app directory.")
    os.makedirs(install_dir, exist_ok=True)
    skip_names = {"__pycache__"}
    for name in os.listdir(payload_dir):
        if name in skip_names or name.endswith(".pyc"):
            continue
        src = os.path.join(payload_dir, name)
        dst = os.path.join(install_dir, name)
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            elif os.path.lexists(dst):
                os.remove(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
    for rel in ("bootstrap.sh", "nikon-install.sh", "app/server.py", "app/wifi_bringup.py"):
        path = os.path.join(install_dir, rel)
        if os.path.isfile(path):
            os.chmod(path, 0o755)


def _run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("Timed out: " + " ".join(cmd)) from exc
    except OSError as exc:
        raise UpdateError(str(exc)) from exc


def _failure(proc, fallback):
    text = (proc.stderr or proc.stdout or fallback).strip()
    return text or fallback


def check_route():
    if shutil.which("ip") is None:
        return
    proc = _run(["ip", "route"], 5)
    if proc.returncode != 0:
        return
    if not has_default_route(proc.stdout):
        raise UpdateError(
            "This Pi has no route to the internet. Plug in ethernet, or join a Wi-Fi "
            "network that can reach GitHub, then try again. While the Pi is only the "
            "Nikon-D3400 access point, this button cannot download an update."
        )


def ensure_git():
    if shutil.which("git"):
        return
    if shutil.which("apt-get") is None:
        raise UpdateError("git is not installed, and there is no apt-get to install it.")
    update = _run(["apt-get", "update"], 180)
    if update.returncode != 0:
        raise UpdateError(_failure(update, "apt-get update failed."))
    install = _run(["apt-get", "install", "-y", "git"], 180)
    if install.returncode != 0 or shutil.which("git") is None:
        raise UpdateError(_failure(install, "Could not install git."))


def fetch_repo(cache):
    if os.path.isdir(os.path.join(cache, ".git")):
        fetch = _run(["git", "-C", cache, "fetch", "--depth", "1", "origin", BRANCH], 180)
        if fetch.returncode != 0:
            raise UpdateError(_failure(fetch, "git fetch failed."))
        reset = _run(["git", "-C", cache, "reset", "--hard", "origin/" + BRANCH], 30)
        if reset.returncode != 0:
            raise UpdateError(_failure(reset, "git reset failed."))
    else:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        if os.path.isdir(cache):
            shutil.rmtree(cache)
        clone = _run(
            ["git", "clone", "--depth", "1", "--branch", BRANCH, REPO, cache],
            180,
        )
        if clone.returncode != 0:
            raise UpdateError(_failure(clone, "git clone failed."))
    rev = _run(["git", "-C", cache, "rev-parse", "--short", "HEAD"], 15)
    if rev.returncode != 0:
        raise UpdateError("Could not read the new revision.")
    return rev.stdout.strip()


def install_units(install_dir):
    units = os.path.join(install_dir, "units")
    dest_dir = "/etc/systemd/system"
    if not os.path.isdir(units) or not os.path.isdir(dest_dir):
        return
    for name in os.listdir(units):
        if name.endswith(".service"):
            shutil.copy2(os.path.join(units, name), os.path.join(dest_dir, name))
    if shutil.which("systemctl"):
        _run(["systemctl", "daemon-reload"], 30)


def schedule_restart():
    if shutil.which("systemd-run") is None:
        return False
    proc = _run(
        [
            "systemd-run",
            "--unit=nikon-update-restart",
            "--on-active=2s",
            "systemctl",
            "restart",
            "nikon-d3400.service",
        ],
        20,
    )
    return proc.returncode == 0


def apply_update():
    check_route()
    ensure_git()
    cache = cache_root()
    rev = fetch_repo(cache)
    install = install_root()
    copy_payload(os.path.join(cache, "payload"), install)
    install_units(install)
    write_revision(rev)
    restarting = schedule_restart()
    return {
        "ok": True,
        "revision": rev,
        "repo": REPO,
        "restarting": restarting,
        "note": (
            "The page restarts in a couple of seconds. Refresh if it drops. "
            "Wi-Fi settings and pictures stay put. This updates the camera console. "
            "Raspberry Pi OS stays as it was imaged."
        ),
    }
