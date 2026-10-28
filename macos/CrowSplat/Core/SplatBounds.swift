import Foundation
import simd

/// Where a splat actually is, ignoring its floaters.
///
/// The viewer's own "frame scene" fits the full bounding box, so a single
/// stray splat far outside the room pushes the camera far away. This reads
/// positions straight from a binary PLY (memory-mapped, a sample of at most
/// ~40k vertices), takes the median as the centre and the 85th percentile
/// distance as the radius, and places an orbit camera that fills the view
/// with the bulk of the scene.
struct SplatFraming {
    let target: SIMD3<Float>
    let position: SIMD3<Float>

    static func compute(for url: URL) -> SplatFraming? {
        guard url.pathExtension.lowercased() == "ply",
              let data = try? Data(contentsOf: url, options: .alwaysMapped),
              let header = PLYHeader(data) else { return nil }

        let step = max(1, header.count / 40_000)
        var xs: [Float] = [], ys: [Float] = [], zs: [Float] = []
        xs.reserveCapacity(header.count / step + 1)
        ys.reserveCapacity(header.count / step + 1)
        zs.reserveCapacity(header.count / step + 1)
        data.withUnsafeBytes { raw in
            var i = 0
            while i < header.count {
                let base = header.dataOffset + i * header.stride
                guard base + header.stride <= raw.count else { break }
                let x = raw.loadUnaligned(fromByteOffset: base + header.x, as: Float.self)
                let y = raw.loadUnaligned(fromByteOffset: base + header.y, as: Float.self)
                let z = raw.loadUnaligned(fromByteOffset: base + header.z, as: Float.self)
                if x.isFinite && y.isFinite && z.isFinite {
                    // The viewer turns PLY splats 180° about Z: (x, y, z) -> (-x, -y, z).
                    xs.append(-x); ys.append(-y); zs.append(z)
                }
                i += step
            }
        }
        guard xs.count > 16 else { return nil }

        let center = SIMD3(median(xs), median(ys), median(zs))
        var distances = zip(xs, zip(ys, zs)).map { simd_distance(SIMD3($0, $1.0, $1.1), center) }
        distances.sort()
        let radius = max(distances[Int(Float(distances.count - 1) * 0.85)], 0.05)

        // Slightly above and in front, close enough that the bulk fills a 60° view.
        let direction = simd_normalize(SIMD3<Float>(0, 0.35, 1))
        return SplatFraming(target: center, position: center + direction * radius * 1.6)
    }

    private static func median(_ values: [Float]) -> Float {
        let sorted = values.sorted()
        return sorted[sorted.count / 2]
    }
}

/// Just enough of a PLY header to find x, y, z in each vertex record.
private struct PLYHeader {
    let count: Int
    let stride: Int
    let x: Int, y: Int, z: Int
    let dataOffset: Int

    init?(_ data: Data) {
        let marker = Data("end_header\n".utf8)
        guard let end = data.range(of: marker, in: 0..<min(data.count, 64 * 1024)),
              let text = String(data: data[0..<end.lowerBound], encoding: .ascii),
              text.contains("binary_little_endian") else { return nil }

        let sizes = ["char": 1, "uchar": 1, "int8": 1, "uint8": 1, "short": 2, "ushort": 2,
                     "int16": 2, "uint16": 2, "int": 4, "uint": 4, "int32": 4, "uint32": 4,
                     "float": 4, "float32": 4, "double": 8, "float64": 8]
        var count = 0, offset = 0, inVertex = false
        var fields: [String: Int] = [:]
        for line in text.split(separator: "\n") {
            let parts = line.split(separator: " ").map(String.init)
            if parts.first == "element" {
                inVertex = parts.count >= 3 && parts[1] == "vertex"
                if inVertex { count = Int(parts[2]) ?? 0 }
            } else if parts.first == "property", inVertex, parts.count >= 3, let size = sizes[parts[1]] {
                if parts[1].hasPrefix("float") || parts[1] == "float" { fields[parts[2]] = offset }
                offset += size
            }
        }
        guard count > 0, let x = fields["x"], let y = fields["y"], let z = fields["z"] else { return nil }
        self.count = count
        self.stride = offset
        self.x = x; self.y = y; self.z = z
        self.dataOffset = end.upperBound
    }
}
