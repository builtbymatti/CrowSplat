import SwiftUI
import UniformTypeIdentifiers
import WebKit

/// Talks to the embedded splat viewer: commands in, load state out.
@Observable
final class ViewerController {
    enum Phase: Equatable { case idle, loading(Double), ready, failed(String) }
    var phase: Phase = .idle
    var mode = "orbit"
    fileprivate weak var webView: WKWebView?

    func frame() { webView?.evaluateJavaScript("window.crow.frame()"); focusKeys() }
    func reset() { webView?.evaluateJavaScript("window.crow.reset()"); focusKeys() }
    func setMode(_ m: String) {
        mode = m
        webView?.evaluateJavaScript("window.crow.mode('\(m)')")
        focusKeys()
    }

    /// Hand the keyboard to the 3D view, so WASD reach the viewer instead of
    /// the SwiftUI button that was just clicked (which answers with a beep).
    func focusKeys() {
        guard let web = webView else { return }
        web.window?.makeFirstResponder(web)
    }
}

/// The PlayCanvas SuperSplat viewer (MIT) with its own UI turned off, in a
/// WKWebView. Pages and splats come through the ``crow://`` scheme, so local
/// files never need a server and large splats stream in chunks.
struct ViewerView: NSViewRepresentable {
    let splat: URL
    let controller: ViewerController

    func makeCoordinator() -> Coordinator { Coordinator(controller: controller) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(CrowSchemeHandler(), forURLScheme: CrowSchemeHandler.scheme)
        config.userContentController.add(context.coordinator, name: "crow")
        let web = CrowWebView(frame: .zero, configuration: config)
        web.setValue(false, forKey: "drawsBackground")   // no white flash before the first frame
        web.underPageBackgroundColor = NSColor(red: 0.047, green: 0.047, blue: 0.043, alpha: 1)
        controller.webView = web
        context.coordinator.loaded = splat
        load(splat, in: web)
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        guard context.coordinator.loaded != splat else { return }
        context.coordinator.loaded = splat
        load(splat, in: web)
    }

    static func dismantleNSView(_ web: WKWebView, coordinator: Coordinator) {
        web.configuration.userContentController.removeScriptMessageHandler(forName: "crow")
    }

    private func load(_ url: URL, in web: WKWebView) {
        controller.phase = .loading(0)
        var components = URLComponents()
        components.scheme = CrowSchemeHandler.scheme
        components.host = "viewer"
        components.path = "/crow-viewer.html"
        let baseItems = [
            URLQueryItem(name: "content", value: CrowSchemeHandler.fileURL(for: url)),
            URLQueryItem(name: "name", value: url.lastPathComponent),
        ]
        // Start on the bulk of the splat, not its full bounding box (floaters
        // would push the camera far out). Computed off the main thread.
        let base = components
        DispatchQueue.global(qos: .userInitiated).async {
            var items = baseItems
            var components = base
            if let f = SplatFraming.compute(for: url) {
                let fmt = { (v: Float) in String(format: "%.4f", v) }
                items.append(URLQueryItem(name: "target", value: [f.target.x, f.target.y, f.target.z].map(fmt).joined(separator: ",")))
                items.append(URLQueryItem(name: "camera", value: [f.position.x, f.position.y, f.position.z].map(fmt).joined(separator: ",")))
            }
            components.queryItems = items
            DispatchQueue.main.async {
                if let page = components.url { web.load(URLRequest(url: page)) }
            }
        }
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        let controller: ViewerController
        var loaded: URL?
        init(controller: ViewerController) { self.controller = controller }

        func userContentController(_ uc: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            DispatchQueue.main.async {
                switch type {
                case "progress": self.controller.phase = .loading((body["value"] as? Double ?? 0) / 100)
                case "loaded":
                    self.controller.phase = .ready
                    self.controller.focusKeys()
                // The viewer also reports "default" and "anim"; for our two buttons
                // everything that is not flying is orbiting.
                case "mode": self.controller.mode = (body["value"] as? String) == "fly" ? "fly" : "orbit"
                case "error": self.controller.phase = .failed(body["message"] as? String ?? "The viewer stopped.")
                default: break
                }
            }
        }
    }
}

