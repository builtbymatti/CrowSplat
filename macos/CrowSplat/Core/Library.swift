import AppKit
import Foundation
import Observation

/// ``scene.json``, written by the core for every scene folder.
struct SceneManifest: Decodable, Hashable {
    var name: String
    var source: String?
    var kind: String?
    var quality: String?
    var status: String?
    var created: Double?
    var updated: Double?
    var step: String?
    var steps: [String]?
    var outputs: [String: String]?
    var splat: String?
    var thumbnail: String?
    var error: String?
}

struct SceneItem: Identifiable, Hashable {
    let folder: URL
    var manifest: SceneManifest

    var id: String { folder.path }
    var name: String { manifest.name }

    enum State: String { case running, ready, failed, cancelled, unknown }
    var state: State { State(rawValue: manifest.status ?? "") ?? .unknown }

    var thumbnailURL: URL? { manifest.thumbnail.map { folder.appending(path: $0) } }
    var splatURL: URL? { manifest.splat.map { URL(fileURLWithPath: $0) } }
    var created: Date { Date(timeIntervalSince1970: manifest.created ?? 0) }

    var kindLabel: String {
        switch manifest.kind {
        case "video": "Video"
        case "images": "Photos"
        default: "Scene"
        }
    }

    var qualityLabel: String { (manifest.quality ?? "standard").capitalized }

    /// The newest splat on disk: the finished one, else the latest checkpoint.
    var latestSplat: URL? {
        if let splat = splatURL, FileManager.default.fileExists(atPath: splat.path) { return splat }
        let checkpoints = folder.appending(path: "checkpoints")
        let plys = (try? FileManager.default.contentsOfDirectory(
            at: checkpoints, includingPropertiesForKeys: [.contentModificationDateKey]))?
            .filter { $0.pathExtension == "ply" } ?? []
        return plys.max {
            let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return a < b
        }
    }

    var exports: [(format: String, url: URL)] {
        (manifest.outputs ?? [:])
            .filter { ["sog", "spz", "glb", "ply"].contains($0.key) }
            .map { ($0.key, URL(fileURLWithPath: $0.value)) }
            .sorted { $0.format < $1.format }
    }
}

/// The scenes in the library folder, newest first.
@Observable
final class LibraryStore {
    static let defaultsKey = "libraryFolder"

    var folder: URL {
        didSet { UserDefaults.standard.set(folder.path, forKey: Self.defaultsKey); reload() }
    }
    private(set) var scenes: [SceneItem] = []

    init() {
        let saved = UserDefaults.standard.string(forKey: Self.defaultsKey)
        folder = saved.map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser.appending(path: "CrowSplat")
        reload()
    }

    func reload() {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let decoder = JSONDecoder()
        let dirs = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        scenes = dirs.compactMap { dir in
            guard let data = try? Data(contentsOf: dir.appending(path: "scene.json")),
                  let manifest = try? decoder.decode(SceneManifest.self, from: data) else { return nil }
            return SceneItem(folder: dir, manifest: manifest)
        }
        .sorted { $0.created > $1.created }
    }

    func scene(named name: String) -> SceneItem? { scenes.first { $0.name == name } }

    /// A folder name that does not clash with an existing scene.
    func uniqueName(_ base: String) -> String {
        let clean = base.replacingOccurrences(of: "/", with: "-").trimmingCharacters(in: .whitespaces)
        let stem = clean.isEmpty ? "Untitled" : clean
        var name = stem, n = 2
        while FileManager.default.fileExists(atPath: folder.appending(path: name).path) {
            name = "\(stem) \(n)"; n += 1
        }
        return name
    }

    func moveToTrash(_ scene: SceneItem) {
        NSWorkspace.shared.recycle([scene.folder]) { _, _ in
            DispatchQueue.main.async { self.reload() }
        }
    }
}
