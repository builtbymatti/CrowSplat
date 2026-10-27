import CoreText
import SwiftUI

/// CrowSplat's palette: the Instrument direction, set clean. Anodized metal
/// greys that lean olive, aluminium for the one control that matters, and
/// signal orange only where something is happening (progress, running,
/// keyboard focus). Never a surface, never a glow.
enum Palette {
    static let canvas   = Color(hex: 0x161814)   // anodized: window, shader base
    static let surface  = Color(hex: 0x1E201C)   // panels, sidebar, sheets
    static let raised   = Color(hex: 0x262923)   // cards, fields, selected row
    static let lifted   = Color(hex: 0x2E322B)   // hover
    static let sunk     = Color(hex: 0x121410)   // grooves and tracks, below the surface
    static let ink      = Color(hex: 0xE7E9E2)   // label: text, the crow
    static let ink2     = Color(hex: 0x9A9F93)   // secondary text
    static let ink3     = Color(hex: 0x6C7066)   // captions
    static let ink4     = Color(hex: 0x3B3F37)   // disabled, ticks
    static let alu      = Color(hex: 0xB9BDB4)   // the primary control face
    static let signal   = Color(hex: 0xFF6B2C)   // information only
    static let failure  = Color(hex: 0xE5484D)   // errors: red, clearly not "running"
    /// The emboss from the colour cards: a light lip on top, a dark rim below.
    static let lip      = Color.white.opacity(0.07)
    static let edge     = Color.white.opacity(0.035)
    static let rim      = Color.black.opacity(0.38)
}

enum Metrics {
    static let radius: CGFloat = 10        // cards, panels
    static let controlRadius: CGFloat = 8  // buttons, fields
    static let gutter: CGFloat = 28        // page padding
    static let sidebarWidth: CGFloat = 220
}

/// Motion tokens. Controls never scale; motion is reserved for things that
/// move for a reason (a detent snapping, a value changing, progress).
enum Motion {
    static let snappy = Animation.spring(response: 0.28, dampingFraction: 0.9)
    static let smooth = Animation.spring(response: 0.42, dampingFraction: 0.92)
    static let gentle = Animation.spring(response: 0.7, dampingFraction: 0.94)
    static let hover = Animation.easeOut(duration: 0.14)
    static let press = Animation.easeOut(duration: 0.08)
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: opacity)
    }
}

// MARK: - Type

/// Alpha Lyrae (Fontfabric for Vega, SIL OFL) for everything. It has one
/// weight, so hierarchy comes from size and tone. By default every fourth
/// glyph swaps to a pixel alternate (its `calt` feature); UI text turns that
/// off, and only the wordmark keeps it. Geist Mono stays for logs and paths.
enum Typeface {
    /// `weight` is kept so call sites read naturally; the face has one weight.
    static func sans(_ size: CGFloat, _ weight: Weight = .regular) -> Font {
        alpha(size, glitch: false)
    }

    /// The wordmark: Alpha Lyrae with its pixel alternates on.
    static func wordmark(_ size: CGFloat) -> Font {
        alpha(size, glitch: true)
    }

    static func mono(_ size: CGFloat, medium: Bool = false) -> Font {
        .custom(medium ? "GeistMono-Medium" : "GeistMono-Regular", size: size)
    }

    enum Weight { case regular, medium, semibold, bold }

    private static func alpha(_ size: CGFloat, glitch: Bool) -> Font {
        var attributes: [CFString: Any] = [kCTFontNameAttribute: "AlphaLyrae-Medium" as CFString]
        if !glitch {
            attributes[kCTFontFeatureSettingsAttribute] = [[
                kCTFontOpenTypeFeatureTag: "calt" as CFString,
                kCTFontOpenTypeFeatureValue: 0,
            ] as [CFString: Any]]
        }
        let descriptor = CTFontDescriptorCreateWithAttributes(attributes as CFDictionary)
        return Font(CTFontCreateWithFontDescriptor(descriptor, size, nil))
    }
}

extension Font {
    static let crowDisplay = Typeface.sans(40)
    static let crowTitle   = Typeface.sans(25)
    static let crowHeading = Typeface.sans(15)
    static let crowBody    = Typeface.sans(13.5)
    static let crowLabel   = Typeface.sans(12.5)
    static let crowCaption = Typeface.sans(12)
    static let crowData    = Typeface.sans(12).monospacedDigit()
    static let crowLog     = Typeface.mono(11.5)
}

// MARK: - Surfaces

/// A panel set off by tone and the emboss: a 1 pt light lip along the top,
/// a hairline of its own colour around it, a 1 pt dark rim underneath. The
/// same edge as the colour cards on the brand page. No blur, no glow.
struct SurfaceModifier: ViewModifier {
    var fill: Color = Palette.raised
    var radius: CGFloat = Metrics.radius

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .background(fill, in: shape)
            .overlay {
                shape.strokeBorder(Palette.edge, lineWidth: 1)
                shape.strokeBorder(LinearGradient(stops: [.init(color: Palette.lip, location: 0),
                                                          .init(color: .clear, location: 0.12)],
                                                  startPoint: .top, endPoint: .bottom), lineWidth: 1)
            }
            .background {
                // The rim: the panel's lower edge catching no light.
                shape.fill(Palette.rim).offset(y: 1)
            }
    }
}

/// The opposite of a surface: a groove pressed into it (tracks, wells).
struct SunkModifier: ViewModifier {
    var radius: CGFloat = Metrics.controlRadius

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .background(Palette.sunk, in: shape)
            .overlay {
                shape.strokeBorder(LinearGradient(colors: [.black.opacity(0.45), .clear],
                                                  startPoint: .top, endPoint: .center), lineWidth: 1)
            }
            .overlay(alignment: .bottom) {
                // Light catching the far lip of the groove.
                shape.strokeBorder(LinearGradient(stops: [.init(color: .clear, location: 0.8),
                                                          .init(color: Palette.edge, location: 1)],
                                                  startPoint: .top, endPoint: .bottom), lineWidth: 1)
            }
    }
}

extension View {
    func surface(_ fill: Color = Palette.raised, radius: CGFloat = Metrics.radius) -> some View {
        modifier(SurfaceModifier(fill: fill, radius: radius))
    }

    func sunk(radius: CGFloat = Metrics.controlRadius) -> some View {
        modifier(SunkModifier(radius: radius))
    }
}

extension View {
    /// macOS 26 draws a hard edge where scrolled content meets the top; the
    /// surfaces here are calm, so the edge stays soft.
    @ViewBuilder
    func softScrollEdge() -> some View {
        if #available(macOS 26.0, *) {
            self.scrollEdgeEffectStyle(.soft, for: .top)
        } else {
            self
        }
    }
}
