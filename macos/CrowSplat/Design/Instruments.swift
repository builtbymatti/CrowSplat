import AppKit
import SwiftUI

// Controls drawn as parts of an instrument rather than form widgets. Each
// one shows the consequence of its value next to it, so a choice is never
// just a word in a pill.

// MARK: - Detail scale

/// An ordered choice (Draft · Standard · Fine, Light · Medium · Strong) as a
/// scale with detents: fine ticks, a taller tick at each stop, and an
/// embossed slider that follows the pointer while dragged and settles into
/// the nearest detent when let go. Click a stop, drag, or use the arrow keys.
struct DetentScale<Value: Hashable>: View {
    struct Stop {
        let value: Value
        let title: String
        let readout: String   // what this stop means, shown on the right
    }

    let stops: [Stop]
    @Binding var selection: Value
    @State private var dragX: CGFloat?
    @FocusState private var focused: Bool

    private let lug: CGFloat = 18
    private let inset: CGFloat = 12

    private var index: Int { stops.firstIndex { $0.value == selection } ?? 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            GeometryReader { geo in
                let span = geo.size.width - inset * 2
                let step = span / CGFloat(max(stops.count - 1, 1))
                let x = dragX ?? (inset + step * CGFloat(index))
                ZStack(alignment: .topLeading) {
                    Ticks(count: (stops.count - 1) * 8 + 1, detentEvery: 8, inset: inset)
                        .frame(height: 24)
                        .offset(y: 4)
                    // The lug: an embossed slider with one fine centre line.
                    RoundedRectangle(cornerRadius: 4, style: .continuous)
                        .fill(LinearGradient(colors: [Color(hex: 0xCDD1C8), Color(hex: 0xA9ADA4)],
                                             startPoint: .top, endPoint: .bottom))
                        .overlay {
                            RoundedRectangle(cornerRadius: 4, style: .continuous)
                                .strokeBorder(LinearGradient(colors: [.white.opacity(0.5), .clear, .black.opacity(0.2)],
                                                             startPoint: .top, endPoint: .bottom), lineWidth: 1)
                        }
                        .overlay { Rectangle().fill(Color(hex: 0x141612).opacity(0.55)).frame(width: 1, height: 14) }
                        .background { RoundedRectangle(cornerRadius: 4, style: .continuous).fill(Palette.rim).offset(y: 1) }
                        .frame(width: lug, height: 30)
                        .offset(x: x - lug / 2, y: 1)
                        .animation(dragX == nil ? Motion.snappy : nil, value: x)
                }
                .frame(height: 32)
                .contentShape(.rect)
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        dragX = min(max(g.location.x, inset), inset + span)
                        NSCursor.closedHand.set()
                    }
                    .onEnded { g in
                        let i = Int(((g.location.x - inset) / step).rounded())
                        select(min(max(i, 0), stops.count - 1))
                        dragX = nil
                        NSCursor.openHand.set()
                    })
                .onHover { inside in (inside ? NSCursor.openHand : NSCursor.arrow).set() }
            }
            .frame(height: 32)

            // Stop names under their detents; the chosen one in ink.
            // First and last labels sit flush with the track's ends, the rest
            // centre on their tick.
            GeometryReader { geo in
                let span = geo.size.width - inset * 2
                let step = span / CGFloat(max(stops.count - 1, 1))
                ZStack(alignment: .topLeading) {
                    ForEach(Array(stops.enumerated()), id: \.offset) { i, stop in
                        let label = Button { select(i) } label: {
                            Text(stop.title)
                                .font(.crowLabel)
                                .foregroundStyle(i == index ? Palette.ink : Palette.ink3)
                                .fixedSize()
                                .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        .focusable(false)
                        if i == 0 {
                            label.frame(maxWidth: .infinity, alignment: .leading)
                        } else if i == stops.count - 1 {
                            label.frame(maxWidth: .infinity, alignment: .trailing)
                        } else {
                            label.position(x: inset + step * CGFloat(i), y: 8)
                        }
                    }
                }
            }
            .frame(height: 16)

            Text(stops[index].readout)
                .font(.crowCaption)
                .foregroundStyle(Palette.ink2)
                .contentTransition(.opacity)
                .animation(Motion.smooth, value: index)
        }
        // Keyboard focus only: click-to-focus would swallow the clicks and drags inside.
        .focusable(interactions: .activate)
        .focused($focused)
        .focusEffectDisabled()
        .overlay {
            if focused {
                RoundedRectangle(cornerRadius: 6).strokeBorder(Palette.signal.opacity(0.7), lineWidth: 1)
                    .padding(-6)
                    .allowsHitTesting(false)
            }
        }
        .onKeyPress(.leftArrow) { select(max(index - 1, 0)); return .handled }
        .onKeyPress(.rightArrow) { select(min(index + 1, stops.count - 1)); return .handled }
        .accessibilityElement()
        .accessibilityValue(stops[index].title)
        .accessibilityAdjustableAction { direction in
            select(direction == .increment ? min(index + 1, stops.count - 1) : max(index - 1, 0))
        }
    }

    private func select(_ i: Int) {
        guard stops.indices.contains(i) else { return }
        if stops[i].value != selection {
            NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .default)
        }
        withAnimation(Motion.snappy) { selection = stops[i].value }
    }
}

/// The ruler under the detent scale: hairline ticks, taller at each detent.
private struct Ticks: View {
    let count: Int
    let detentEvery: Int
    let inset: CGFloat

