import SwiftUI

/// CrowSplat's whole palette. Off-white ink on a near-black that leans warm,
/// never blue. There is no brand hue: emphasis is tonal (a step lighter or
/// darker), and colour is reserved for the one thing that needs it, failure.
enum Palette {
    static let canvas   = Color(hex: 0x0C0C0B)   // window background
    static let surface  = Color(hex: 0x131312)   // panels, sidebar
    static let raised   = Color(hex: 0x1A1A19)   // cards, fields
    static let lifted   = Color(hex: 0x222220)   // hover / pressed surfaces
    static let ink      = Color(hex: 0xEDECE7)   // primary text, the crow
    static let ink2     = Color(hex: 0xA8A59E)   // secondary text
    static let ink3     = Color(hex: 0x6E6B65)   // tertiary, captions
    static let ink4     = Color(hex: 0x3D3B38)   // disabled, tracks
    static let failure  = Color(hex: 0xD98A74)   // muted brick, only for errors
    /// The edge of a surface is its own colour, lifted, not a drawn line.
    static let edge     = Color.white.opacity(0.055)
    static let lip      = Color.white.opacity(0.07)  // top highlight on raised surfaces
}

enum Metrics {
    static let radius: CGFloat = 10        // cards, panels
    static let controlRadius: CGFloat = 8  // buttons, fields
    static let gutter: CGFloat = 28        // page padding
    static let sidebarWidth: CGFloat = 220
}

/// Motion tokens. Springs over curves: they settle instead of stopping, and
/// an interrupted animation keeps its velocity.
enum Motion {
    static let snappy = Animation.spring(response: 0.28, dampingFraction: 0.86)
    static let smooth = Animation.spring(response: 0.45, dampingFraction: 0.9)
    static let gentle = Animation.spring(response: 0.7, dampingFraction: 0.92)
    static let hover = Animation.easeOut(duration: 0.14)
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

/// Geist for everything; Geist Mono only where the content is data
/// (step counts, file sizes, durations, paths).
enum Typeface {
    static func sans(_ size: CGFloat, _ weight: Weight = .regular) -> Font {
        .custom(weight.postscript, size: size)
    }

    static func mono(_ size: CGFloat, medium: Bool = false) -> Font {
        .custom(medium ? "GeistMono-Medium" : "GeistMono-Regular", size: size)
    }

    enum Weight {
        case regular, medium, semibold, bold
        var postscript: String {
            switch self {
            case .regular: "Geist-Regular"
            case .medium: "Geist-Medium"
            case .semibold: "Geist-SemiBold"
            case .bold: "Geist-Bold"
            }
        }
    }
}

extension Font {
    static let crowDisplay = Typeface.sans(40, .semibold)
    static let crowTitle   = Typeface.sans(24, .semibold)
    static let crowHeading = Typeface.sans(15, .medium)
    static let crowBody    = Typeface.sans(13)
    static let crowLabel   = Typeface.sans(12, .medium)
    static let crowCaption = Typeface.sans(11.5)
    static let crowData    = Typeface.mono(11.5)
}

// MARK: - Surfaces

/// A panel lifted off the canvas by tone and a self-coloured edge with a
/// faint top lip, the way light catches a rounded rim. No drop shadow.
struct SurfaceModifier: ViewModifier {
    var fill: Color = Palette.raised
    var radius: CGFloat = Metrics.radius

    func body(content: Content) -> some View {
        content
            .background(fill, in: .rect(cornerRadius: radius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(colors: [Palette.lip, Palette.edge, Palette.edge.opacity(0.6)],
                                       startPoint: .top, endPoint: .bottom),
                        lineWidth: 1)
            }
    }
}

extension View {
    func surface(_ fill: Color = Palette.raised, radius: CGFloat = Metrics.radius) -> some View {
        modifier(SurfaceModifier(fill: fill, radius: radius))
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
