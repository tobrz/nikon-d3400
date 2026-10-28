"""Replace the installed console from the public git repo.

Pictures, the Wi-Fi list, and the page password live under /var/lib/nikon-d3400
and are left in place. The standalone access point has no route to GitHub.
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

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
    for rel in ("bootstrap.sh", "nikon-install.sh", "samba-setup.sh", "app/server.py", "app/wifi_bringup.py"):
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


def revisions_match(installed, remote):
    installed = (installed or "").strip()
    remote = (remote or "").strip()
    if not installed or not remote:
        return False
    return remote.startswith(installed) or installed.startswith(remote)


def github_repo():
    text = REPO[:-4] if REPO.endswith(".git") else REPO
    owner, name = text.rstrip("/").split("/")[-2:]
    return owner, name


def parse_commits(payload):
    """Commit messages from a GitHub compare object or a commits list. Newest first."""
    if isinstance(payload, dict):
        items = payload.get("commits") or []
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        message = ((item.get("commit") or {}).get("message") or "").strip()
        if not message:
            continue
        subject, _, body = message.partition("\n")
        found.append({
            "rev": (item.get("sha") or "")[:7],
            "subject": subject.strip(),
            "body": body.strip(),
        })
    found.reverse()
    return found


def parse_files(payload, limit=40):
    if not isinstance(payload, dict):
        return []
    items = payload.get("files") or []
    rows = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        name = (item.get("filename") or "").strip()
        status = (item.get("status") or "").strip()
        if name:
            rows.append((status + " " + name).strip())
    extra = len(items) - limit
    if extra > 0:
        rows.append(str(extra) + " more files")
    return rows


def format_update_log(installed, available, note, changes, files, changes_note):
    lines = [
        note,
        "Installed: " + (installed or "not recorded"),
        "Available: " + (available or "unknown"),
    ]
    if changes_note:
        lines.append(changes_note)
    if changes:
        lines.append("")
        for item in changes:
            lines.append((item.get("rev") or "") + "  " + (item.get("subject") or ""))
            body = (item.get("body") or "").strip()
            if body:
                lines.append(body)
            lines.append("")
    if files:
        lines.append("Files:")
        lines.extend(files)
    return "\n".join(lines).strip() + "\n"


def github_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nikon-d3400", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise UpdateError("GitHub returned " + str(exc.code) + ".") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise UpdateError("Could not read the commit list from GitHub. " + str(exc)) from exc


def lookup_changes(installed, remote):
    """Commits and files on main that are not in the installed revision."""
    owner, name = github_repo()
    base = (installed or "").strip()
    head = (remote or "").strip() or BRANCH
    recent = "https://api.github.com/repos/" + owner + "/" + name + "/commits?sha=" + BRANCH + "&per_page=15"
    if revisions_match(base, head):
        return [], [], ""
    if not base:
        payload = github_json(recent)
        return parse_commits(payload), [], "No installed revision is recorded. These are the latest commits on main."
    try:
        payload = github_json(
            "https://api.github.com/repos/" + owner + "/" + name + "/compare/" + base + "..." + head
        )
    except UpdateError as exc:
        if "GitHub returned 404" in str(exc):
            payload = github_json(recent)
            return parse_commits(payload), [], "GitHub did not find the installed revision. These are the latest commits on main."
        raise
    return parse_commits(payload), parse_files(payload), ""


def check_update():
    """Ask GitHub if main is newer, and list the commits since this Pi."""
    check_route()
    ensure_git()
    proc = _run(["git", "ls-remote", REPO, "refs/heads/" + BRANCH], 60)
    if proc.returncode != 0:
        raise UpdateError(_failure(proc, "Could not reach the git repo."))
    remote = (proc.stdout.split() or [""])[0]
    installed = read_revision()
    available = remote[:7]
    behind = not revisions_match(installed, remote)
    changes, files, changes_note = [], [], ""
    try:
        changes, files, changes_note = lookup_changes(installed, remote)
    except UpdateError as exc:
        changes_note = str(exc)
    if behind and changes:
        word = "commit" if len(changes) == 1 else "commits"
        note = (
            str(len(changes)) + " new " + word + " on main (" + (available or "unknown")
            + "). The list is below. Use Update from git to install."
        )
    elif behind:
        note = "An update is available (" + (available or "unknown") + "). Use Update from git to install it."
    else:
        note = "This Pi is already on " + (installed or available) + "."
    return {
        "installed": installed,
        "available": available,
        "update": behind,
        "repo": REPO,
        "note": note,
        "changes": changes,
        "files": files,
        "log": format_update_log(installed, available, note, changes, files, changes_note),
    }


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
    share = setup_share(install)
    write_revision(rev)
    restarting = schedule_restart()
    note = (
        "The page restarts in a couple of seconds. Refresh if it drops. "
        "Wi-Fi settings and pictures stay put. This updates the camera console. "
        "Raspberry Pi OS stays as it was imaged."
    )
    if share:
        note = note + " " + share
    return {
        "ok": True,
        "revision": rev,
        "repo": REPO,
        "restarting": restarting,
        "note": note,
    }


def setup_share(install):
    script = os.path.join(install, "samba-setup.sh")
    if not os.path.isfile(script):
        return ""
    os.chmod(script, 0o755)
    proc = _run([script], 300)
    text = (proc.stdout or proc.stderr or "").strip()
    return text
