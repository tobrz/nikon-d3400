// Draws ios/Nikon/Nikon/Assets.xcassets/AppIcon.appiconset/AppIcon.png: swift ios/tools/make-icon.swift <out.png>
// 1024×1024: charcoal gradient, a yellow aperture of six blades, a small red record dot.
import AppKit

let size: CGFloat = 1024
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGradient(colors: [NSColor(white: 0.20, alpha: 1), NSColor(white: 0.04, alpha: 1)])!.draw(in: NSRect(x: 0, y: 0, width: size, height: size), angle: -70)
let c = NSPoint(x: size / 2, y: size / 2), R: CGFloat = 330, r: CGFloat = 120
let yellow = NSColor(srgbRed: 1.0, green: 0.84, blue: 0.0, alpha: 1)
// Ring
let ring = NSBezierPath(ovalIn: NSRect(x: c.x - R - 40, y: c.y - R - 40, width: 2 * (R + 40), height: 2 * (R + 40)))
ring.lineWidth = 44; yellow.setStroke(); ring.stroke()
// Six blades: quads from the inner hexagon to the outer circle, slightly twisted.
for i in 0..<6 {
    let a0 = CGFloat(i) * .pi / 3, a1 = a0 + .pi / 3
    let p = NSBezierPath()
    p.move(to: NSPoint(x: c.x + r * cos(a0), y: c.y + r * sin(a0)))
    p.line(to: NSPoint(x: c.x + R * cos(a0 + 0.35), y: c.y + R * sin(a0 + 0.35)))
    p.line(to: NSPoint(x: c.x + R * cos(a1 + 0.35), y: c.y + R * sin(a1 + 0.35)))
    p.line(to: NSPoint(x: c.x + r * cos(a1), y: c.y + r * sin(a1)))
    p.close()
    (i % 2 == 0 ? yellow : NSColor(srgbRed: 0.93, green: 0.74, blue: 0.0, alpha: 1)).setFill(); p.fill()
    NSColor(white: 0.08, alpha: 1).setStroke(); p.lineWidth = 10; p.stroke()
}
NSColor(srgbRed: 0.95, green: 0.20, blue: 0.20, alpha: 1).setFill()
NSBezierPath(ovalIn: NSRect(x: 800, y: 800, width: 110, height: 110)).fill()
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