/// A web view that takes the keyboard when clicked and handles the movement
/// keys itself: W A S D and the arrows are tracked as held or released here
/// and sent to the viewer as one movement vector, so every press and release
/// lands, and none of them reaches the page (or beeps).
final class CrowWebView: WKWebView {
    private var held = Set<UInt16>()

    // Key codes: W A S D and the arrow keys.
    private static let forward: Set<UInt16> = [13, 126]
    private static let back: Set<UInt16> = [1, 125]
    private static let left: Set<UInt16> = [0, 123]
    private static let right: Set<UInt16> = [2, 124]
    private static let movement = forward.union(back).union(left).union(right)

    override var acceptsFirstResponder: Bool { true }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        super.mouseDown(with: event)
    }

    override func keyDown(with event: NSEvent) {
        guard Self.movement.contains(event.keyCode), event.modifierFlags.intersection([.command, .control, .option]).isEmpty else {
            return super.keyDown(with: event)
        }
        if !event.isARepeat { held.insert(event.keyCode); sendMove() }
    }

    override func keyUp(with event: NSEvent) {
        guard Self.movement.contains(event.keyCode) else { return super.keyUp(with: event) }
        held.remove(event.keyCode)
        sendMove()
    }

    /// Losing focus (a click elsewhere, another window) releases everything,
    /// so the camera never keeps drifting on a key we will not hear go up.
    override func resignFirstResponder() -> Bool {
        if !held.isEmpty { held.removeAll(); sendMove() }
        return super.resignFirstResponder()
    }

    private func sendMove() {
        func any(_ keys: Set<UInt16>) -> Int { held.isDisjoint(with: keys) ? 0 : 1 }
        let x = any(Self.right) - any(Self.left)
        let z = any(Self.forward) - any(Self.back)
        evaluateJavaScript("window.crow.move(\(x), \(z))")
    }
}

/// ``crow://viewer/<file>`` serves the bundled viewer;
/// ``crow://viewer/file/<absolute path>`` serves a splat from disk, streamed.
final class CrowSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "crow"
    private var stopped = Set<ObjectIdentifier>()
    private let lock = NSLock()

    static func fileURL(for url: URL) -> String {
        let encoded = url.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? url.path
        return "\(scheme)://viewer/file\(encoded)"
    }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return }
        let path = url.path.removingPercentEncoding ?? url.path
        let fileURL: URL
        if path.hasPrefix("/file/") {
            fileURL = URL(fileURLWithPath: String(path.dropFirst("/file".count)))
        } else {
            guard let viewerDir = Bundle.main.resourceURL?.appending(path: "Viewer") else { return }
            fileURL = viewerDir.appending(path: String(path.drop(while: { $0 == "/" })))
        }
        let id = ObjectIdentifier(task)
        DispatchQueue.global(qos: .userInitiated).async {
            guard let handle = try? FileHandle(forReadingFrom: fileURL) else {
                task.didFailWithError(URLError(.fileDoesNotExist))
                return
            }
            defer { try? handle.close() }
            let size = (try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            let mime = UTType(filenameExtension: fileURL.pathExtension)?.preferredMIMEType
                ?? (fileURL.pathExtension == "wasm" ? "application/wasm" : "application/octet-stream")
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                           headerFields: ["Content-Type": mime, "Content-Length": "\(size)",
                                                          "Access-Control-Allow-Origin": "*"])!
            task.didReceive(response)
            while true {
                if self.isStopped(id) { return }
                let chunk = handle.readData(ofLength: 4 << 20)
                if chunk.isEmpty { break }
                task.didReceive(chunk)
            }
            if !self.isStopped(id) { task.didFinish() }
        }
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {
        lock.lock(); stopped.insert(ObjectIdentifier(task)); lock.unlock()
    }

    private func isStopped(_ id: ObjectIdentifier) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return stopped.contains(id)
    }
}
