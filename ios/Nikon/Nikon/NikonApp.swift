import SwiftUI

@main
struct NikonApp: App {
    @State private var pi = Pi()
    var body: some Scene {
        WindowGroup {
            RootView().environment(pi).tint(.yellow)
        }
    }
}

struct RootView: View {
    @Environment(Pi.self) private var pi
    @State private var resuming = true

    var body: some View {
        Group {
            if pi.connected { MainTabs() }
            else if resuming { ProgressView("Finding the camera Pi…") }
            else { ConnectView() }
        }
        .task {
            await pi.resume()
            resuming = false
            // Keep status (camera present, jobs) fresh while the app is open; the picture list (for the Shots badge)
            // every minute.
            var ticks = 0
            if pi.connected { await pi.loadShots() }
            while true {
                try? await Task.sleep(for: .seconds(5))
                ticks += 1
                if pi.connected && pi.busy == nil {
                    await pi.refreshStatus()
                    if ticks % 12 == 0 { await pi.loadShots() }
                }
            }
        }
    }
}

struct MainTabs: View {
    @Environment(Pi.self) private var pi
    var body: some View {
        // On the open Duo these become the column of icons on the right, as in Money.
        TabView {
            Tab("Shoot", systemImage: "camera.aperture") { ShootView() }
            // The badge is the reminder that pictures are only on the Pi until they're saved to Photos.
            Tab("Shots", systemImage: "photo.on.rectangle") { ShotsView() }.badge(pi.notInPhotos.count)
            Tab("Aurora", systemImage: "sparkles") { AuroraView() }
            Tab("Programs", systemImage: "timer") { ProgramsView() }
            Tab("Camera", systemImage: "slider.horizontal.3") { CameraView() }
        }
    }
}

struct ConnectView: View {
    @Environment(Pi.self) private var pi
    @State private var host = ""
    @State private var password = ""
    @State private var working = false

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: "camera.aperture").font(.system(size: 64)).foregroundStyle(.yellow)
            Text("Nikon D3400").font(.title2.bold())
            Text("Join the Pi's Wi-Fi “Nikon-D3400” (address 192.168.50.1), or the same network as the Pi (nikon-d3400.local).")
                .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            HStack {
                ForEach(["nikon-d3400.local", "192.168.50.1"], id: \.self) { h in
                    Button(h) { host = h }.buttonStyle(.bordered).controlSize(.small)
                }
            }
            TextField("Pi address", text: $host).textInputAutocapitalization(.never).autocorrectionDisabled()
                .padding(12).background(.quaternary, in: .rect(cornerRadius: 12))
            SecureField("Page password (factory: nikon-d3400)", text: $password)
                .padding(12).background(.quaternary, in: .rect(cornerRadius: 12))
            if let e = pi.lastError { Text(e).font(.footnote).foregroundStyle(.red) }
            Button {
                working = true
                Task { _ = await pi.connect(host: host, password: password); working = false }
            } label: { Text(working ? "Connecting…" : "Connect").frame(maxWidth: .infinity).padding(.vertical, 6) }
                .buttonStyle(.borderedProminent).disabled(host.isEmpty || password.isEmpty || working)
            Spacer()
        }
        .padding(24).frame(maxWidth: 480)
        .onAppear { host = pi.host }
    }
}

/// Small status line used on several screens.
struct CameraBadge: View {
    @Environment(Pi.self) private var pi
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(pi.cameraName == nil ? .orange : .green).frame(width: 8, height: 8)
            Text(pi.cameraName ?? "Camera not connected (turn it on, USB to the Pi)").font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
    }
}
