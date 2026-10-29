import Charts
import SwiftUI

/// Star focus: the Pi measures how tight the brightest star is in a live-view frame (half-flux diameter, smaller is
/// sharper). Step near/far, watch the number and the history, stop at the smallest. Zoom shows the star itself.
struct StarFocusView: View {
    @Environment(Pi.self) private var pi
    var onStart: () -> Void = {}
    @State private var metrics: FocusMetrics?
    @State private var zoom: UIImage?
    @State private var history: [Double] = []
    @State private var running = false
    @State private var error: String?

    private var best: Double? { history.min() }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Star focus").font(.subheadline.bold())
            Text("Aim at a bright star, lens on M. The number is the star's size: step Near/Far until it's smallest.")
                .font(.caption2).foregroundStyle(.secondary)
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Color.black
                    if let zoom { Image(uiImage: zoom).resizable().interpolation(.none).scaledToFit() }
                    else { Image(systemName: "sparkle").foregroundStyle(.secondary) }
                }
                .frame(width: 110, height: 110).clipShape(.rect(cornerRadius: 10))
                VStack(alignment: .leading, spacing: 4) {
                    if let m = metrics, m.star, let hfd = m.hfd {
                        Text(String(format: "%.1f px", hfd)).font(.title.bold().monospacedDigit())
                            .foregroundStyle(best.map { hfd <= $0 * 1.05 } == true ? .green : .primary)
                        if let best { Text(String(format: "Best %.1f px", best)).font(.caption).foregroundStyle(.secondary) }
                        if m.saturated { Text("Star is saturated: a shorter exposure reads truer.").font(.caption2).foregroundStyle(.orange) }
                    } else if metrics != nil {
                        Text("No star stands out").font(.subheadline)
                    } else {
                        Text("—").font(.title.bold())
                    }
                    if let m = metrics {
                        Chart(Array(m.histogram.enumerated()), id: \.offset) { i, v in
                            BarMark(x: .value("level", i), y: .value("count", v)).foregroundStyle(.yellow)
                        }
                        .chartXAxis(.hidden).chartYAxis(.hidden).frame(height: 36)
                    }
                }
            }
            if history.count > 1 {
                Chart(Array(history.enumerated()), id: \.offset) { i, v in
                    LineMark(x: .value("try", i), y: .value("size", v)).foregroundStyle(.yellow)
                    PointMark(x: .value("try", i), y: .value("size", v)).foregroundStyle(v == best ? .green : .yellow)
                }
                .chartXAxis(.hidden).frame(height: 70)
            }
            HStack {
                Button(running ? "Stop" : "Keep measuring") { running.toggle(); if running { onStart() } }
                    .buttonStyle(.borderedProminent).tint(running ? .red : .yellow).foregroundStyle(.black)
                Button("Once") { onStart(); Task { await measure() } }.buttonStyle(.bordered).disabled(running)
                Spacer()
                if !history.isEmpty { Button("Reset") { history = [] }.font(.caption) }
            }
            .disabled(pi.cameraName == nil)
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
        }
        .task(id: running) {
            while running && !Task.isCancelled {
                await measure()
                try? await Task.sleep(for: .milliseconds(300))
            }
        }
    }

    private func measure() async {
        do {
            let (m, frame) = try await pi.focusAssist()
            metrics = m
            error = nil
            if m.star, let hfd = m.hfd { history.append(hfd); if history.count > 40 { history.removeFirst() } }
            if let frame, let cg = frame.cgImage {
                // 40 px around the star, blown up.
                let w = CGFloat(cg.width), h = CGFloat(cg.height)
                let rect = CGRect(x: m.x * w - 20, y: m.y * h - 20, width: 40, height: 40).intersection(CGRect(x: 0, y: 0, width: w, height: h))
                zoom = cg.cropping(to: rect).map { UIImage(cgImage: $0) }
            }
        } catch {
            self.error = error.localizedDescription
            running = false
        }
    }
}
