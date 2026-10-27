import AppKit
import Foundation
import Observation
import UserNotifications

/// One run of a bridge job, as the UI sees it.
@Observable
final class JobRun: Identifiable {
    enum State: Equatable { case running, succeeded, failed(String), cancelled }

    let id = UUID()
    let kind: String            // scene, sharp, clean, convert, upscale, split360, fourdgs
    let title: String           // scene name or tool name
    let sceneName: String?
    let started = Date()

    var state: State = .running
    var stepID: String?
    var stepLabel = "Starting"
    var stepIndex = 0
    var stepCount = 1
    var stepNames: [String] = []
    var progress: Double = -1   // within the step; -1 = indeterminate
    var eta: Double = -1
    var status = ""
    var latestCheckpoint: URL?
    var thumbnail: URL?
    var outputs: [String: String] = [:]
    var resultPath: String?
    private(set) var log: [LogLine] = []

    struct LogLine: Identifiable {
        let id = UUID()
        let text: String
        let raw: Bool
    }

    /// Across all steps, for the Dock and the sidebar.
    var overall: Double {
        let p = max(0, progress)
        return (Double(stepIndex) + p / 100) / Double(max(stepCount, 1)) * 100
    }

    var isRunning: Bool { state == .running }

    fileprivate var process: BridgeProcess?

    init(kind: String, title: String, sceneName: String?) {
        self.kind = kind
        self.title = title
        self.sceneName = sceneName
    }

    func appendLog(_ text: String, raw: Bool) {
        log.append(LogLine(text: text, raw: raw))
        if log.count > 4000 { log.removeFirst(log.count - 4000) }
    }

    func cancel() { process?.cancel() }
}

/// Runs bridge jobs one at a time (they all want the GPU), mirrors progress
/// in the Dock and posts a notification when a long run ends.
@Observable
final class JobCenter {
    private(set) var runs: [JobRun] = []
    var onFinish: ((JobRun) -> Void)?

    var active: JobRun? { runs.last { $0.isRunning } }

    func run(for scene: String) -> JobRun? { runs.last { $0.sceneName == scene } }

    @MainActor
    @discardableResult
    func start(kind: String, title: String, sceneName: String? = nil, job: [String: Any]) -> JobRun? {
        guard active == nil else { return nil }
        let run = JobRun(kind: kind, title: title, sceneName: sceneName)
        let process: BridgeProcess
        do {
            var spec = job
            spec["job"] = kind
            process = try BridgeProcess.job(spec)
        } catch {
            run.state = .failed(error.localizedDescription)
            runs.append(run)
            return run
        }
        run.process = process
        runs.append(run)
        DockProgress.shared.show(0)
        Task { @MainActor in
            for await ev in process.events { self.apply(ev, to: run) }
            if run.isRunning { run.state = .failed("The core stopped unexpectedly. See the log.") }
            DockProgress.shared.hide()
            self.notify(run)
            self.onFinish?(run)
        }
        return run
    }

    @MainActor
    private func apply(_ ev: BridgeEvent, to run: JobRun) {
        switch ev.type {
        case "step":
            run.stepID = ev.id
            run.stepLabel = ev.label ?? run.stepLabel
            run.stepIndex = ev.index ?? run.stepIndex
            run.stepCount = ev.count ?? run.stepCount
            if let names = ev.steps { run.stepNames = names }
            run.progress = -1
            run.eta = -1
            run.status = ""
        case "progress":
            if let v = ev.value { run.progress = v }
            DockProgress.shared.show(run.overall)
        case "eta":
            run.eta = ev.seconds ?? -1
        case "status":
            run.status = ev.text ?? ""
        case "log":
            if let t = ev.text { run.appendLog(t, raw: ev.level == "raw") }
        case "artifact":
            guard let p = ev.path else { break }
            let url = URL(fileURLWithPath: p)
            switch ev.kind {
            case "checkpoint", "splat": run.latestCheckpoint = url
            case "thumbnail": run.thumbnail = url
            default: break
            }
        case "done":
            if ev.ok == true {
                run.state = .succeeded
                run.progress = 100
                if case .object(let o)? = ev.result?["outputs"] {
                    run.outputs = o.compactMapValues(\.string)
                }
                run.resultPath = ev.result?["output"]?.string ?? ev.result?["scene"]?.string
            } else if ev.result?["cancelled"]?.bool == true {
                run.state = .cancelled
            } else {
                run.state = .failed(ev.message ?? "Something went wrong.")
            }
        default:
            break
        }
    }

    private func notify(_ run: JobRun) {
        // Only worth a banner when the user had time to look away.
        guard Date().timeIntervalSince(run.started) > 20, !NSApp.isActive else { return }
        let content = UNMutableNotificationContent()
        switch run.state {
        case .succeeded: content.title = "\(run.title) is ready"; content.body = "Your splat finished training."
        case .failed(let m): content.title = "\(run.title) stopped"; content.body = m
        default: return
        }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            center.add(UNNotificationRequest(identifier: run.id.uuidString, content: content, trigger: nil))
        }
    }
}

/// A thin progress line drawn under the Dock icon while a job runs.
final class DockProgress {
    static let shared = DockProgress()
    private let view = DockTileView()

    func show(_ percent: Double) {
        DispatchQueue.main.async {
            let tile = NSApp.dockTile
            if tile.contentView !== self.view { tile.contentView = self.view }
            self.view.progress = max(0, min(100, percent)) / 100
            tile.display()
        }
    }

    func hide() {
        DispatchQueue.main.async {
            NSApp.dockTile.contentView = nil
            NSApp.dockTile.display()
        }
    }

    private final class DockTileView: NSView {
        var progress: Double = 0

        override func draw(_ dirtyRect: NSRect) {
            NSApp.applicationIconImage.draw(in: bounds)
            let inset = bounds.width * 0.16
            let track = NSRect(x: inset, y: bounds.height * 0.1, width: bounds.width - inset * 2, height: bounds.height * 0.06)
            let r = track.height / 2
            NSColor(white: 0.05, alpha: 0.85).setFill()
            NSBezierPath(roundedRect: track.insetBy(dx: -2, dy: -2), xRadius: r + 2, yRadius: r + 2).fill()
            NSColor(white: 0.93, alpha: 1).setFill()
            var fill = track
            fill.size.width = max(track.height, track.width * progress)
            NSBezierPath(roundedRect: fill, xRadius: r, yRadius: r).fill()
        }
    }
}
