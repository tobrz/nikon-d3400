import SwiftUI

/// Live view with the shutter and the main exposure settings. On the open Duo the picture and the controls sit side by side.
struct ShootView: View {
    @Environment(Pi.self) private var pi
    @Environment(\.horizontalSizeClass) private var width
    @State private var live = false
    @State private var frame: UIImage?
    @State private var lastShot: String?
    @State private var seconds = ""

    var body: some View {
        NavigationStack {
            Group {
                if width == .regular {
                    HStack(alignment: .top, spacing: 16) { picture.frame(maxWidth: .infinity); controls.frame(width: 340) }
                } else {
                    ScrollView { VStack(spacing: 14) { picture; controls } }
                }
            }
            .padding()
            .navigationTitle("Shoot")
            .toolbar { ToolbarItem(placement: .topBarLeading) { CameraBadge() } }
            .task { if pi.controls.isEmpty, pi.cameraName != nil { await pi.loadControls() } }
            .task(id: live) {
                // Ask for frames back to back while live view is on.
                while live && !Task.isCancelled {
                    if pi.busy == nil, let img = await pi.previewFrame() { frame = img } else if pi.busy == nil { live = false }
                    try? await Task.sleep(for: .milliseconds(150))
                }
            }
            .onDisappear { live = false }
        }
    }

    private var picture: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 16).fill(.black)
            if let frame { Image(uiImage: frame).resizable().scaledToFit().clipShape(.rect(cornerRadius: 16)) }
            else { Text(pi.cameraName == nil ? "Camera not connected" : "Live view is off").foregroundStyle(.secondary) }
            if let b = pi.busy { VStack { Spacer(); Text(b).font(.footnote.bold()).padding(8).background(.ultraThinMaterial, in: .capsule).padding() } }
        }
        .aspectRatio(3 / 2, contentMode: .fit)
        .overlay(alignment: .topTrailing) {
            Button(live ? "Stop" : "Start") { live.toggle(); if !live { frame = nil } }
                .buttonStyle(.borderedProminent).tint(live ? .red : .yellow).foregroundStyle(.black).padding(10)
                .disabled(pi.cameraName == nil)
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                let wasLive = live
                live = false
                Task {
                    let files = await pi.capture(seconds: Double(seconds))
                    if let jpg = files.first(where: { $0.lowercased().hasSuffix(".jpg") }) ?? files.first {
                        lastShot = URL(fileURLWithPath: jpg).lastPathComponent
                        if let d = await pi.data(pi.shotURL(lastShot!)), let img = UIImage(data: d) { frame = img }
                    }
                    if wasLive && files.isEmpty { live = true }
                }
            } label: {
                Label(pi.busy ?? "Take picture", systemImage: "camera.fill").font(.title3.bold())
                    .frame(maxWidth: .infinity).padding(.vertical, 12)
            }
            .buttonStyle(.borderedProminent).tint(.yellow).foregroundStyle(.black)
            .disabled(pi.cameraName == nil || pi.busy != nil || pi.status?.jobs?.anyRunning == true)
            HStack {
                Text("Exposure")
                TextField("camera's", text: $seconds).keyboardType(.decimalPad).multilineTextAlignment(.trailing).frame(width: 90)
                Text("s").foregroundStyle(.secondary)
            }
            .font(.subheadline)
            if let lastShot { Text("Saved \(lastShot) on the Pi").font(.caption).foregroundStyle(.secondary) }
            Divider()
            if pi.controls.isEmpty {
                Button("Load camera settings") { Task { await pi.loadControls() } }.disabled(pi.cameraName == nil)
            } else {
                Quick(title: "Mode", keys: ["expprogram"])
                Quick(title: "ISO", keys: ["iso"])
                Quick(title: "Shutter", keys: ["shutterspeed", "shutterspeed2"])
                Quick(title: "Aperture", keys: ["f-number", "aperture"])
                Quick(title: "Exposure comp.", keys: ["exposurecompensation"])
                Quick(title: "White balance", keys: ["whitebalance"])
                Quick(title: "Focus mode", keys: ["focusmode", "focusmode2"])
            }
            Divider()
            Text("Focus").font(.subheadline.bold())
            HStack {
                ForEach([("near3", "≪"), ("near1", "‹"), ("auto", "AF"), ("far1", "›"), ("far3", "≫")], id: \.0) { dir, label in
                    Button(label) { Task { await pi.focus(dir) } }.buttonStyle(.bordered).frame(maxWidth: .infinity)
                }
            }
            .disabled(pi.cameraName == nil)
            Text("Near/far steps need the lens on M; AF needs A.").font(.caption2).foregroundStyle(.secondary)
            if let e = pi.lastError { Text(e).font(.footnote).foregroundStyle(.red) }
        }
    }
}

/// A picker for one camera control, by its gphoto2 key.
struct Quick: View {
    @Environment(Pi.self) private var pi
    let title: String
    let keys: [String]

    var body: some View {
        if let c = keys.lazy.compactMap({ k in pi.control(k) }).first {
            HStack {
                Text(title).font(.subheadline)
                Spacer()
                if c.readonly == true || (c.choices ?? []).isEmpty {
                    Text(c.current ?? "—").foregroundStyle(.secondary)
                } else {
                    Menu {
                        ForEach(c.choices ?? [], id: \.label) { ch in
                            Button(ch.label) { Task { await pi.set(c, ch.label) } }
                        }
                    } label: { Text(c.current ?? "—").bold() }
                }
            }
        }
    }
}
