// Renders CrowSplat's app icon set and DMG background from the same code
// the app draws with (crow geometry, splat field, palette, Geist).
//
//   mkdir -p /tmp/rb && cp macos/scripts/RenderBrand.swift /tmp/rb/main.swift
//   swiftc -o /tmp/render-brand /tmp/rb/main.swift \
//       macos/CrowSplat/Design/{Theme,CrowMark,SplatField}.swift && /tmp/render-brand macos
//
// Writes CrowSplat/Resources/Assets.xcassets/AppIcon.appiconset/* and
// scripts/dmg-background.png (+ @2x).

import AppKit
import CoreText
import SwiftUI

@MainActor
func save(_ view: some View, size: CGSize, scale: CGFloat, to url: URL) {
    let renderer = ImageRenderer(content: view.frame(width: size.width, height: size.height))
    renderer.scale = scale
    guard let cg = renderer.cgImage else { fatalError("render failed: \(url.lastPathComponent)") }
    let rep = NSBitmapImageRep(cgImage: cg)
    try! rep.representation(using: .png, properties: [:])!.write(to: url)
}

/// macOS icon grid: the body is a continuous-corner square inset in the canvas.
struct AppIcon: View {
    let pixels: CGFloat

    var body: some View {
        let canvas = pixels
        let body = canvas * 0.805
        ZStack {
            RoundedRectangle(cornerRadius: body * 0.225, style: .continuous)
                .fill(LinearGradient(colors: [Color(hex: 0x2A2D27), Color(hex: 0x161814)],
                                     startPoint: .top, endPoint: .bottom))
                .overlay {
                    // The lip: light catching the top edge, the same move as every surface in the app.
                    RoundedRectangle(cornerRadius: body * 0.225, style: .continuous)
                        .strokeBorder(LinearGradient(colors: [.white.opacity(0.16), .white.opacity(0.02)],
                                                     startPoint: .top, endPoint: .center),
                                      lineWidth: max(1, canvas / 256))
                }
                .frame(width: body, height: body)
            if pixels >= 256 {
                CrowShape().fill(Palette.ink.opacity(0.18))
                    .frame(width: body * 0.66, height: body * 0.66)
                SplatField(formation: 1, count: 1500, splatScale: body / 380)
                    .frame(width: body * 0.8, height: body * 0.8)
            } else {
                CrowShape().fill(Palette.ink)
                    .frame(width: body * 0.62, height: body * 0.62)
            }
        }
        .frame(width: canvas, height: canvas)
    }
}

struct DMGBackground: View {
    var body: some View {
        ZStack {
            Palette.canvas
            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    CrowShape().fill(Palette.ink).frame(width: 22, height: 16)
                    Text("CrowSplat").font(.custom("AlphaLyrae-Medium", size: 16)).foregroundStyle(Palette.ink)
                }
                .padding(.top, 34)
                Spacer()
                Text("Drag CrowSplat into Applications")
                    .font(.custom("AlphaLyrae-Medium", size: 13))
                    .foregroundStyle(Palette.ink3)
                    .padding(.bottom, 40)
            }
            // A drawn arrow between the two icon slots (icons sit at x 165 and 495).
            Path { p in
                p.move(to: CGPoint(x: 268, y: 200))
                p.addLine(to: CGPoint(x: 392, y: 200))
                p.move(to: CGPoint(x: 380, y: 190))
                p.addLine(to: CGPoint(x: 392, y: 200))
                p.addLine(to: CGPoint(x: 380, y: 210))
            }
            .stroke(Palette.ink3, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        }
    }
}

@MainActor
func run() {
    let mac = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "macos")
    let fonts = mac.appending(path: "CrowSplat/Resources/Fonts")
    for f in (try? FileManager.default.contentsOfDirectory(at: fonts, includingPropertiesForKeys: nil)) ?? [] {
        CTFontManagerRegisterFontsForURL(f as CFURL, .process, nil)
    }

    let iconset = mac.appending(path: "CrowSplat/Resources/Assets.xcassets/AppIcon.appiconset")
    try? FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
    var images: [[String: String]] = []
    for points in [16, 32, 128, 256, 512] {
        for scale in [1, 2] {
            let px = points * scale
            let name = "icon_\(points)x\(points)\(scale == 2 ? "@2x" : "").png"
            save(AppIcon(pixels: CGFloat(px)), size: CGSize(width: px, height: px), scale: 1,
                 to: iconset.appending(path: name))
            images.append(["idiom": "mac", "size": "\(points)x\(points)", "scale": "\(scale)x", "filename": name])
        }
    }
    let contents: [String: Any] = ["images": images, "info": ["author": "xcode", "version": 1]]
    try! JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
        .write(to: iconset.appending(path: "Contents.json"))

    let size = CGSize(width: 660, height: 400)
    save(DMGBackground(), size: size, scale: 1, to: mac.appending(path: "scripts/dmg-background.png"))
    save(DMGBackground(), size: size, scale: 2, to: mac.appending(path: "scripts/dmg-background@2x.png"))
    print("brand assets written")
}

MainActor.assumeIsolated { run() }
