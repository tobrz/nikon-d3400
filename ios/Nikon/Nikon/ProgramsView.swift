import SwiftUI

/// Runs on the Pi: timelapse, bracket, lightning, and the card offload. One at a time; status refreshes every few seconds.
struct ProgramsView: View {
    @Environment(Pi.self) private var pi
    @State private var interval = 10.0
    @State private var count = 0
    @State private var seconds = ""
    @State private var fps = 24
    @State private var followLight = false
    @State private var brCount = 3
    @State private var brStep = 1.0
    @State private var frames = 30
    @State private var gap = 0.4

    var body: some View {
        let jobs = pi.status?.jobs
        let busy = jobs?.anyRunning == true || pi.cameraName == nil
        NavigationStack {
            Form {
                Section { CameraBadge() }
                Section {
                    Stepper("Gap after each frame: \(Int(interval)) s", value: $interval, in: 1...3600)
                    Stepper(count == 0 ? "Frames: until Stop" : "Frames: \(count)", value: $count, in: 0...9999, step: 10)
                    HStack { Text("Shutter open"); Spacer(); TextField("camera's", text: $seconds).keyboardType(.decimalPad).multilineTextAlignment(.trailing).frame(width: 90); Text("s") }
                    Toggle("Follow the light (day to night)", isOn: $followLight)
                    Stepper("Movie: \(fps) frames/s", value: $fps, in: 1...60)
                    run("timelapse", jobs?.timelapse, busy: busy) {
                        var b: [String: Any] = ["interval": interval, "count": count, "fps": fps, "auto": followLight]
                        if let s = Double(seconds) { b["seconds"] = s }
                        return b
                    }
                    if let r = jobs?.timelapse { RunLine(run: r, done: "\(r.taken ?? 0) taken" + ((r.movie ?? "").isEmpty ? "" : " · movie \(r.movie!)")) }
                } header: { Text("Timelapse") } footer: { Text("Tripod. Frames download to the Pi and two or more JPEGs become an mp4 in Shots, with flicker smoothed out. Follow the light picks shutter and ISO from each frame's brightness (mode dial on M), for sunsets into night.") }

                Section {
                    run("tether", jobs?.tether, busy: busy) { [:] }
                    if let r = jobs?.tether { RunLine(run: r, done: "\(r.saved ?? 0) copied" + ((r.last ?? "").isEmpty ? "" : " · last \(r.last!)")) }
                } header: { Text("Copy as I shoot") } footer: { Text("Shoot with the camera's own button; each picture copies to the Pi a moment later and stays on the card.") }

                Section {
                    Picker("Frames", selection: $brCount) { Text("3").tag(3); Text("5").tag(5) }.pickerStyle(.segmented)
                    Picker("Stops apart", selection: $brStep) { Text("1/3").tag(0.333); Text("2/3").tag(0.667); Text("1").tag(1.0) }.pickerStyle(.segmented)
                    run("bracket", jobs?.bracket, busy: busy) { ["count": brCount, "step": brStep] }
                    if let r = jobs?.bracket { RunLine(run: r, done: "\(r.taken ?? 0) of \(r.count ?? brCount)") }
                } header: { Text("Bracket") } footer: { Text("M or S steps the shutter; A or P steps exposure compensation. Settings are put back afterwards.") }

                Section {
                    Stepper("Frames: \(frames)", value: $frames, in: 5...500, step: 5)
                    Stepper("Gap: \(gap, specifier: "%.1f") s", value: $gap, in: 0.2...10, step: 0.1)
                    run("lightning", jobs?.lightning, busy: busy) { ["frames": frames, "gap": gap] }
                    if let r = jobs?.lightning { RunLine(run: r, done: "\(r.triggers ?? 0) fired · \(r.downloaded ?? 0) copied") }
                } header: { Text("Lightning") } footer: { Text("Manual exposure and manual focus first. Start around ISO 200, f/8, 5 s.") }

                Section {
                    Button("Offload camera card to the Pi") { Task { await pi.start("offload", [:]) } }.disabled(busy)
                    if let r = jobs?.offload { RunLine(run: r, done: "\(r.copied ?? 0) of \(r.total ?? 0) copied · \(r.deleted ?? 0) removed from card") }
                } header: { Text("Card") } footer: { Text("Copies every picture to the Pi, then deletes only the copies that arrived.") }

                if let n = jobs?.usb_resets, n > 0 {
                    Section { Text("The Pi reset the camera's USB link \(n) time\(n == 1 ? "" : "s") to keep going.\(jobs?.last_usb_reset.map { " Last: \($0)" } ?? "")").font(.caption).foregroundStyle(.secondary) }
                }
                if let e = pi.lastError { Section { Text(e).foregroundStyle(.red) } }
            }
            .navigationTitle("Programs")
            .refreshable { await pi.refreshStatus() }
        }
    }

    @ViewBuilder private func run(_ job: String, _ r: Jobs.Run?, busy: Bool, body: @escaping () -> [String: Any]) -> some View {
        if r?.running == true {
            Button("Stop", role: .destructive) { Task { await pi.stop(job) } }
        } else {
            Button("Start") { Task { await pi.start(job, body()) } }.bold().disabled(busy)
        }
    }
}

struct RunLine: View {
    let run: Jobs.Run
    let done: String
    var body: some View {
        if run.running == true || !(run.error ?? "").isEmpty || (run.taken ?? run.copied ?? run.triggers ?? run.saved ?? 0) > 0 {
            VStack(alignment: .leading, spacing: 2) {
                HStack { if run.running == true { ProgressView().controlSize(.small) }; Text(done).font(.subheadline) }
                if let n = run.note, !n.isEmpty { Text(n).font(.caption).foregroundStyle(.secondary) }
                if let e = run.error, !e.isEmpty { Text(e).font(.caption).foregroundStyle(.red) }
            }
        }
    }
}
