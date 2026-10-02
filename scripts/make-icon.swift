import AppKit
import CoreGraphics
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let context = CGContext(data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
        context.setFillColor(CGColor(red: 0.06, green: 0.46, blue: 0.43, alpha: 1))
        context.addPath(CGPath(roundedRect: CGRect(x: 64, y: 64, width: 896, height: 896), cornerWidth: 200, cornerHeight: 200, transform: nil)); context.fillPath()
        context.setStrokeColor(CGColor(gray: 1, alpha: 0.95)); context.setLineWidth(28)
        context.addPath(CGPath(roundedRect: CGRect(x: 200, y: 300, width: 624, height: 424), cornerWidth: 52, cornerHeight: 52, transform: nil)); context.strokePath()
        context.setFillColor(CGColor(gray: 1, alpha: 0.95))
        for row in 0..<3 {
            for column in 0..<8 {
                context.addPath(CGPath(roundedRect: CGRect(x: 250 + column * 66, y: 495 + row * 66, width: 42, height: 42), cornerWidth: 8, cornerHeight: 8, transform: nil)); context.fillPath()
            }
        }
        context.addPath(CGPath(roundedRect: CGRect(x: 338, y: 372, width: 350, height: 54), cornerWidth: 12, cornerHeight: 12, transform: nil)); context.fillPath()
        let bitmap = NSBitmapImageRep(cgImage: context.makeImage()!)
        let suffix = scale == 2 ? "@2x" : ""
        try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}
