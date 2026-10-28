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

The page comes up before the camera tools are installed. Plan on a couple of minutes from power-on until `Nikon-D3400` appears. Package setup starts after the Pi has a route to the internet, and on a Pi 4 that is several more minutes. The Pi reboots once after that setup finishes, then the page comes back. Give a slow link 20 minutes before you pull the card to read the log.

## First boot

Leave the camera unplugged. Leave the keyboard, mouse, and HDMI unplugged. Ethernet is optional. The page is enough.

Power the Pi. Cloud-init creates the user `camera`, turns on SSH, and starts the page and the access point. It does not wait for packages.

When the Wi-Fi network `Nikon-D3400` appears:

1. Join it. Password `nikon-d3400`. The Pi runs DHCP, so the phone or laptop gets an address on `192.168.50.0/24`.
2. Open `http://192.168.50.1`.
3. Sign in with `nikon-d3400`. The status line says to join a Wi-Fi network with internet.
4. On the Wi-Fi tab, save Starlink or the house network. The Pi leaves its access point and joins that network. Join the same network on the phone.
5. Open `http://nikon-d3400.local`. Setup downloads `gphoto2`, `git`, the picture share, and ExifTool. On a Pi with at least 2 GB of RAM it also tries the small on-device model. A Pi Zero 2 W skips that model. The written guide works either way.
6. The Pi reboots once when that finishes. Open the page again. The camera can be plugged in after that.

If `Nikon-D3400` never appears, pull the card, mount the boot partition on the Mac, and read `nikon-install.log`. Ethernet still works. If a cable is plugged in and the router gives the Pi an address, setup starts on its own and the page is also at `http://nikon-d3400.local`.

## Join the house Wi-Fi

On the Wi-Fi tab, enter the house network name and password and choose **Remember this network**. The Pi leaves the access point and joins that network. Saving a network while you are on `Nikon-D3400` drops this page until you find the Pi again.

After it joins, open `http://nikon-d3400.local`, or the address your router gives the host `nikon-d3400`.

## In the field on Starlink

Starlink is a normal Wi-Fi network with internet. Save it once and the Pi joins it whenever it is in range. Your phone or laptop stays on Starlink too. The page is `http://nikon-d3400.local`, and **Update from git** works from there.

The first time the Pi does not know Starlink yet, so it brings up its own access point, which has no internet:

1. Join Wi-Fi `Nikon-D3400` from the phone. Password `nikon-d3400`.
2. Open `http://192.168.50.1` and sign in with `nikon-d3400`.
3. On the Wi-Fi tab, enter the Starlink network name and password and choose **Remember this network**.
4. The Pi leaves its access point and joins Starlink. Join Starlink on the phone as well.
5. Open `http://nikon-d3400.local`. If that name is not there yet, use the address the Starlink app shows for `nikon-d3400`. The first join is also when the Pi installs its packages, so give it the rest of the 10 minutes.
6. On the Wi-Fi tab, choose **Update from git**.

The next time you are at the dish, the Pi joins Starlink by itself. Skip the access-point steps.

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

A git update installs this share. The first image does too, once the Pi has a route to the internet, either ethernet or Starlink.

## Update without imaging the card again

The Pi keeps its own checkout and can pull this public repo.

1. Give the Pi a route to the internet. Ethernet, house Wi-Fi, and Starlink all count. The standalone `Nikon-D3400` access point has no upstream, so the button stops and tells you that.
2. Open the Wi-Fi tab, or use **Check for updates** at the top of the page.
3. **Check for updates** asks GitHub if `main` is newer, then prints each new commit: the short hash, the subject, the rest of the message, and the files that changed. It does not install anything. **Update from git** installs that commit and restarts the page. The list appears under the header and again on the Wi-Fi tab.

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

The page has ten tabs. Controls are read from the body over USB when it is plugged in. The menu is not a fixed list baked into the page.

### Guide

Type a sentence such as “I want a night shot of the Milky Way. Walk me through aim and focus, then get ready to open the shutter.” The Pi returns a written plan for this camera. **Apply the exposure** sends the settings the body actually offers. **Open the shutter** applies them and takes a frame.

The Milky Way plan uses ISO 1600, f/3.5, daylight white balance, and a shutter of `300 / (1.5 × focal length)` so stars stay points on the DX sensor. At 18 mm that is 11 seconds. Aim and focus stay manual: live view, magnify, focus ring. USB cannot focus the Milky Way for you.

On a Pi with at least 2 GB of RAM and a finished first boot, Ollama `qwen2.5:0.5b` may rephrase that written plan. The steps and the exposure stay the written ones. The page says whether you are hearing the built-in guide or the on-device model.

The same planner also covers lightning, timelapse, a general night frame, and a plain “what can this camera do” question.

### Live view

Guide, Shoot, Timelapse, Bracket, Lightning, Night, and Live view each show the scene beside that page's own controls. Menu does not. Press **Start** on the picture. It keeps running while you move between those shooting pages, and it stops when you open Menu or another page without the picture. **Record video** and the focus steps are on the Live view tab. The clip stays on the camera card.

### Live view details