    var body: some View {
        Canvas { ctx, size in
            let span = size.width - inset * 2
            for i in 0..<count {
                let x = inset + span * CGFloat(i) / CGFloat(max(count - 1, 1))
                let detent = i % detentEvery == 0
                let h: CGFloat = detent ? 16 : 7
                let rect = CGRect(x: x - 0.5, y: (size.height - h) / 2, width: 1, height: h)
                ctx.fill(Path(roundedRect: rect, cornerRadius: 0.5),
                         with: .color(detent ? Palette.ink3 : Palette.ink4))
            }
        }
        .accessibilityHidden(true)
    }
}

// MARK: - Scrub value

/// A number you drag: grab it and move sideways to step through the allowed
/// values (like a value field in audio or 3D software), or use the arrows on
/// either side. The consequence sits beside it.
struct ScrubValue: View {
    let values: [Int]
    @Binding var value: Int
    let unit: String
    let readout: String
    @State private var dragStart: (x: CGFloat, index: Int)?
    @State private var hovering = false
    @FocusState private var focused: Bool

    private var index: Int { values.firstIndex(of: value) ?? 0 }

    var body: some View {
        HStack(spacing: 14) {
            HStack(spacing: 2) {
                stepper(.chevronLeft, enabled: index > 0) { step(-1) }
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text("\(value)")
                        .font(Typeface.sans(26).monospacedDigit())
                        .foregroundStyle(Palette.ink)
                        .contentTransition(.numericText(value: Double(value)))
                    Text(unit).font(.crowLabel).foregroundStyle(Palette.ink3)
                }
                .frame(minWidth: 70)
                .padding(.vertical, 4)
                .contentShape(.rect)
                .gesture(DragGesture(minimumDistance: 2)
                    .onChanged { g in
                        let start = dragStart ?? (g.startLocation.x, index)
                        dragStart = start
                        // One value per 22 pt of travel.
                        let i = start.index + Int((g.location.x - start.x) / 22)
                        let clamped = min(max(i, 0), values.count - 1)
                        if values[clamped] != value {
                            NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .default)
                            withAnimation(Motion.snappy) { value = values[clamped] }
                        }
                    }
                    .onEnded { _ in dragStart = nil })
                .onHover { inside in
                    hovering = inside
                    (inside ? NSCursor.resizeLeftRight : NSCursor.arrow).set()
                }
                stepper(.chevronRight, enabled: index < values.count - 1) { step(1) }
            }
            .padding(.horizontal, 4)
            .sunk(radius: Metrics.controlRadius)
            .overlay {
                if focused {
                    RoundedRectangle(cornerRadius: Metrics.controlRadius).strokeBorder(Palette.signal.opacity(0.7), lineWidth: 1)
                }
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(readout).font(.crowCaption).foregroundStyle(Palette.ink2)
                Text(hovering ? "Drag the number to change it" : " ")
                    .font(.crowCaption).foregroundStyle(Palette.ink3)
                    .animation(Motion.hover, value: hovering)
            }
        }
        // Keyboard focus only: click-to-focus would swallow the clicks and drags inside.
        .focusable(interactions: .activate)
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.leftArrow) { step(-1); return .handled }
        .onKeyPress(.rightArrow) { step(1); return .handled }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(unit)
        .accessibilityValue("\(value)")
        .accessibilityAdjustableAction { step($0 == .increment ? 1 : -1) }
    }

    private func step(_ delta: Int) {
        let i = min(max(index + delta, 0), values.count - 1)
        withAnimation(Motion.snappy) { value = values[i] }
    }

    private func stepper(_ glyph: Glyph, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) { Icon(glyph, size: 11) }
            .buttonStyle(QuietButtonStyle(tone: Palette.ink3))
            .focusable(false)
            .disabled(!enabled)
    }
}

// MARK: - LED toggle

/// An on/off setting as a whole row: an indicator lamp, a title and what it
/// does. Off, the lamp is a dark recess; on, it lights signal orange (a flat,
/// lit lens, no glow). The row is the switch.
struct CheckRow: View {
    let title: String
    var detail: String? = nil
    @Binding var isOn: Bool
    @State private var hovering = false

    var body: some View {
        Button {
            withAnimation(Motion.snappy) { isOn.toggle() }
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 11) {
                Lamp(on: isOn)
                    .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.crowBody).foregroundStyle(isOn ? Palette.ink : Palette.ink2)
                    if let detail {
                        Text(detail).font(.crowCaption).foregroundStyle(Palette.ink3)
                    }
                }
                Spacer(minLength: 0)
                Text(isOn ? "On" : "Off")
                    .font(.crowCaption)
                    .foregroundStyle(isOn ? Palette.ink2 : Palette.ink4)
                    .contentTransition(.opacity)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(hovering ? Palette.lifted.opacity(0.6) : .clear,
                        in: .rect(cornerRadius: Metrics.controlRadius, style: .continuous))
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, -10)
        .onHover { hovering = $0 }
        .animation(Motion.hover, value: hovering)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isToggle)
        .accessibilityValue(isOn ? "On" : "Off")
    }
}

private struct Lamp: View {
    let on: Bool

    var body: some View {
        ZStack {
            Circle().fill(Palette.sunk)
                .overlay(Circle().strokeBorder(LinearGradient(colors: [.black.opacity(0.55), Palette.edge],
                                                              startPoint: .top, endPoint: .bottom), lineWidth: 1))
            if on {
                Circle()
                    .fill(RadialGradient(colors: [Color(hex: 0xFFB08A), Palette.signal, Color(hex: 0xD9480F)],
                                         center: UnitPoint(x: 0.4, y: 0.32), startRadius: 0, endRadius: 4.5))
                    .padding(2)
                    .transition(.opacity)
            }
        }
        .frame(width: 11, height: 11)
    }
}
