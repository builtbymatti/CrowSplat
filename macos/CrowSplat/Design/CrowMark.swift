import SwiftUI

/// The crow, as geometry. Parsed once from the logo's SVG path so it scales
/// crisply, can be filled, stroked, masked, and sampled for the splat field.
struct CrowShape: Shape {
    func path(in rect: CGRect) -> Path {
        let base = CrowGeometry.path
        let bounds = CrowGeometry.bounds
        let scale = min(rect.width / bounds.width, rect.height / bounds.height)
        let w = bounds.width * scale, h = bounds.height * scale
        let transform = CGAffineTransform(translationX: rect.minX + (rect.width - w) / 2,
                                          y: rect.minY + (rect.height - h) / 2)
            .scaledBy(x: scale, y: scale)
            .translatedBy(x: -bounds.minX, y: -bounds.minY)
        return base.applying(transform)
    }
}

/// The logo mark at a given height, in the current foreground colour.
struct CrowMark: View {
    var height: CGFloat = 18

    var body: some View {
        CrowShape()
            .frame(width: height * CrowGeometry.aspect, height: height)
            .accessibilityLabel("CrowSplat")
    }
}

enum CrowGeometry {
    /// The crow outline from the brand SVG (56-unit artboard).
    static let svg = "m40.99 14.1c-0.6247-0.3969-1.264-1.147-3.065-1.147-1.529 0-2.83 0.757-3.697 1.852-0.8967 1.117-1.499 2.528-2.271 3.624-0.5806 0.8232-1.367 1.272-2.205 1.749-1.529 0.8673-2.727 1.705-4.175 3.072-3.352 3.234-7.49 7.115-9.695 9.165-0.5439 0.5072-0.8452 0.882-0.8159 0.9776 0.08085 0.1984 3.161-1.066 4.41-1.492-2.212 1.654-6.042 4.292-7.916 6.167-0.4777 0.4704-0.588 0.6247-0.5366 0.7276 0.0588 0.1911 0.566 0.2132 1.161 0.2499 0.7938 0.169 1.808 0.3234 2.506 0.3234l-0.3161 0.4557c0.5586 0.147 1.536-0.3161 2.242-0.8967 1.411-1.161 3.072-2.668 4.484-3.829 1.426-1.176 3.866-2.47 4.653-2.514 0.3234-0.0147 0.4116 0.2058 0.3087 0.4998l-0.7717 1.962c-0.1837 0.4924-0.1617 0.9996 0.0588 1.367 0.8012 1.477 1.602 3.293 2.109 4.579 0.1617 0.4116 0.0441 0.6909-0.3234 0.8232-0.9261 0.3308-1.911 0.6101-1.97 1.213h6.372c-0.0882-0.6909-0.8967-0.8306-1.742-1.095-0.4704-0.1323-0.7203-0.3234-0.904-0.6835-0.6689-1.389-1.47-3.138-1.933-4.248-0.147-0.3454-0.0588-0.6174 0.1764-0.882l1.382-1.477c0.2499-0.2572 0.4337-0.1396 0.4042 0.1985l-0.1543 1.308c-0.0441 0.3822 0.06615 0.7497 0.294 1.036 0.9702 1.235 2.109 2.852 2.742 3.925 0.1911 0.3381 0.1323 0.5954-0.0588 0.7791 0.3601 0.2793 0.5586 0.6688 0.6394 1.139h4.542c-0.0735-0.6248-0.8894-0.8085-1.882-0.9849-0.9482-0.169-1.374-0.2426-1.654-0.6321l-2.661-3.925c-0.2131-0.3234-0.2278-0.6541-0.08085-0.9702l1.338-2.771c0.2058-0.4336 0.5145-0.8379 0.8746-1.139 2.837-2.389 6.666-6.152 6.659-9.805 0-0.7423-0.09555-1.382-0.294-1.845-0.3234-0.9408-0.3014-2.234 0-3.087 0.272-0.8158 1.103-1.301 1.977-1.374l4.013-0.3528c-0.0735-0.441-1.08-1.183-2.183-1.529-0.8526-0.2867-1.61-0.3455-2.043-0.5145z"

    static let path: Path = SVGPathParser.parse(svg)
    static let bounds: CGRect = path.boundingRect
    static var aspect: CGFloat { bounds.width / bounds.height }

