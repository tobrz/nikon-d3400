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
  aperture, exposure compensation, white balance and focus mode, and focus steps / AF. On an open Duo the picture and the
  controls sit side by side; the tabs are the right-hand icon column.
- **Shots:** pictures on the Pi, JPEG + NEF as one (RAW badge). The viewer is full screen: swipe left/right through the set, EXIF under each picture (taken, camera, lens, focal length, aperture, shutter, ISO, comp., mode, metering, WB, flash, size, location), Save to Photos, Share, Delete.
- **Programs:** timelapse, bracket, lightning, card offload, with live progress (status polls every 5 s).
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
