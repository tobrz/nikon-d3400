# Nikon for iPhone

Native SwiftUI app for the camera Pi in this repo. Project `ios/Nikon/Nikon.xcodeproj`, bundle id `com.tobrz.nikon`,
display name Nikon. Same setup as the other tobrz iPhone apps (homelab README, "iPhone apps"): Xcode 27.1, iOS 27.1+,
iPhone only, automatic signing with team `H8B6W6NWP4`; builds set `DEVELOPER_DIR`.

It talks to the Pi's own API (`payload/app/server.py`) over plain HTTP on the local network with the
`X-Nikon-Password` header. Info.plist allows local networking (ATS `NSAllowsLocalNetworking`); iOS asks once for Local
Network access. No Pi changes were needed.

## Screens

- **Connect:** the Pi's address (`nikon-d3400.local` on a shared network, `192.168.50.1` on the Pi's own `Nikon-D3400`
  Wi-Fi) and the page password, kept in the Keychain. At launch it reconnects; with nothing saved it finds a Pi that
  still has the factory password and connects by itself.
- **Shoot:** live view (frames from `/preview.jpg` back to back while on), Take picture (optional exposure seconds; long
  exposures and Bulb are handled by the Pi), the result replaces live view, quick pickers for mode, ISO, shutter,
  aperture, exposure compensation, white balance and focus mode, focus steps / AF, and **Star focus** (`StarFocusView`):
  the Pi measures the brightest star's size in a live-view frame; the app shows it zoomed in, the size history and
  the best so far, and a histogram. On an open Duo the picture and the
  controls sit side by side; the tabs are the right-hand icon column.
- **Shots:** a yellow reminder for pictures that aren't in this phone's Photos library yet, with **Save all to Photos**
  (optionally the NEF too, saved as the RAW half of a RAW+JPEG pair; movies as videos), a badge with that count on
  the Shots tab and a yellow dot on each one. Saves go into a "Nikon D3400" album, and a picture only counts as saved
  after the app finds it in the library (full Photos access); a JPEG+NEF pair Photos refuses is saved as two photos.
  Deleting a picture that isn't confirmed in Photos asks first, with "Save to Photos first". What's been saved is
  remembered per Pi on the phone. Aurora frames get a
  green badge and an "Aurora only" filter. Pictures on the Pi, JPEG + NEF as one (RAW badge). The viewer is full screen: swipe left/right through the set, EXIF under each picture (taken, camera, lens, focal length, aperture, shutter, ISO, comp., mode, metering, WB, flash, size, location), Save to Photos, Share, Delete.
- **Aurora:** the Pi's outlook for its saved place (`GET /api/aurora`, `payload/app/aurora.py`): chance in view,
  Kp, dark or not, and a compass arrow with the bearing and height to aim at; **Use this phone's location** saves the
  phone's position on the Pi (also used to tag pictures). The compass follows the phone's heading ("Turn left 20°",
  a tap when you face it). **Line up the camera** (`AimView.swift`): lay the phone flat on the camera, top edge along
  the lens; the compass gives the tripod pan and the motion sensor the lens tilt (the glow's height, kept 10-45° up),
  each turning green within 8° / 3°. NOAA's northern-hemisphere OVATION map with a 12-hour time
  slider (the newest frame is the forecast) and the 3-day Kp forecast, both read straight from NOAA by the phone.
  Clouds and moon right now; **Next three nights** (verdict, best hour, Kp, cloud, moon; tap for the hours).
  **Watch tonight** starts the Pi's all-night aurora watch (threshold, max cloud, exposure, interval, ISO, follow the
  light, look for it in the pictures): it checks NOAA and the clouds every 5 minutes, shoots when it's dark and likely
  or when the frames show green, and stops at dawn. **Alerts**: the Pi's ntfy topic, on/off, pictures, test, new topic.
- **Programs:** timelapse (with Follow the light), Copy as I shoot, bracket, lightning, card offload, with live progress
  (status polls every 5 s), and a note when the Pi has had to reset the camera's USB link.
- **Camera:** status, every setting the body reports (filterable, editable), the Pi's web page for Wi-Fi, Place, Guide
  and updates, Disconnect.

## Build and run

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
# Duo simulator
xcodebuild -project ios/Nikon/Nikon.xcodeproj -scheme Nikon \
  -destination 'platform=iOS Simulator,id=5703D6A6-D466-445D-8446-7CB0E767EFE4' \
  -derivedDataPath "$HOME/Library/Developer/Xcode/DerivedData/Nikon-sim" build
xcrun simctl install 5703D6A6-D466-445D-8446-7CB0E767EFE4 "$HOME/Library/Developer/Xcode/DerivedData/Nikon-sim/Build/Products/Debug-iphonesimulator/Nikon.app"
xcrun simctl launch --terminate-running-process 5703D6A6-D466-445D-8446-7CB0E767EFE4 com.tobrz.nikon
# iPhone 17 Pro (negskillz17pro)
xcodebuild -project ios/Nikon/Nikon.xcodeproj -scheme Nikon -destination 'platform=iOS,id=00008150-001A3C4E3EC0401C' \
  -derivedDataPath "$HOME/Library/Developer/Xcode/DerivedData/Nikon-device" -allowProvisioningUpdates \
  -allowProvisioningDeviceRegistration DEVELOPMENT_TEAM=H8B6W6NWP4 CODE_SIGN_STYLE=Automatic build
xcrun devicectl device install app --device 00008150-001A3C4E3EC0401C "$HOME/Library/Developer/Xcode/DerivedData/Nikon-device/Build/Products/Debug-iphoneos/Nikon.app"
```

The icon is drawn by `ios/tools/make-icon.swift`.

## Not built yet

Guide (the sentence planner), Place (location/clock), camera-card thumbnails and pull, movie recording, Wi-Fi setup
and updates in the app itself — the Camera tab opens the Pi's web page for those.
