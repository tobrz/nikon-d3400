import Charts
import CoreLocation
import SwiftUI

/// Northern lights: the Pi's outlook for its saved place (chance in view, where to aim, dark yet), NOAA's map with a time
/// slider, the 3-day Kp forecast, and the all-night watch that shoots when the aurora is likely.
struct AuroraView: View {
    @Environment(Pi.self) private var pi
    @Environment(\.horizontalSizeClass) private var width
    @State private var outlook: AuroraOutlook?
    @State private var error: String?
    @State private var locator = Locator()
    @State private var heading = Heading()
    @State private var aiming = false

    var body: some View {
        NavigationStack {
            ScrollView {
                if width == .regular {
                    HStack(alignment: .top, spacing: 16) {
                        VStack(spacing: 16) { now; WatchCard(); AlertsCard() }.frame(maxWidth: .infinity)
                        VStack(spacing: 16) { PlanCard(); AuroraMap(); KpForecast() }.frame(maxWidth: .infinity)
                    }
                    .padding()
                } else {
                    VStack(spacing: 16) { now; PlanCard(); AuroraMap(); WatchCard(); AlertsCard(); KpForecast() }.padding()
                }
            }
            .navigationTitle("Aurora")
            .refreshable { await load() }
            .task { await load() }
            .onAppear { heading.start() }
            .sheet(isPresented: $aiming) {
                if let o = outlook, let b = o.bearing {
                    AimView(bearing: Double(b), direction: o.direction ?? "", elevation: o.elevation)
                        .onAppear { heading.stop() }.onDisappear { heading.start() }
                }
            }
            .onDisappear { heading.stop() }
        }
    }

    private func load() async {
        do { outlook = try await pi.aurora(); error = nil } catch { self.error = error.localizedDescription }
    }

    private var now: some View {
        Panel(title: "Right now") {
            if let o = outlook {
                HStack(spacing: 18) {
                    Gauge(value: Double(o.visible), in: 0...100) { Text("in view") } currentValueLabel: { Text("\(o.visible)%") }
                        .gaugeStyle(.accessoryCircular).tint(Gradient(colors: [.gray, .green, .mint, .purple])).scaleEffect(1.5)
                        .frame(width: 90, height: 90)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(o.summary ?? "").font(.subheadline)
                        HStack(spacing: 12) {
                            if let kp = o.kp { Label("Kp \(kp, specifier: "%.1f")", systemImage: "waveform.path.ecg") }
                            Label(o.dark == true ? "Dark" : "Not dark yet", systemImage: o.dark == true ? "moon.stars.fill" : "sun.horizon.fill")
                        }
                        .font(.caption).foregroundStyle(.secondary)
                        HStack(spacing: 12) {
                            if let c = o.clouds?.total { Label("\(c)% cloud", systemImage: c > 70 ? "cloud.fill" : c > 30 ? "cloud.sun" : "sparkles") }
                            if let m = o.moon { Label("Moon \(Int(m.illumination * 100))%\(m.altitude > 0 ? ", up" : ", down")", systemImage: "moon") }
                        }
                        .font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let b = o.bearing {
                    let turn = heading.degrees.map { Heading.turn(from: $0, to: Double(b)) }
                    HStack(spacing: 16) {
                        Compass(bearing: Double(b), heading: heading.degrees).frame(width: 110, height: 110)
                            .sensoryFeedback(.success, trigger: turn.map { abs($0) <= Heading.onTarget } ?? false) { _, on in on }
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Aim \(o.direction ?? "") · \(b)°").font(.headline)
                            if let turn {
                                // Live from the phone's compass: hold it flat, top edge pointing away from you.
                                Group {
                                    if abs(turn) <= Heading.onTarget { Label("You're facing it", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
                                    else { Label("Turn \(turn < 0 ? "left" : "right") \(Int(abs(turn)))°", systemImage: turn < 0 ? "arrow.turn.up.left" : "arrow.turn.up.right") }
                                }
                                .font(.subheadline.bold())
                            }
                            if let e = o.elevation { Text(e < 15 ? "Low on the horizon (\(Int(e))° up)" : "About \(Int(e))° up").font(.subheadline) }
                            if let d = o.distance_km { Text("Strongest glow about \(d) km away").font(.caption).foregroundStyle(.secondary) }
                            Button { aiming = true } label: { Label("Line up the camera", systemImage: "scope") }
                                .buttonStyle(.borderedProminent).font(.footnote)
                        }
                    }
                }
                Text("NOAA forecast for \(time(o.forecast_time)) · \(String(format: "%.3f, %.3f", o.lat ?? 0, o.lon ?? 0))")
                    .font(.caption2).foregroundStyle(.secondary)
            } else if let error {
                Text(error).font(.footnote).foregroundStyle(error.contains("location") ? Color.secondary : Color.red)
            } else { ProgressView() }
            Button {
                Task {
                    if let loc = await locator.current() {
                        await pi.saveLocation(lat: loc.coordinate.latitude, lon: loc.coordinate.longitude, alt: loc.altitude)
                        await load()
                    } else { error = "Allow location for Nikon in Settings, or set the place on the Pi's page." }
                }
            } label: { Label("Use this phone's location", systemImage: "location") }
                .buttonStyle(.bordered).font(.footnote)
        }
    }

    private func time(_ iso: String?) -> String {
        guard let iso, let d = ISO8601DateFormatter().date(from: iso) else { return "—" }
        return d.formatted(date: .omitted, time: .shortened)
    }
}

struct Panel<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.headline)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.background.secondary, in: .rect(cornerRadius: 16))
    }
}

