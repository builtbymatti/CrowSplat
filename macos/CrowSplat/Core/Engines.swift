import Foundation
import Observation

struct EngineStatus: Identifiable, Hashable {
    let id: String
    let role: String        // core, export, optional
    let purpose: String
    var installed: Bool
    var version: String
    var installable: Bool
    var via: String

    var title: String {
        switch id {
        case "colmap": "COLMAP"
        case "brush": "Brush"
        case "splat-transform": "SplatTransform"
        case "sharp": "ML Sharp"
        case "upscayl": "Upscayl"
        case "extractor_360": "360° Extractor"
        case "four_dgs": "4DGS prep"
        default: id
        }
    }

    var isCore: Bool { role == "core" }
}

/// Engine status from ``app.bridge probe``, plus installs streamed live.
@Observable
final class EngineStore {
    private(set) var engines: [EngineStatus] = []
    private(set) var machine: [String: String] = [:]
    private(set) var probing = false
    private(set) var probed = false
    var homebrew: Bool = true

    /// Engine id → live install state.
    private(set) var installing: [String: InstallState] = [:]

    struct InstallState: Equatable {
        var line: String = ""
        var failed: String?
    }

    var coreReady: Bool { probed && engines.filter(\.isCore).allSatisfy(\.installed) }

    func engine(_ id: String) -> EngineStatus? { engines.first { $0.id == id } }

    @MainActor
    func probe() async {
        probing = true
        defer { probing = false }
        for await ev in BridgeProcess(arguments: ["probe"]).events where ev.type == "done" {
            guard let r = ev.result else { continue }
            engines = r["engines"]?.array.compactMap { e in
                guard let id = e["id"]?.string else { return nil }
                return EngineStatus(id: id, role: e["role"]?.string ?? "optional",
                                    purpose: e["purpose"]?.string ?? "",
                                    installed: e["installed"]?.bool ?? false,
                                    version: e["version"]?.string ?? "",
                                    installable: e["installable"]?.bool ?? true,
                                    via: e["via"]?.string ?? "download")
            } ?? []
            if let m = r["machine"] {
                machine["chip"] = m["chip"]?.string
                machine["macos"] = m["macos"]?.string
                if let gb = m["memory_gb"]?.double { machine["memory"] = "\(Int(gb)) GB" }
            }
            homebrew = r["tools"]?["homebrew"]?.string != nil
            probed = true
        }
    }

    @MainActor
    func install(_ id: String) async {
        installing[id] = InstallState(line: "Starting")
        var failure: String?
        for await ev in BridgeProcess(arguments: ["install", id]).events {
            switch ev.type {
            case "status": installing[id]?.line = ev.text ?? ""
            case "log" where ev.level == "raw":
                if let t = ev.text?.trimmingCharacters(in: .whitespaces), !t.isEmpty {
                    installing[id]?.line = String(t.prefix(90))
                }
            case "done": if ev.ok != true { failure = ev.message ?? "Install failed" }
            default: break
            }
        }
        if let failure {
            installing[id] = InstallState(line: "", failed: failure)
        } else {
            installing[id] = nil
        }
        await probe()
    }
}
