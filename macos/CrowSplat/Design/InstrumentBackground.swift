import SwiftUI

/// The window's ground (see Instrument.metal). Decoration only: nothing
/// sits on it that depends on it drawing.
struct InstrumentBackground: View {
    var strength: Double = 1
    /// Pointer in unit coordinates (0-1, top left), eased toward by the shader light.
    var pointer: CGPoint = CGPoint(x: 0.75, y: 0.3)

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private let start = Date()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduceMotion)) { tl in
            GeometryReader { geo in
                Rectangle()
                    .fill(Palette.canvas)
                    .colorEffect(ShaderLibrary.instrument(
                        .float2(geo.size),
                        .float(Float(tl.date.timeIntervalSince(start))),
                        .float2(pointer),
                        .float(Float(strength))))
            }
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }
}

/// Tracks the pointer over a view for the shader's light.
struct PointerLight: ViewModifier {
    @Binding var point: CGPoint

    func body(content: Content) -> some View {
        GeometryReader { geo in
            content.onContinuousHover { phase in
                guard case .active(let p) = phase, geo.size.width > 0 else { return }
                point = CGPoint(x: p.x / geo.size.width, y: p.y / geo.size.height)
            }
        }
    }
}
