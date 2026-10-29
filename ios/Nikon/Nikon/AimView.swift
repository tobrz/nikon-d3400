import CoreMotion
import SwiftUI

/// Line up the camera with the phone lying flat on top of it: the compass says which way to turn the tripod head,
/// the motion sensor says how far to tilt the lens up. Both green = lock the tripod.
struct AimView: View {
    @Environment(\.dismiss) private var dismiss
    let bearing: Double
    let direction: String
    let elevation: Double?
    @State private var heading = Heading()
    @State private var tilt = Tilt()

    static let tiltTolerance = 3.0

    /// Aim at the glow, but keep at least a little sky above the horizon and some foreground at the bottom of the frame.
    private var targetTilt: Double { min(45, max(10, elevation ?? 10)) }

    var body: some View {
        let turn = heading.degrees.map { Heading.turn(from: $0, to: bearing) }
        let tiltOff = tilt.degrees.map { targetTilt - $0 }
        let turnOK = turn.map { abs($0) <= Heading.onTarget } ?? false
        let tiltOK = tiltOff.map { abs($0) <= Self.tiltTolerance } ?? false
        NavigationStack {
            ScrollView {
                VStack(spacing: 22) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("1. Camera on the tripod, level, lens in landscape.")
                        Text("2. Lay this phone flat on top of the camera, screen up, the top of the phone pointing the same way as the lens.")
                        Text("3. Turn the tripod head until the arrow points straight up, then tilt the lens until the level turns green.")
                    }
                    .font(.footnote).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)

                    Compass(bearing: bearing, heading: heading.degrees).frame(width: 220, height: 220)
                    Group {
                        if let turn {
                            if turnOK { Label("Facing \(direction) (\(Int(bearing))°)", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
                            else { Label("Turn \(turn < 0 ? "left" : "right") \(Int(abs(turn)))°", systemImage: turn < 0 ? "arrow.turn.up.left" : "arrow.turn.up.right") }
                        } else { Text("This device has no compass.").foregroundStyle(.secondary) }
                    }
                    .font(.title3.bold())

                    TiltLevel(current: tilt.degrees, target: targetTilt, ok: tiltOK).frame(height: 70)
                    Group {
                        if let tiltOff {
                            if tiltOK { Label("Tilted \(Int(targetTilt))° up", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
                            else { Label("Tilt \(tiltOff > 0 ? "up" : "down") \(Int(abs(tiltOff).rounded()))°", systemImage: tiltOff > 0 ? "arrow.up" : "arrow.down") }
                        } else { Text("No motion sensor.").foregroundStyle(.secondary) }
                    }
                    .font(.title3.bold())

                    if turnOK && tiltOK {
                        Text("Lined up. Lock the tripod, take the phone off, and start the watch.")
                            .font(.headline).foregroundStyle(.green).multilineTextAlignment(.center)
                    }
                    Text(elevation.map { $0 < 10 ? "The glow is low (\(Int($0))° up), so aim \(Int(targetTilt))° up to keep the horizon near the bottom of the frame." : "The strongest glow is about \(Int($0))° up." } ?? "")
                        .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    Text("A camera body can pull a phone's compass a few degrees. If the arrow jumps around, check the direction with the phone held a little above the camera.")
                        .font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
                .padding()
            }
            .sensoryFeedback(.success, trigger: turnOK && tiltOK) { _, on in on }
            .sensoryFeedback(.selection, trigger: turnOK) { _, on in on }
            .sensoryFeedback(.selection, trigger: tiltOK) { _, on in on }
            .navigationTitle("Line up the camera").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .onAppear {
                heading.start(); tilt.start()
                UIApplication.shared.isIdleTimerDisabled = true   // the screen stays on while you fiddle with the tripod
            }
            .onDisappear {
                heading.stop(); tilt.stop()
                UIApplication.shared.isIdleTimerDisabled = false
            }
        }
    }
}

/// A side-on view of the lens: a line at the current tilt and a mark at the target.
struct TiltLevel: View {
    let current: Double?
    let target: Double
    let ok: Bool
    /// -10° at the bottom, 60° at the top.
    private func y(_ deg: Double, _ h: CGFloat) -> CGFloat { h - CGFloat(min(60, max(-10, deg)) + 10) / 70 * h }

    var body: some View {
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            let y = { (deg: Double) in self.y(deg, h) }
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 10).fill(.background.secondary)
                Path { p in p.move(to: CGPoint(x: 0, y: y(0))); p.addLine(to: CGPoint(x: w, y: y(0))) }
                    .stroke(.secondary.opacity(0.5), style: StrokeStyle(lineWidth: 1, dash: [4]))
                Text("horizon").font(.caption2).foregroundStyle(.secondary).position(x: 30, y: y(0) - 8)
                Rectangle().fill(.green.opacity(0.25)).frame(height: max(4, y(target - AimView.tiltTolerance) - y(target + AimView.tiltTolerance)))
                    .offset(y: y(target + AimView.tiltTolerance))
                if let current {
                    Capsule().fill(ok ? Color.green : .yellow).frame(width: w * 0.6, height: 6)
                        .position(x: w * 0.2 + w * 0.3, y: y(current))
                        .animation(.easeOut(duration: 0.15), value: current)
                    Text("\(Int(current.rounded()))°").font(.caption.bold().monospacedDigit()).position(x: w - 24, y: y(current) - 12)
                }
            }
        }
    }
}

/// How far the top edge of a flat-lying phone is tipped up (= the lens tilt when the phone sits on the camera).
@MainActor @Observable
final class Tilt {
    var degrees: Double?
    @ObservationIgnored private let motion = CMMotionManager()

    func start() {
        guard motion.isDeviceMotionAvailable else { return }
        motion.deviceMotionUpdateInterval = 1.0 / 15
        motion.startDeviceMotionUpdates(to: .main) { [weak self] m, _ in
            guard let g = m?.gravity else { return }
            // Flat, screen up: gravity is (0, 0, -1). Tipping the top edge up moves it to -y.
            self?.degrees = asin(max(-1, min(1, -g.y))) * 180 / .pi
        }
    }
    func stop() { motion.stopDeviceMotionUpdates() }
}
