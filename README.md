# Nikon D3400 on a Raspberry Pi

Headless camera console for a Nikon D3400 plugged into a Raspberry Pi over USB. The Pi joins a known Wi-Fi network when one is in range. Otherwise it becomes the access point `Nikon-D3400` at `192.168.50.1` and gives the phone or laptop an address. The whole setup is a web page. No keyboard, mouse, or HDMI.

The D3400 does not offer a supported remote-control app of its own. This box talks to it with gphoto2 and shows every control the body actually returns over USB. Shutter, timelapse, a lightning spray, and a night exposure are built in. A local guide walks through a Milky Way, including aim and manual focus, which USB cannot do for you. On a Pi with at least 2 GB of RAM and ethernet on first boot, a small on-device model (`qwen2.5:0.5b` through Ollama) can rephrase that guide. The steps stay the written ones either way.

Plug the camera in after its battery is charged. The Controls page is the inventory of what that body allows. Read-only rows are facts. Writable rows can be changed from the phone.

## First boot

1. Flash a card with `scripts/write-image.sh diskN` on a Mac. That writes Raspberry Pi OS Lite (64-bit, Trixie, 2026-10-06) and the first-boot files.
2. Plug in ethernet. A Pi Zero 2 W needs a USB ethernet adapter in the USB port for this boot, and the camera stays unplugged. A Pi 3, 4, or 5 can use the ethernet jack.
3. Power the Pi. There is nothing to click. The first boot installs gphoto2, enables SSH, and reboots.
4. Join Wi-Fi `Nikon-D3400`. Password `nikon-d3400`.
5. Open `http://192.168.50.1`. Same password.
6. On the Wi-Fi page, save the house network. The Pi will leave the access point and join it. After that, use `http://nikon-d3400.local` or the address your router gives it.
7. Move the USB cable to the camera. On a Pi Zero 2 W the USB port is in host mode. Use a USB-OTG host adapter and a USB-A to micro-USB cable. On a Pi 3, 4, or 5 use a normal USB-A port.

SSH user is `camera`, password `nikon-d3400`. Change the page password from the Wi-Fi panel. Change the SSH password with `passwd` after you log in.

If the page never appears, pull the card and read `nikon-install.log` on the boot partition.

## What the page does

- Guide: “I want a night shot of the Milky Way” produces the focus and aim steps, then can apply ISO, aperture, and shutter and open the shutter.
- Controls: every gphoto2 setting the connected body reports.
- Timelapse: interval shooting on a tripod. The D3400 has no interval timer of its own.
- Lightning: repeated remote releases, then the new frames are copied off the card.
- Night: one test frame at ISO 800, f/3.5, and a long shutter.
- Shots: JPEGs and NEFs that made it to the Pi.

A light sensor is not required. A 3.3 V digital module on GPIO 17 can be added later; the page sprays the shutter without it.

## Develop

```bash
python3 -m unittest discover tests
```

The image download is cached in `~/Library/Caches/nikon-d3400` and is not part of this repo.
