# Nikon D3400 on a Raspberry Pi

Headless camera console for a Nikon D3400 plugged into a Raspberry Pi over USB. The Pi joins a known Wi-Fi network when one is in range. Otherwise it becomes the access point `Nikon-D3400` at `192.168.50.1` and hands the phone or laptop an address. Setup and every later change happen on a web page. No keyboard, mouse, or HDMI after the card is imaged.

Source code: [github.com/tobrz/nikon-d3400](https://github.com/tobrz/nikon-d3400)

The working copy on the build Mac is `/Users/tobrz/Git/nikon-d3400`.

Factory password for the web page, SSH, and the standalone Wi-Fi network: `nikon-d3400`.

SSH user: `camera`.

## What you need

- A Raspberry Pi with Wi-Fi. A Pi Zero 2 W, 3, 4, or 5 all work. A Zero 2 W has one USB port, so the first boot uses a USB ethernet adapter and the camera is plugged in later.
- A microSD card. The imaging script was written for the 64 GB card used here. It refuses the internal Mac disks `disk0` and `disk3`.
- A Mac to write the card. The script is `scripts/write-image.sh`.
- A Nikon D3400 and a USB-A to micro-USB cable. The camera battery can charge first. The software does not wait for the body.
- Ethernet on the very first boot, so the Pi can install packages. After that, Wi-Fi is enough.

## Image the card

1. Plug the microSD card into the Mac.
2. Find the external disk. In Terminal:

   ```bash
   diskutil list external
   ```

   Use the whole-disk name, such as `disk5`. The name changes when other disks are attached. Confirm the line says external before you continue.

3. From this repo, write the card. This replaces everything on that disk, including an older DigiPi install:

   ```bash
   scripts/write-image.sh disk5
   ```

   The script downloads Raspberry Pi OS Lite, 64-bit, Trixie, image `2026-10-06-raspios-trixie-arm64-lite.img.xz`, checks its SHA256, writes it, then copies this project onto the boot partition. The download is cached in `~/Library/Caches/nikon-d3400` and is not part of the git repo.

4. The script prints `Boot volume ready` and ejects the card. The first-boot files are `user-data`, `meta-data`, `ssh`, `nikon-install.sh`, `nikon-revision`, and the `nikon-d3400/` folder. Ejecting matters. Pulling the card while it is still mounted can drop a boot file, and the web page then never starts.

5. Put the card in the Pi.

A later software change does not need this step. Use the web update below. Image the card again when you want a fresh Raspberry Pi OS, or when the web page will not come up at all.

## How long the first boot takes

Plan on about 10 minutes from the moment you apply power. Give a slow network or a slow card 20 minutes before you pull it out to read the log.

On a Pi 4 with ethernet, timed from one real first boot:

- About 2 minutes: the Pi answers on the network as `nikon-d3400`. SSH is up. The web page may still be installing.
- The Pi reboots once by itself, a few minutes in. That reboot is part of setup. Leave it plugged in.
- About 10 minutes: open the page. Packages, including the picture share, are in place by then.
- On a Pi with 2 GB of RAM or more, the optional speech model can still be downloading after the page is up. The written guide works before that finishes. A Pi Zero 2 W skips the model.

Use the ethernet address from your router, or `http://nikon-d3400.local` once the name appears. The address `http://192.168.50.1` is only for the Pi's own Wi-Fi, when no house network is saved.

## First boot

Leave the camera unplugged. Leave the keyboard, mouse, and HDMI unplugged. Plug in ethernet.

On a Pi Zero 2 W, put a USB ethernet adapter in the only USB port for this boot. On a Pi 3, 4, or 5, use the ethernet jack.

Power the Pi. There is nothing to click. Cloud-init creates the user `camera`, turns on SSH, and runs `nikon-install.sh`. That script sets the hostname to `nikon-d3400`, installs the console to `/opt/nikon-d3400`, and reboots once about 25 seconds later. `nikon-bootstrap` then installs `gphoto2`, `avahi-daemon`, and `git` from the ethernet connection. On a Pi with at least 2 GB of RAM it also tries to install Ollama and the small model `qwen2.5:0.5b`. A Pi Zero 2 W skips that model. The written guide works either way.

When the Wi-Fi network `Nikon-D3400` appears:

1. Join it. Password `nikon-d3400`. The Pi runs DHCP, so the phone or laptop gets an address on `192.168.50.0/24`.
2. Open `http://192.168.50.1`.
3. Sign in with `nikon-d3400`.

If that network never appears, pull the card, mount the boot partition on the Mac, and read `nikon-install.log`.

## Join the house Wi-Fi

On the Wi-Fi tab, enter the house network name and password and choose **Remember this network**. The Pi leaves the access point and joins that network. Saving a network while you are on `Nikon-D3400` drops this page until you find the Pi again.

After it joins, open `http://nikon-d3400.local`, or the address your router gives the host `nikon-d3400`.

Then move the USB cable to the camera.

- Pi Zero 2 W: the USB port is in host mode. Use a USB-OTG host adapter and a USB-A to micro-USB cable. Remove the ethernet adapter first. The Pi is on Wi-Fi now.
- Pi 3, 4, or 5: use a normal USB-A port. Ethernet can stay or go.

Change the page password on the Wi-Fi tab. It must be at least 8 characters. Change the SSH password after you log in, with `passwd`, and then set the same password for the picture share with `smbpasswd`. The standalone access-point password stays `nikon-d3400`.

## Pictures on the Mac

The Pi shares the folder of pictures already stored on it. In Finder, choose Go, Connect to Server, and enter:

```text
smb://nikon-d3400.local/shots
```

Sign in as `camera`. The factory password is `nikon-d3400`. The share is read-only. Drag the files from that window into the Photos app. New frames show up here after the page has copied them off the camera, or after a timelapse or lightning run has saved them on the Pi.

The same login works with `smb://` and the ethernet address your router gave the Pi. That address can change. The name `nikon-d3400.local` is the one to keep.

A git update installs this share. The first image does too, as long as ethernet has a route during that first boot.

## Update without imaging the card again

The Pi keeps its own checkout and can pull this public repo.

1. Give the Pi a route to the internet. Plug in ethernet, or join a house Wi-Fi network from the Wi-Fi tab. The standalone `Nikon-D3400` access point has no upstream, so the button stops and tells you that.
2. Open the Wi-Fi tab.
3. Choose **Update from git**.

The button installs `git` if the first boot did not, shallow-clones or fast-forwards `https://github.com/tobrz/nikon-d3400.git`, copies `payload/` over `/opt/nikon-d3400`, reloads the service units, and restarts the web page a couple of seconds later. Refresh if the page drops.

That replaces the camera console. Pictures already stored on the Pi, the saved Wi-Fi list, and the page password stay in `/var/lib/nikon-d3400`. Raspberry Pi OS stays as it was imaged. The status line shows the short git revision after a successful update. Before the first update it shows the revision written onto the card, or “factory image” if that file is missing.

If the page itself will not load, and SSH still works:

```bash
ssh camera@nikon-d3400.local
sudo apt-get update
sudo apt-get install -y git
sudo rm -rf /var/lib/nikon-d3400/src
sudo git clone --depth 1 --branch main https://github.com/tobrz/nikon-d3400.git /var/lib/nikon-d3400/src
sudo cp -a /var/lib/nikon-d3400/src/payload/. /opt/nikon-d3400/
sudo systemctl daemon-reload
sudo systemctl restart nikon-d3400
```

## Features

The page has eight tabs. Controls are read from the body over USB when it is plugged in. The menu is not a fixed list baked into the page.

### Guide

Type a sentence such as “I want a night shot of the Milky Way. Walk me through aim and focus, then get ready to open the shutter.” The Pi returns a written plan for this camera. **Apply the exposure** sends the settings the body actually offers. **Open the shutter** applies them and takes a frame.

The Milky Way plan uses ISO 1600, f/3.5, daylight white balance, and a shutter of `300 / (1.5 × focal length)` so stars stay points on the DX sensor. At 18 mm that is 11 seconds. Aim and focus stay manual: live view, magnify, focus ring. USB cannot focus the Milky Way for you.

On a Pi with at least 2 GB of RAM and a finished first boot, Ollama `qwen2.5:0.5b` may rephrase that written plan. The steps and the exposure stay the written ones. The page says whether you are hearing the built-in guide or the on-device model.

The same planner also covers lightning, timelapse, a general night frame, and a plain “what can this camera do” question.

### Live view

**Start live view** asks the body for a preview and keeps requesting frames. Near and Far buttons drive `manualfocusdrive` in steps of 1, 2, and 3. **Autofocus** sends `autofocusdrive`. The lens switch wants M for the near/far steps and A for autofocus.

Live view and remote focus are attempted. Some Nikon bodies refuse them over USB. When the D3400 refuses, the text under the picture is the gphoto2 error. Treat that message as the result until a connected body proves the control works.

### Menu

Every setting `gphoto2 --list-all-config` returns: choices, switches, number ranges, text, and read-only rows. A search box filters the list. Changing a writable row sends that value immediately. Read-only rows are shown and left alone. **Release shutter** takes one picture.

Capture tries `--capture-image-and-download` first, then `--trigger-capture` if the body hangs on the download form. The page reports which one ran.

### Timelapse

Tripod interval shooting. The D3400 has no interval timer of its own. The shortest gap is 3 seconds. A count of 0 runs until **Stop**. Each frame is downloaded to the Pi. One run at a time: timelapse and lightning share the camera.

### Lightning

A shutter spray, then the new frames are copied off the card. Set the frame count and the gap (minimum 0.2 seconds). Put the camera in manual exposure and manual focus first. This is not a light sensor. A 3.3 V digital module on GPIO 17 can be added later. The page works without it.

The guide’s starting exposure for lightning is ISO 200, f/8, and 5 seconds.

### Night

One test frame. The guide applies ISO 800, f/3.5, and a long shutter when the body offers those names, then releases the shutter.

### Shots

**Show pictures on the camera** lists the card in the D3400. **Copy, then download here** pulls that file onto the Pi and saves it to the phone or laptop. Frames already on the Pi can be downloaded one by one. **Download all on the Pi** is a zip of those files. The zip is stored, not recompressed, so NEFs stay intact.

### Wi-Fi

Add a network, see whether the Pi is the access point or a client, change the page password, and run **Update from git**.

## What lives where

| Path | Role |
| --- | --- |
| `/opt/nikon-d3400` | The running console. Updates replace this tree. |
| `/var/lib/nikon-d3400` | Password, Wi-Fi list, pictures, revision, and the git checkout. |
| `/var/lib/nikon-d3400/src` | Shallow clone of this repo. |
| `http://192.168.50.1` | Page while the Pi is its own access point. |
| `http://nikon-d3400.local` | Page after it has joined a network and Avahi is up. |

The web server is Python’s standard library on port 80. `gphoto2` is the camera tool. NetworkManager runs the client and the access point. The access point profile is `nikon-ap`, WPA password `nikon-d3400`, address `192.168.50.1/24`.

## Develop

```bash
python3 -m unittest discover tests
```

Do not commit the OS image, the cache under `~/Library/Caches/nikon-d3400`, or pictures from a camera.
