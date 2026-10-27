import SwiftUI

// MARK: - Buttons

/// The one action a screen is about. Solid ink, dark label. Hover shifts the
/// tone; press compresses a hair. It never jumps.
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    var wide = false

    func makeBody(configuration: Configuration) -> some View {
        PrimaryBody(configuration: configuration, enabled: enabled, wide: wide)
    }

    private struct PrimaryBody: View {
        let configuration: Configuration
        let enabled: Bool
        let wide: Bool
        @State private var hovering = false

        var body: some View {
            configuration.label
                .font(.crowLabel)
                .foregroundStyle(Palette.canvas)
                .padding(.horizontal, 14)
                .frame(minWidth: wide ? 160 : nil, minHeight: 32)
                .background(fill, in: .rect(cornerRadius: Metrics.controlRadius, style: .continuous))
                .scaleEffect(configuration.isPressed ? 0.98 : 1)
                .opacity(enabled ? 1 : 0.35)
                .animation(Motion.hover, value: hovering)
                .animation(Motion.snappy, value: configuration.isPressed)
                .onHover { hovering = $0 }
                .contentShape(.rect)
        }

        private var fill: Color {
            if configuration.isPressed { return Palette.ink2 }
            return hovering ? Color(hex: 0xFFFFFF) : Palette.ink
        }
    }
}

/// Everything that is not the main action: label and optional icon, a tonal
/// surface appears under it on hover.
struct QuietButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    var tone: Color = Palette.ink2

    func makeBody(configuration: Configuration) -> some View {
        QuietBody(configuration: configuration, enabled: enabled, tone: tone)
    }

    private struct QuietBody: View {
        let configuration: Configuration
        let enabled: Bool
        let tone: Color
        @State private var hovering = false

        var body: some View {
            configuration.label
                .font(.crowLabel)
                .foregroundStyle(hovering && enabled ? Palette.ink : tone)
                .padding(.horizontal, 10)
                .frame(minHeight: 30)
                .background(hovering && enabled ? Palette.lifted : .clear,
                            in: .rect(cornerRadius: Metrics.controlRadius, style: .continuous))
                .opacity(enabled ? (configuration.isPressed ? 0.7 : 1) : 0.35)
                .animation(Motion.hover, value: hovering)
                .onHover { hovering = $0 }
                .contentShape(.rect)
        }
    }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var primary: PrimaryButtonStyle { PrimaryButtonStyle() }
}

extension ButtonStyle where Self == QuietButtonStyle {
    static var quiet: QuietButtonStyle { QuietButtonStyle() }
}

/// Icon + text, spaced the same everywhere.
struct Labeled: View {
    let title: String
    let glyph: Glyph?
    var iconSize: CGFloat = 14

    init(_ title: String, _ glyph: Glyph? = nil, iconSize: CGFloat = 14) {
        self.title = title
        self.glyph = glyph
        self.iconSize = iconSize
    }

    var body: some View {
        HStack(spacing: 7) {
            if let glyph { Icon(glyph, size: iconSize) }
            Text(title)
        }
    }
}

// MARK: - Progress

/// A slim track whose fill grows by width: the rounded caps stay round at
/// every length, and the fill always reaches the full track at 100.
struct ProgressTrack: View {
    var value: Double          // 0-100; nil-like negative = indeterminate
    var height: CGFloat = 3
    var fill: Color = Palette.ink

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Palette.ink4.opacity(0.6))
                if value < 0 {
                    IndeterminateSweep(height: height, fill: fill)
                } else {
                    Capsule()
                        .fill(fill)
                        .frame(width: max(height, geo.size.width * min(1, value / 100)))
                        .animation(reduceMotion ? nil : Motion.smooth, value: value)
                }
            }
        }
        .frame(height: height)
        .clipShape(Capsule())
        .accessibilityElement()
        .accessibilityValue(value < 0 ? "In progress" : "\(Int(value)) percent")
    }
}

private struct IndeterminateSweep: View {
    let height: CGFloat
    let fill: Color

    var body: some View {
        TimelineView(.animation) { tl in
            GeometryReader { geo in
                let t = tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6
                let w = geo.size.width * 0.28
                Capsule()
                    .fill(fill.opacity(0.8))
                    .frame(width: w, height: height)
                    .offset(x: -w + (geo.size.width + w) * t)
            }
        }
    }
}

// MARK: - Choice

/// Segmented choice with a sliding indicator. Selection reads through tone:
/// the chosen label is ink on a lifted plate, the rest stay secondary.
struct ChoiceBar<Value: Hashable>: View {
    let options: [(Value, String)]
    @Binding var selection: Value
    @Namespace private var plate

    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { value, title in
                let chosen = value == selection
                Button {
                    withAnimation(Motion.snappy) { selection = value }
                } label: {
                    Text(title)
                        .font(.crowLabel)
                        .foregroundStyle(chosen ? Palette.ink : Palette.ink3)
                        .frame(maxWidth: .infinity, minHeight: 28)
                        .background {
                            if chosen {
                                RoundedRectangle(cornerRadius: 6, style: .continuous)
                                    .fill(Palette.lifted)
                                    .matchedGeometryEffect(id: "plate", in: plate)
                            }
                        }
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .surface(Palette.canvas, radius: Metrics.controlRadius)
    }
}

/// A checkbox that is a sentence: the box, a title, a quiet explanation.
struct CheckRow: View {
    let title: String
    var detail: String? = nil
    @Binding var isOn: Bool
    @State private var hovering = false

    var body: some View {
        Button {
            withAnimation(Motion.snappy) { isOn.toggle() }
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 4, style: .continuous)
                        .fill(isOn ? Palette.ink : Palette.canvas)
                    RoundedRectangle(cornerRadius: 4, style: .continuous)
                        .strokeBorder(isOn ? .clear : (hovering ? Palette.ink3 : Palette.ink4), lineWidth: 1)
                    if isOn {
                        Icon(.check, size: 11)
                            .foregroundStyle(Palette.canvas)
                            .transition(.scale(scale: 0.4).combined(with: .opacity))
                    }
                }
                .frame(width: 15, height: 15)
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.crowBody).foregroundStyle(Palette.ink)
                    if let detail {
                        Text(detail).font(.crowCaption).foregroundStyle(Palette.ink3)
                    }
                }
                Spacer(minLength: 0)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(Motion.hover, value: hovering)
    }
}

// MARK: - Fields

struct FieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration
            .textFieldStyle(.plain)
            .font(.crowBody)
            .foregroundStyle(Palette.ink)
            .padding(.horizontal, 10)
            .frame(height: 32)
            .surface(Palette.canvas, radius: Metrics.controlRadius)
    }
}

/// Small caption above a control. Sentence case, secondary tone; it names
/// the control and stays out of its way.
struct FieldLabel: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text).font(.crowLabel).foregroundStyle(Palette.ink2)
    }
}

// MARK: - Formatting

enum Format {
    static func duration(_ seconds: Double) -> String {
        if seconds < 0 { return "" }
        if seconds < 60 { return "under a minute" }
        let m = Int((seconds / 60).rounded())
        if m < 60 { return "\(m) min" }
        return "\(m / 60) h \(String(format: "%02d", m % 60))"
    }

    static func clock(_ seconds: Double) -> String {
        let s = Int(seconds.rounded())
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
                         : String(format: "%d:%02d", s / 60, s % 60)
    }

    static func relative(_ date: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        return f.localizedString(for: date, relativeTo: .now)
    }

    static func bytes(_ count: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: count, countStyle: .file)
    }
}
