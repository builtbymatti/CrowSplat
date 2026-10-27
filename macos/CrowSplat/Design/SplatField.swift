import SwiftUI

/// The signature: the crow, rendered the way CrowSplat renders everything,
/// as soft Gaussian splats. They start as a loose cloud, settle into the
/// silhouette, keep breathing, and part around the pointer.
///
/// Purely decorative: every word and control sits outside it, so nothing
/// depends on this animation running.
struct SplatField: View {
    /// 0 = scattered cloud, 1 = the crow. Animate it from the outside.
    var formation: Double = 1
    var count: Int = 1300
    var splatScale: CGFloat = 1

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pointer: CGPoint?

    private var splats: [Splat] { Splat.cached(count: count) }

    var body: some View {
        TimelineView(.animation(paused: reduceMotion)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            Canvas(rendersAsynchronously: true) { ctx, size in
                guard let sprite = ctx.resolveSymbol(id: 0) else { return }
                let frame = crowFrame(in: size)
                let form = reduceMotion ? 1 : formation
                for s in splats {
                    var p = mix(s.scatter(in: size), s.target(in: frame), ease(form, s.delay))
                    // Breathing: each splat drifts on its own slow orbit.
                    let breathe = reduceMotion ? 0 : 1.2 * splatScale
                    p.x += CGFloat(sin(t * s.speed + s.phase)) * breathe
                    p.y += CGFloat(cos(t * s.speed * 0.8 + s.phase)) * breathe
                    if let pointer, !reduceMotion {
                        let dx = p.x - pointer.x, dy = p.y - pointer.y
                        let d2 = dx * dx + dy * dy
                        let reach: CGFloat = 70 * 70
                        if d2 < reach {
                            let push = (1 - d2 / reach) * 16
                            let d = max(sqrt(d2), 0.001)
                            p.x += dx / d * push; p.y += dy / d * push
                        }
                    }
                    var layer = ctx
                    layer.opacity = s.alpha * (0.35 + 0.65 * form)
                    layer.translateBy(x: p.x, y: p.y)
                    layer.rotate(by: .radians(s.angle))
                    layer.scaleBy(x: s.size.width * splatScale, y: s.size.height * splatScale)
                    layer.draw(sprite, at: .zero)
                }
            } symbols: {
                // One soft Gaussian sprite, 20 pt across, drawn hundreds of times.
                Circle()
                    .fill(RadialGradient(colors: [Palette.ink, Palette.ink.opacity(0.55), .clear],
                                         center: .center, startRadius: 0, endRadius: 10))
                    .frame(width: 20, height: 20)
                    .tag(0)
            }
        }
        .onContinuousHover { phase in
            switch phase {
            case .active(let p): pointer = p
            case .ended: pointer = nil
            }
        }
        .accessibilityHidden(true)
    }

    private func crowFrame(in size: CGSize) -> CGRect {
        let aspect = CrowGeometry.aspect
        let h = min(size.height * 0.82, size.width * 0.82 / aspect)
        let w = h * aspect
        return CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
    }

    private func ease(_ form: Double, _ delay: Double) -> CGFloat {
        // Staggered: each splat starts its flight a little later than the last.
        let local = min(1, max(0, (form - delay * 0.35) / 0.65))
        return CGFloat(1 - pow(1 - local, 3))
    }

    private func mix(_ a: CGPoint, _ b: CGPoint, _ t: CGFloat) -> CGPoint {
        CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t)
    }
}

private struct Splat {
    var unit: CGPoint          // position inside the crow, 0-1
    var scatterUnit: CGPoint   // position in the loose cloud, -0.2...1.2
    var size: CGSize           // scale of the 20 pt sprite
    var angle: Double
    var alpha: Double
    var speed: Double
    var phase: Double
    var delay: Double

    func target(in frame: CGRect) -> CGPoint {
        CGPoint(x: frame.minX + unit.x * frame.width, y: frame.minY + unit.y * frame.height)
    }

    func scatter(in size: CGSize) -> CGPoint {
        CGPoint(x: scatterUnit.x * size.width, y: scatterUnit.y * size.height)
    }

    /// Sampling the silhouette costs a few ms; do it once per size, not per frame.
    private static var cache: [Int: [Splat]] = [:]
    static func cached(count: Int) -> [Splat] {
        if let hit = cache[count] { return hit }
        let made = make(count: count)
        cache[count] = made
        return made
    }

    /// A loose, soft-edged cloud around the centre (Gaussian falloff), not
    /// a uniform box: scattered splats should read as haze, not a rectangle.
    static func cloudPoint(_ rng: inout SeededRandom) -> CGPoint {
        // Box-Muller from two uniforms.
        let u1 = max(rng.next(), 1e-6), u2 = rng.next()
        let r = sqrt(-2 * log(u1)) * 0.2
        let a = 2 * CGFloat.pi * u2
        return CGPoint(x: 0.5 + r * cos(a) * 1.25, y: 0.5 + r * sin(a))
    }

    static func make(count: Int) -> [Splat] {
        var rng = SeededRandom(seed: 42)
        return CrowGeometry.samplePoints(count: count).map { unit in
            // Anisotropic like real splats: stretched, rotated, mostly small,
            // with a few broad faint ones that give the body its volume.
            let broad = rng.next() < 0.14
            let base = broad ? 0.9 + rng.next() * 0.8 : 0.12 + pow(rng.next(), 2.2) * 0.55
            let stretch = 0.55 + rng.next() * 0.9
            return Splat(
                unit: unit,
                scatterUnit: Self.cloudPoint(&rng),
                size: CGSize(width: base * stretch, height: base / stretch),
                angle: Double(rng.next()) * .pi,
                alpha: broad ? 0.07 + Double(rng.next()) * 0.1 : 0.35 + Double(rng.next()) * 0.6,
                speed: 0.25 + Double(rng.next()) * 0.6,
                phase: Double(rng.next()) * .pi * 2,
                delay: Double(rng.next())
            )
        }
    }
}
