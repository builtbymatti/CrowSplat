import SwiftUI

// MARK: - Buttons

/// The one action a screen is about: an aluminium face with a 3% vertical
/// gradient and the emboss edges. Hover steps the tone up; a press moves one
/// point and turns the light inward. No scale, no glow.
struct PrimaryButtonStyle: ButtonStyle {
    var wide = false

    func makeBody(configuration: Configuration) -> some View {
        EmbossedButton(configuration: configuration, wide: wide, primary: true)
    }
}

/// A second action that still deserves a key (Run again, Install): the panel
/// tone with the same emboss, label in ink.
struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        EmbossedButton(configuration: configuration, wide: false, primary: false)
    }
}

private struct EmbossedButton: View {
    let configuration: ButtonStyleConfiguration
    let wide: Bool
    let primary: Bool
    @Environment(\.isEnabled) private var enabled
    @State private var hovering = false

    var body: some View {
        let pressed = configuration.isPressed
        let shape = RoundedRectangle(cornerRadius: Metrics.controlRadius, style: .continuous)
        configuration.label
            .font(.crowLabel)
            .foregroundStyle(primary ? Color(hex: 0x141612) : Palette.ink)
            .padding(.horizontal, 14)
            .frame(minWidth: wide ? 150 : nil, minHeight: 32)
            .background(face(pressed: pressed), in: shape)
            .overlay {
                // Lip on top at rest; when pressed the light falls inside instead.
                shape.strokeBorder(LinearGradient(
                    stops: pressed
                        ? [.init(color: .black.opacity(0.22), location: 0), .init(color: .clear, location: 0.35)]
                        : [.init(color: .white.opacity(primary ? 0.45 : 0.08), location: 0),
                           .init(color: .clear, location: 0.2),
                           .init(color: .black.opacity(primary ? 0.16 : 0.2), location: 1)],
                    startPoint: .top, endPoint: .bottom), lineWidth: 1)
            }
            .background { if !pressed { shape.fill(Palette.rim).offset(y: 1) } }
            .offset(y: pressed ? 1 : 0)
            .opacity(enabled ? 1 : 0.35)
            .animation(Motion.hover, value: hovering)
            .animation(Motion.press, value: pressed)
            .onHover { hovering = $0 }
            .contentShape(.rect)
    }

    private func face(pressed: Bool) -> LinearGradient {
        let (top, bottom): (UInt32, UInt32) = switch (primary, pressed, hovering && enabled) {
        case (true, true, _): (0xADB1A8, 0xB6BAB1)
        case (true, false, true): (0xCDD1C8, 0xBCC0B7)
        case (true, false, false): (0xC3C7BE, 0xB2B6AD)
        case (false, true, _): (0x23261F, 0x23261F)
        case (false, false, true): (0x33372F, 0x2C2F29)
        case (false, false, false): (0x2C2F29, 0x262923)
        }
        return LinearGradient(colors: [Color(hex: top), Color(hex: bottom)], startPoint: .top, endPoint: .bottom)
    }
}

/// Everything else: label and icon, a quiet surface under it on hover.
struct QuietButtonStyle: ButtonStyle {
    var tone: Color = Palette.ink2

    func makeBody(configuration: Configuration) -> some View {
        QuietBody(configuration: configuration, tone: tone)
    }

    private struct QuietBody: View {
        let configuration: Configuration
        let tone: Color
        @Environment(\.isEnabled) private var enabled
        @State private var hovering = false

        var body: some View {
            configuration.label
                .font(.crowLabel)
                .foregroundStyle(hovering && enabled ? Palette.ink : tone)
                .padding(.horizontal, 10)
                .frame(minHeight: 30)
                .background(configuration.isPressed ? Palette.raised : (hovering && enabled ? Palette.lifted : .clear),
                            in: .rect(cornerRadius: Metrics.controlRadius, style: .continuous))
                .opacity(enabled ? 1 : 0.35)
                .animation(Motion.hover, value: hovering)
                .onHover { hovering = $0 }
                .contentShape(.rect)
        }
    }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var primary: PrimaryButtonStyle { PrimaryButtonStyle() }
}

extension ButtonStyle where Self == SecondaryButtonStyle {
    static var secondary: SecondaryButtonStyle { SecondaryButtonStyle() }
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

/// A groove pressed into the surface; the fill is the one place signal orange
/// is a surface. It grows by width, so the round caps stay round.
struct ProgressTrack: View {
    var value: Double          // 0-100; negative = indeterminate
    var height: CGFloat = 4

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Palette.sunk)
                    .overlay(Capsule().strokeBorder(LinearGradient(colors: [.black.opacity(0.5), .clear],
                                                                   startPoint: .top, endPoint: .bottom), lineWidth: 1))
                if value < 0 {
                    IndeterminateSweep(height: height)
                } else {
                    Capsule()
                        .fill(LinearGradient(colors: [Color(hex: 0xFF8650), Color(hex: 0xF0581B)],
                                             startPoint: .top, endPoint: .bottom))
                        .overlay(alignment: .top) {
                            Capsule().fill(Color.white.opacity(0.3)).frame(height: 1).padding(.horizontal, height / 2)
                        }
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

    var body: some View {
        TimelineView(.animation) { tl in
            GeometryReader { geo in
                let t = tl.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6
                let w = geo.size.width * 0.28
                Capsule()
                    .fill(Palette.signal.opacity(0.85))
                    .frame(width: w, height: height)
                    .offset(x: -w + (geo.size.width + w) * t)
            }
        }
    }
}

// MARK: - Tabs

/// Navigation between a few views (Settings): a groove with one embossed
/// plate that slides. Choices that set a value use the instruments in
/// Instruments.swift instead.
struct ChoiceBar<Value: Hashable>: View {
    let options: [(Value, String)]
    @Binding var selection: Value
    @Namespace private var plate

    var body: some View {
        HStack(spacing: 0) {
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
                                    .fill(LinearGradient(colors: [Color(hex: 0x34382F), Color(hex: 0x2C2F28)],
                                                         startPoint: .top, endPoint: .bottom))
                                    .overlay {
                                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                                            .strokeBorder(LinearGradient(stops: [.init(color: .white.opacity(0.1), location: 0),
                                                                                 .init(color: .clear, location: 0.3)],
                                                                         startPoint: .top, endPoint: .bottom), lineWidth: 1)
                                    }
                                    .matchedGeometryEffect(id: "plate", in: plate)
                            }
                        }
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .focusEffectDisabled()
            }
        }
        .padding(2)
        .sunk(radius: Metrics.controlRadius)
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
            .sunk(radius: Metrics.controlRadius)
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