    /// Points spread inside the silhouette, in unit space (0-1 on both axes,
    /// aspect kept), for the splat field. Deterministic: same crow every launch.
    static func samplePoints(count: Int, seed: UInt64 = 7) -> [CGPoint] {
        var rng = SeededRandom(seed: seed)
        let b = bounds
        var points: [CGPoint] = []
        var guardCount = 0
        while points.count < count && guardCount < count * 60 {
            guardCount += 1
            let p = CGPoint(x: b.minX + rng.next() * b.width, y: b.minY + rng.next() * b.height)
            if path.contains(p) {
                points.append(CGPoint(x: (p.x - b.minX) / b.width, y: (p.y - b.minY) / b.height))
            }
        }
        return points
    }
}

/// SplitMix64, so the sampled crow is identical on every launch.
struct SeededRandom {
    private var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> CGFloat {
        state &+= 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        z ^= z >> 31
        return CGFloat(z >> 11) / CGFloat(1 << 53)
    }
}

/// Minimal SVG path-data parser: M/L/H/V/C/S/Q/Z, absolute and relative,
/// with implicit repeats. Enough for the brand mark; not a general SVG engine.
enum SVGPathParser {
    static func parse(_ d: String) -> Path {
        var path = Path()
        var tokens = Tokenizer(d)
        var command: Character = "M"
        var current = CGPoint.zero, start = CGPoint.zero, lastControl: CGPoint?

        while let token = tokens.peek() {
            if case .command(let c) = token {
                command = c
                _ = tokens.nextToken()
                if c == "Z" || c == "z" {
                    path.closeSubpath(); current = start; lastControl = nil
                    continue
                }
            }
            let rel = command.isLowercase
            func pt() -> CGPoint? {
                guard let x = tokens.number(), let y = tokens.number() else { return nil }
                return rel ? CGPoint(x: current.x + x, y: current.y + y) : CGPoint(x: x, y: y)
            }
            switch command.uppercased().first! {
            case "M":
                guard let p = pt() else { return path }
                path.move(to: p); current = p; start = p; lastControl = nil
                command = rel ? "l" : "L"  // further pairs are line-tos
            case "L":
                guard let p = pt() else { return path }
                path.addLine(to: p); current = p; lastControl = nil
            case "H":
                guard let x = tokens.number() else { return path }
                current.x = rel ? current.x + x : x; path.addLine(to: current); lastControl = nil
            case "V":
                guard let y = tokens.number() else { return path }
                current.y = rel ? current.y + y : y; path.addLine(to: current); lastControl = nil
            case "C":
                guard let c1 = pt(), let c2 = pt(), let p = pt() else { return path }
                path.addCurve(to: p, control1: c1, control2: c2); current = p; lastControl = c2
            case "S":
                let c1 = lastControl.map { CGPoint(x: 2 * current.x - $0.x, y: 2 * current.y - $0.y) } ?? current
                guard let c2 = pt(), let p = pt() else { return path }
                path.addCurve(to: p, control1: c1, control2: c2); current = p; lastControl = c2
            case "Q":
                guard let c = pt(), let p = pt() else { return path }
                path.addQuadCurve(to: p, control: c); current = p; lastControl = c
            default:
                _ = tokens.nextToken()
            }
        }
        return path
    }

    struct Tokenizer {
        enum Token { case command(Character), number(CGFloat) }
        private let chars: [Character]
        private var i = 0
        init(_ s: String) { chars = Array(s) }

        mutating func skip() {
            while i < chars.count, chars[i] == " " || chars[i] == "," || chars[i] == "\n" { i += 1 }
        }

        mutating func peek() -> Token? {
            skip()
            guard i < chars.count else { return nil }
            let c = chars[i]
            if c.isLetter && c != "e" && c != "E" { return .command(c) }
            let save = i
            defer { i = save }
            return number().map { .number($0) }
        }

        mutating func nextToken() -> Token? {
            skip()
            guard i < chars.count else { return nil }
            let c = chars[i]
            if c.isLetter && c != "e" && c != "E" { i += 1; return .command(c) }
            return number().map { .number($0) }
        }

        mutating func number() -> CGFloat? {
            skip()
            var s = ""
            var seenDot = false, seenExp = false
            while i < chars.count {
                let c = chars[i]
                if c == "-" || c == "+" {
                    if s.isEmpty || s.last == "e" || s.last == "E" { s.append(c); i += 1; continue }
                    break
                }
                if c == "." {
                    if seenDot || seenExp { break }  // "0.5.5" is 0.5 then .5
                    seenDot = true; s.append(c); i += 1; continue
                }
                if c == "e" || c == "E" { seenExp = true; s.append(c); i += 1; continue }
                if c.isNumber { s.append(c); i += 1; continue }
                break
            }
            return Double(s).map { CGFloat($0) }
        }
    }
}
