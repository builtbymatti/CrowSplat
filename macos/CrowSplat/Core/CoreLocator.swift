import Foundation

/// Where the Python core, its interpreter and the writable data live.
///
/// Debug builds run the core straight from the repository (``CrowCoreRoot``
/// in Info.plist, set by the build), with its ``.venv`` and ``engines/``.
/// Release builds carry the core and a standalone CPython inside the bundle,
/// and keep engines, models and settings in Application Support, since a
/// signed bundle is read-only.
struct CoreLocator {
    let coreRoot: URL
    let python: URL
    let dataRoot: URL?   // nil = the core's own folder (debug)

    static let shared = CoreLocator.resolve()

    static func resolve() -> CoreLocator {
        if let dev = Bundle.main.object(forInfoDictionaryKey: "CrowCoreRoot") as? String,
           !dev.isEmpty, FileManager.default.fileExists(atPath: dev + "/app/bridge/__main__.py") {
            let root = URL(fileURLWithPath: dev).standardizedFileURL
            return CoreLocator(coreRoot: root,
                               python: root.appending(path: ".venv/bin/python"),
                               dataRoot: nil)
        }
        let res = Bundle.main.resourceURL!
        return CoreLocator(coreRoot: res.appending(path: "core"),
                           python: res.appending(path: "python/bin/python3"),
                           dataRoot: applicationSupport)
    }

    static var applicationSupport: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appending(path: "CrowSplat")
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    /// GUI apps start with a bare PATH; the core shells out to brew-installed
    /// COLMAP and ffmpeg, so put the usual tool folders back.
    var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        let extra = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"]
        let path = (extra + (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin").split(separator: ":").map(String.init))
        env["PATH"] = NSOrderedSet(array: path).array.compactMap { $0 as? String }.joined(separator: ":")
        env["PYTHONPATH"] = coreRoot.path
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = dataRoot == nil ? nil : "1"
        if let dataRoot { env["CROWSPLAT_DATA_DIR"] = dataRoot.path }
        return env
    }
}