/// A compass rose with an arrow to the bearing. Without a heading north is up; with the phone's heading the rose turns
/// with the phone, so the arrow points at the aurora in the real world and sits straight up when you face it.
struct Compass: View {
    let bearing: Double
    var heading: Double? = nil
    var body: some View {
        let h = heading ?? 0
        let on = heading.map { abs(Heading.turn(from: $0, to: bearing)) <= Heading.onTarget } ?? false
        ZStack {
            Circle().stroke(on ? Color.green : .secondary.opacity(0.4), lineWidth: on ? 4 : 2)
            if heading != nil { Rectangle().fill(.secondary).frame(width: 2, height: 10).offset(y: -55) }
            ZStack {
                ForEach(Array(["N", "E", "S", "W"].enumerated()), id: \.0) { i, n in
                    Text(n).font(.caption2.bold()).foregroundStyle(n == "N" ? .red : .secondary)
                        .rotationEffect(.degrees(h - Double(i) * 90))      // keep the letters upright
                        .offset(y: -44).rotationEffect(.degrees(Double(i) * 90))
                }
            }
            .rotationEffect(.degrees(-h))
            Image(systemName: "location.north.fill").font(.system(size: 34)).foregroundStyle(.green)
                .rotationEffect(.degrees(bearing - h))
        }
        .animation(.easeOut(duration: 0.2), value: h)
    }
}

/// NOAA's northern-hemisphere OVATION map: the last 24 hours in 5-minute frames, the newest is the forecast.
struct AuroraMap: View {
    struct Frame: Codable { let url: String; let time_tag: String }
    @State private var frames: [Frame] = []
    @State private var index = 0.0
    @State private var image: UIImage?
    @State private var cache: [String: UIImage] = [:]

    var body: some View {
        Panel(title: "Where the lights are") {
            ZStack {
                Color.black
                if let image { Image(uiImage: image).resizable().scaledToFit() } else { ProgressView() }
            }
            .aspectRatio(1, contentMode: .fit)
            .clipShape(.rect(cornerRadius: 12))
            if frames.count > 1 {
                let f = frames[min(Int(index), frames.count - 1)]
                Slider(value: $index, in: 0...Double(frames.count - 1), step: 1)
                HStack {
                    Text(label(f.time_tag, last: Int(index) == frames.count - 1)).font(.caption.bold())
                    Spacer()
                    Button("Latest") { index = Double(frames.count - 1) }.font(.caption)
                }
            }
            Text("Green to red is the chance overhead. You can see aurora up to ~1,000 km toward it, low in the sky.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .task {
            guard frames.isEmpty, let u = URL(string: "https://services.swpc.noaa.gov/products/animations/ovation_north_24h.json"),
                  let (d, _) = try? await URLSession.shared.data(from: u),
                  let all = try? JSONDecoder().decode([Frame].self, from: d) else { return }
            frames = Array(all.suffix(144))      // last 12 hours keeps the slider usable
            index = Double(frames.count - 1)
            await show(Int(index))
        }
        .onChange(of: index) { _, i in Task { await show(Int(i)) } }
    }

    private func show(_ i: Int) async {
        guard frames.indices.contains(i) else { return }
        let url = frames[i].url
        if let img = cache[url] { image = img; return }
        guard let u = URL(string: "https://services.swpc.noaa.gov" + url), let (d, _) = try? await URLSession.shared.data(from: u),
              let img = UIImage(data: d) else { return }
        cache[url] = img
        if frames.indices.contains(Int(index)), frames[Int(index)].url == url { image = img }
    }

    private func label(_ tag: String, last: Bool) -> String {
        let f = ISO8601DateFormatter()
        guard let d = f.date(from: tag) else { return tag }
        return (last ? "Forecast · " : "") + d.formatted(.dateTime.weekday(.abbreviated).hour().minute())
    }
}

/// NOAA's 3-day planetary Kp forecast (3-hour blocks). Kp 5+ is a storm; around Kp 5-6 aurora can reach the northern US.
struct KpForecast: View {
    struct Row: Identifiable { let id = UUID(); let time: Date; let kp: Double; let predicted: Bool }
    @State private var rows: [Row] = []