**Start live view** asks the body for a preview and keeps requesting frames. Near and Far buttons drive `manualfocusdrive` in steps of 1, 2, and 3. **Autofocus** sends `autofocusdrive`. The lens switch wants M for the near/far steps and A for autofocus.

Live view and remote focus are attempted. Some Nikon bodies refuse them over USB. When the D3400 refuses, the text under the picture is the gphoto2 error. Treat that message as the result until a connected body proves the control works.

### Raw

The Raw tab is the body's own report: the gphoto2 summary, the capture abilities, and every control with its path, whether it is writable, and its current value. Lens identity is in that summary as Lens ID, Lens Type, and the minimum and maximum focal length. The D3400 sends those as numbers and millimeters, not the name printed on the lens barrel.

**Check firmware against Nikon** reads the body's Device Version and compares it with the C firmware named on [Nikon's D3400 download page](https://downloadcenter.nikonimglib.com/en/download/fw/284.html). The Pi needs ethernet or a joined network with internet. The button does not download or install the file. When Nikon has a newer version, the update is still their file, copied to the root of a card that was formatted in the camera.

### Menu

Every setting `gphoto2 --list-all-config` returns: choices, switches, number ranges, text, and read-only rows. A search box filters the list. Changing a writable row sends that value immediately. Read-only rows are shown and left alone. This page has no live view. **Release shutter** takes one picture with the shutter already on the camera and waits until it closes.

### Shoot

One picture, with the scene beside the button. **Automatic** uses the shutter speed already on the body. A chosen time is set over USB, then the Pi waits until that exposure finishes. The D3400 times speeds up to 30 seconds itself. Longer than that uses Bulb: one press opens the shutter, the Pi waits, and a second press closes it. Those two presses are one camera session. A lone trigger is not used, because on this body that opens the shutter and returns before it closes.

While a picture is in progress, the page does not start a second camera command. That includes the status probe that used to run every few seconds.

### Timelapse

Tripod interval shooting. The D3400 has no interval timer of its own. **Seconds to leave the shutter open** can be blank, which means the speed already on the camera. The gap is the time after the shutter closes, before the next frame, and it can be as short as 1 second. A count of 0 runs until **Stop**. Stop finishes the exposure that is already open, then ends the run. Each frame is downloaded to the Pi. Two or more JPEG frames are compiled with ffmpeg into an mp4 at the playback rate you set, usually 24 frames a second. The movie is named `timelapse-<time>.mp4` in the shots folder. One run at a time: timelapse, bracket, and lightning share the camera.

### Bracket

Three or five frames, from dark to bright, one or one-third or two-thirds of a stop apart. In M or S the Pi steps the shutter speed. A step that would be longer than 30 seconds is a Bulb exposure with an open and a close. In A or P the Pi steps exposure compensation. The original shutter or compensation is put back when the run ends, including when it stops early. The mode dial is not moved.

### Lightning

A shutter spray, then the new frames are copied off the card. Set the frame count and the gap (minimum 0.2 seconds). Put the camera in manual exposure and manual focus first. This is not a light sensor. A 3.3 V digital module on GPIO 17 can be added later. The page works without it.

The guide’s starting exposure for lightning is ISO 200, f/8, and 5 seconds.

### Night

One test frame. The guide applies ISO 800, f/3.5, and a long shutter when the body offers those names, then releases the shutter.

### Place

The D3400 has no GPS receiver. SnapBridge is what copies a phone's location into a picture. On the Place tab, leave **SnapBridge is connected** unchecked when the phone app is not linked. The Pi then sets the camera clock from its own clock, which follows the network time while ethernet or Starlink is up, and writes a saved latitude and longitude into JPG and NEF files after they are copied onto the Pi.

**Use this phone's location** asks the browser. A phone often blocks that on a plain `http://` page. Type the numbers from Maps if it does. **Set the camera clock** writes the Pi's time into the body. **Write location into pictures on the Pi** stamps files that are already stored here. With the SnapBridge box checked, the Pi leaves the clock and the location alone.

### Shots

Pictures already on the Pi show on this tab. A JPEG is the picture itself. A NEF shows the small preview stored inside the file when the Pi can read one. **Show pictures on the camera** loads the newest 24 thumbnails from the card. The missing ones are read together, in one camera session, then kept in `/var/lib/nikon-d3400/thumbs`. The next visit does not ask the camera for those again. A thumbnail is not a full copy. **Copy, then download** pulls that file onto the Pi and saves it to the phone or laptop. **Offload camera card to the Pi** copies every picture onto the Pi, then deletes only the copies that arrived. A picture that fails to copy stays on the camera. That is how you free the camera card in the field. The copies stay on the Pi until you drag them into Photos from `smb://nikon-d3400.local/shots`. **Download all on the Pi** is a zip of those files. The zip is stored, not recompressed, so NEFs stay intact.

### Wi-Fi

**Scan for networks** lists what the Pi can hear and fills the network name. Enter the password, then **Remember this network**. A scan while the Pi is the Nikon-D3400 access point can drop the phone for a moment. Rejoin that access point if the page disappears. The tab also shows whether the Pi is the access point or a client, changes the page password, and runs **Check for updates** and **Update from git**.

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