    var body: some View {
        Panel(title: "Next 3 days (Kp)") {
            if rows.isEmpty { ProgressView() } else {
                Chart(rows) { r in
                    BarMark(x: .value("Time", r.time, unit: .hour), y: .value("Kp", r.kp))
                        .foregroundStyle(r.kp >= 5 ? .purple : r.kp >= 4 ? .green : .gray)
                }
                .chartYScale(domain: 0...9)
                .chartYAxis { AxisMarks(values: [0, 3, 5, 7, 9]) }
                .frame(height: 160)
                if let peak = rows.max(by: { $0.kp < $1.kp }) {
                    Text("Highest: Kp \(peak.kp, specifier: "%.1f") around \(peak.time.formatted(.dateTime.weekday(.abbreviated).hour()))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .task {
            guard rows.isEmpty, let u = URL(string: "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"),
                  let (d, _) = try? await URLSession.shared.data(from: u),
                  let arr = try? JSONSerialization.jsonObject(with: d) as? [[String: Any]] else { return }
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"; f.timeZone = TimeZone(identifier: "UTC")
            rows = arr.compactMap { r in
                guard (r["observed"] as? String) == "predicted", let t = (r["time_tag"] as? String).flatMap(f.date(from:)),
                      let kp = r["kp"] as? Double else { return nil }
                return Row(time: t, kp: kp, predicted: true)
            }
        }
    }
}

/// The Pi's all-night watch.
struct WatchCard: View {
    @Environment(Pi.self) private var pi
    @State private var threshold = 30.0
    @State private var interval = 20
    @State private var seconds = 8
    @State private var iso = "1600"
    @State private var maxCloud = 80.0
    @State private var followLight = true
    @State private var lookInPictures = true

    var body: some View {
        let run = pi.status?.jobs?.aurora
        Panel(title: "Watch tonight") {
            if run?.running == true {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Image(systemName: run?.shooting == true ? "camera.fill" : "eye").foregroundStyle(run?.shooting == true ? .green : .secondary)
                        Text(run?.shooting == true ? "Shooting" : "Watching").font(.headline)
                        Spacer()
                        Text("\(run?.taken ?? 0) frames").monospacedDigit()
                    }
                    Text(run?.note ?? "").font(.subheadline)
                    if (run?.detected ?? 0) > 0 {
                        Label("\(run?.detected ?? 0) frames showed aurora" + ((run?.last_seen ?? "").isEmpty ? "" : ", last at \(run!.last_seen!)"), systemImage: "sparkles")
                            .font(.subheadline.bold()).foregroundStyle(.green)
                    }
                    Text(["Last check \(run?.last_check ?? "—")", "in view \(run?.visible ?? 0)% (trigger \(run?.threshold ?? 0)%)",
                          run?.cloud.map { "\($0)% cloud" }, run?.exposure.flatMap { $0.isEmpty ? nil : $0 }].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Stop watching", role: .destructive) { Task { await pi.stop("aurora") } }.buttonStyle(.bordered)
                }
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Shoot when it's at least \(Int(threshold))% likely in view").font(.subheadline)
                    Slider(value: $threshold, in: 5...80, step: 5)
                    Text(maxCloud >= 100 ? "Ignore clouds" : "…and no more than \(Int(maxCloud))% cloud").font(.subheadline)
                    Slider(value: $maxCloud, in: 20...100, step: 10)
                    Stepper((followLight ? "Longest exposure " : "Exposure ") + "\(seconds) s", value: $seconds, in: 2...30)
                    Stepper("Every \(interval) s between frames", value: $interval, in: 1...300, step: 5)
                    Picker("ISO", selection: $iso) { ForEach(["800", "1600", "3200", "6400"], id: \.self) { Text($0) } }.pickerStyle(.segmented)
                    Toggle("Follow the light", isOn: $followLight).font(.subheadline)
                    Toggle("Look for it in the pictures", isOn: $lookInPictures).font(.subheadline)
                    Text("Tripod, mode dial on M, lens on M focused at infinity, aimed the way the arrow says. The Pi checks NOAA and the clouds every 5 minutes and stops at dawn. "
                         + (lookInPictures ? "When the forecast says no it still takes one test frame, and keeps shooting while frames show green. " : "")
                         + (followLight ? "The exposure adjusts itself to each frame. " : "")
                         + "Turn on alerts below and go to bed.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button {
                        Task { await pi.start("aurora", ["threshold": Int(threshold), "interval": interval, "seconds": seconds, "iso": iso,
                                                         "max_cloud": Int(maxCloud), "auto_exposure": followLight, "detect": lookInPictures]) }
                    } label: { Label("Watch tonight", systemImage: "moon.stars").frame(maxWidth: .infinity).padding(.vertical, 6) }
                        .buttonStyle(.borderedProminent).tint(.green)
                        .disabled(pi.status?.jobs?.anyRunning == true)
                    if let e = run?.error, !e.isEmpty { Text(e).font(.caption).foregroundStyle(.red) }
                    if let n = run?.note, !n.isEmpty, run?.taken ?? 0 > 0 {
                        Text("Last run: \(n)" + ((run?.detected ?? 0) > 0 ? " \(run!.detected!) showed aurora." : "")).font(.caption).foregroundStyle(.secondary)
                    }
                    if let best = run?.best, !best.isEmpty {
                        Text("Best frames: " + best.joined(separator: ", ")).font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
            if let e = pi.lastError { Text(e).font(.caption).foregroundStyle(.red) }
        }
    }
}

/// The next three nights: Kp, clouds and moon rolled into one verdict per night, best hour first.
struct PlanCard: View {
    @Environment(Pi.self) private var pi
    @State private var plan: AuroraPlan?
    @State private var error: String?
    @State private var open: String?

    var body: some View {
        Panel(title: "Next three nights") {
            if let plan {
                ForEach(plan.nights) { n in
                    VStack(alignment: .leading, spacing: 4) {
                        Button { withAnimation { open = open == n.id ? nil : n.id } } label: {
                            HStack {
                                Text(day(n.date)).font(.subheadline.bold()).frame(width: 90, alignment: .leading)
                                Text(n.verdict).font(.subheadline.bold()).foregroundStyle(color(n.verdict))
                                Spacer()
                                Group {
                                    if let kp = n.kp_max { Text("Kp \(kp, specifier: "%.1f")") }
                                    if let c = n.cloud_mean { Label("\(c)%", systemImage: "cloud") }
                                    Label("\(Int(n.moon * 100))%", systemImage: "moon")
                                }
                                .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .buttonStyle(.plain)
                        if let b = n.best, b.score > 0 {
                            Text("Best around \(time(b.time)): \(b.chance)% from Kp\(b.cloud.map { ", \($0)% cloud" } ?? "")")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if open == n.id {
                            ForEach(n.hours) { h in
                                HStack {
                                    Text(time(h.time)).frame(width: 64, alignment: .leading)
                                    Text("Kp \(h.kp ?? 0, specifier: "%.1f")").frame(width: 56, alignment: .leading)
                                    Text(h.cloud.map { "\($0)% cloud" } ?? "—").frame(width: 80, alignment: .leading)
                                    Text(h.moon_altitude > 0 ? "moon up" : "").foregroundStyle(.secondary)
                                    Spacer()
                                    Text("\(h.score)").bold().foregroundStyle(color(AuroraPlanVerdict.of(h.score)))
                                }
                                .font(.caption.monospacedDigit())
                            }
                        }
                    }
                    if n.id != plan.nights.last?.id { Divider() }
                }
                Text("Needs about Kp \(plan.kp_needed, specifier: "%.1f") here. Tap a night for its hours.").font(.caption2).foregroundStyle(.secondary)
            } else if let error {
                Text(error).font(.footnote).foregroundStyle(.secondary)
            } else { ProgressView() }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        do { plan = try await pi.auroraPlan(); error = nil } catch { self.error = error.localizedDescription }
    }

    private func color(_ v: String) -> Color { v == "Good" ? .green : v == "Maybe" ? .orange : .secondary }

    private func day(_ ymd: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: ymd) else { return ymd }
        if Calendar.current.isDateInToday(d) || Calendar.current.isDateInYesterday(d) && Calendar.current.component(.hour, from: .now) < 12 { return "Tonight" }
        return d.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }

    private func time(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter().date(from: iso) else { return iso }
        return d.formatted(date: .omitted, time: .shortened)
    }
}

enum AuroraPlanVerdict {
    static func of(_ score: Int) -> String { score >= 40 ? "Good" : score >= 15 ? "Maybe" : "Poor" }
}

/// Phone alerts through the free ntfy app: the Pi posts when shooting starts, when frames show aurora, and at dawn.
struct AlertsCard: View {
    @Environment(Pi.self) private var pi
    @Environment(\.openURL) private var openURL
    @State private var settings: NotifySettings?
    @State private var message: String?

    var body: some View {
        Panel(title: "Alerts") {
            if let s = settings {
                Toggle("Send alerts to this phone", isOn: Binding(get: { s.enabled }, set: { v in save(["enabled": v]) }))
                Toggle("Include a small picture", isOn: Binding(get: { s.pictures }, set: { v in save(["pictures": v]) }))
                    .disabled(!s.enabled)
                Text("Install the free **ntfy** app and subscribe to this topic (it's random to your Pi; anyone who knows it can read the alerts):")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Text(s.topic).font(.footnote.monospaced()).textSelection(.enabled)
                    Spacer()
                    Button { UIPasteboard.general.string = s.topic; message = "Topic copied." } label: { Image(systemName: "doc.on.doc") }
                }
                HStack {
                    Button("Get ntfy") { openURL(URL(string: "https://apps.apple.com/app/ntfy/id1625396347")!) }
                    Button("Test alert") { Task { do { try await pi.testNotify(); message = "Sent. Check ntfy." } catch { message = error.localizedDescription } } }
                    Spacer()
                    Button("New topic") { save(["new_topic": true]) }.font(.caption)
                }
                .buttonStyle(.bordered)
                if let message { Text(message).font(.caption).foregroundStyle(.secondary) }
            } else if let message {
                Text(message).font(.footnote).foregroundStyle(.secondary)
            } else { ProgressView() }
        }
        .task { do { settings = try await pi.notifySettings() } catch { message = error.localizedDescription } }
    }

    private func save(_ fields: [String: Any]) {
        Task {
            do { settings = try await pi.saveNotify(fields); message = nil } catch { message = error.localizedDescription }
        }
    }
}

/// The phone's compass while the Aurora tab is open: true north when location is allowed, magnetic otherwise.
@MainActor @Observable
final class Heading: NSObject, CLLocationManagerDelegate {
    static let onTarget = 8.0
    var degrees: Double?
    @ObservationIgnored private let manager = CLLocationManager()

    /// Signed degrees to turn, -180...180; negative is left.
    static func turn(from heading: Double, to bearing: Double) -> Double {
        (bearing - heading + 540).truncatingRemainder(dividingBy: 360) - 180
    }

    func start() {
        guard CLLocationManager.headingAvailable() else { return }
        manager.delegate = self
        manager.headingFilter = 1
        manager.headingOrientation = .portrait
        manager.startUpdatingHeading()
    }
    func stop() { manager.stopUpdatingHeading() }

    nonisolated func locationManager(_ m: CLLocationManager, didUpdateHeading h: CLHeading) {
        let value = h.trueHeading >= 0 ? h.trueHeading : h.magneticHeading
        guard h.headingAccuracy >= 0 else { return }
        Task { @MainActor in degrees = value }
    }
    nonisolated func locationManagerShouldDisplayHeadingCalibration(_ m: CLLocationManager) -> Bool { true }
}

/// One location fix for "Use this phone's location".
@MainActor
final class Locator: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var waiting: CheckedContinuation<CLLocation?, Never>?

    func current() async -> CLLocation? {
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        return await withCheckedContinuation { c in
            waiting = c
            manager.requestLocation()
        }
    }

    nonisolated func locationManager(_ m: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        Task { @MainActor in waiting?.resume(returning: locs.last); waiting = nil }
    }
    nonisolated func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in waiting?.resume(returning: nil); waiting = nil }
    }
    nonisolated func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        Task { @MainActor in
            if m.authorizationStatus == .denied || m.authorizationStatus == .restricted { waiting?.resume(returning: nil); waiting = nil }
            else if m.authorizationStatus != .notDetermined, waiting != nil { m.requestLocation() }
        }
    }
}
