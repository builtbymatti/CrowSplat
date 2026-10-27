import SwiftUI

struct SceneDetailView: View {
    @Environment(AppModel.self) private var model
    let sceneName: String
    @State private var viewer = ViewerController()
    @State private var viewerHasShown = false

    private var scene: SceneItem? { model.library.scene(named: sceneName) }
    private var run: JobRun? { model.jobs.run(for: sceneName) }
    private var liveRun: JobRun? { run.flatMap { $0.isRunning ? $0 : nil } }

    /// What to show in the viewer: the newest checkpoint while training,
    /// the finished splat after.
    private var splat: URL? {
        // A live run only shows its own passes: older checkpoints on disk are
        // about to be archived and would be a stale preview.
        if let liveRun { return liveRun.latestCheckpoint }
        return scene?.latestSplat
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            stage
                .padding(.horizontal, Metrics.gutter)
            if let liveRun {
                RunPanel(run: liveRun)
                    .padding(.horizontal, Metrics.gutter)
                    .padding(.top, 18)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            } else if let scene, scene.state == .failed || scene.state == .cancelled || scene.state == .running {
                StoppedPanel(scene: scene, run: run)
                    .padding(.horizontal, Metrics.gutter)
                    .padding(.top, 18)
            }
            if model.showsLog, let run {
                LogDrawer(run: run)
                    .padding(.horizontal, Metrics.gutter)
                    .padding(.top, 14)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            Spacer(minLength: Metrics.gutter)
        }
        .animation(Motion.smooth, value: liveRun?.id)
        .animation(Motion.smooth, value: model.showsLog)
        .onChange(of: run?.state) { _, _ in model.library.reload() }
        .onChange(of: viewer.phase) { _, phase in
            if phase == .ready { withAnimation(Motion.gentle) { viewerHasShown = true } }
        }
        .animation(Motion.smooth, value: viewer.phase)
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 12) {
            Button { model.destination = .library } label: { Icon(.chevronLeft, size: 14) }
                .buttonStyle(.quiet)
                .help("Library")
            VStack(alignment: .leading, spacing: 2) {
                Text(sceneName).font(.crowTitle).foregroundStyle(Palette.ink)
                if let scene {
                    Text("\(scene.kindLabel) · \(scene.qualityLabel) · \(Format.relative(scene.created))")
                        .font(.crowCaption).foregroundStyle(Palette.ink3)
                }
            }
            Spacer()
            if run != nil {
                Button { model.showsLog.toggle() } label: { Labeled(model.showsLog ? "Hide log" : "Log", .log) }
                    .buttonStyle(.quiet)
            }
            if let scene {
                Button { NSWorkspace.shared.activateFileViewerSelecting([scene.folder]) } label: {
                    Labeled("Show in Finder", .folder)
                }
                .buttonStyle(.quiet)
                if scene.state == .ready { ExportMenu(scene: scene) }
            }
        }
        .padding(.horizontal, Metrics.gutter)
        .padding(.top, 40)
        .padding(.bottom, 18)
    }

    // MARK: Stage

    private var stage: some View {
        ZStack {
            Palette.surface
            if let splat {
                // Always drawn at full opacity: WebKit stops rendering views it
                // thinks are invisible, and would then never report "loaded".
                ViewerView(splat: splat, controller: viewer)
            }
            // Covers the viewer until its first splat is on screen; later
            // checkpoints swap in under a small notice instead.
            if splat == nil || !viewerHasShown {
                StagePlaceholder(scene: scene, run: liveRun, viewerPhase: splat == nil ? nil : viewer.phase)
                    .background(Palette.surface)
                    .transition(.opacity)
            } else if case .loading = viewer.phase {
                VStack {
                    Text("Loading newer pass")
                        .font(.crowCaption).foregroundStyle(Palette.ink2)
                        .padding(.horizontal, 10).frame(height: 28)
                        .glassPlate()
                        .padding(14)
                    Spacer()
                }
                .transition(.opacity)
            }
            if splat != nil && viewerHasShown {
                VStack {
                    Spacer()
                    HStack {
                        ViewerControls(viewer: viewer)
                        Spacer()
                        if liveRun != nil, let name = splat?.lastPathComponent {
                            Text("Preview · \(name)")
                                .font(.crowData).foregroundStyle(Palette.ink2)
                                .padding(.horizontal, 10).frame(height: 30)
                                .glassPlate()
                        }
                    }
                    .padding(14)
                }
                .transition(.opacity)
            }
        }
        .clipShape(.rect(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Palette.edge, lineWidth: 1)
        }
        .frame(maxHeight: .infinity)
    }
}

/// Before there is a splat to show: the capture's own frame, dimmed, with
/// the crow assembling over it, so the wait has something to look at.
private struct StagePlaceholder: View {
    let scene: SceneItem?
    let run: JobRun?
    let viewerPhase: ViewerController.Phase?

    var body: some View {
        ZStack {
            // The frame fills whatever the stage offers and never asks for
            // more: a fill-mode image sized itself would push the layout out.
            Color.clear.overlay {
                if let thumb = run?.thumbnail ?? scene?.thumbnailURL, let image = NSImage(contentsOf: thumb) {
                    Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
                        .blur(radius: 24).opacity(0.28)
                }
            }
            .clipped()
            VStack(spacing: 14) {
                SplatField(formation: formation, count: 700, splatScale: 0.7)
                    .frame(width: 280, height: 190)
                    .animation(Motion.gentle, value: formation)
                Text(message).font(.crowBody).foregroundStyle(Palette.ink2)
            }
        }
    }

    private var formation: Double {
        if let run { return 0.25 + 0.75 * min(1, run.overall / 50) }
        return 1
    }

    private var message: String {
        if case .loading(let p)? = viewerPhase { return p > 0 ? "Loading splat \(Int(p * 100))%" : "Loading splat" }
        if case .failed(let m)? = viewerPhase { return "The viewer could not open this splat. \(m)" }
        // The run panel already names the step; this says what to expect here.
        if run != nil { return "The splat appears here as soon as training saves its first pass." }
        return "No splat yet"
    }
}

/// Camera controls on a glass plate over the live 3D view.
private struct ViewerControls: View {
    let viewer: ViewerController

    var body: some View {
        HStack(spacing: 2) {
            Button { viewer.frame() } label: { Icon(.scene, size: 15) }
                .buttonStyle(.quiet).help("Frame the scene")
            Button { viewer.reset() } label: { Icon(.reset, size: 15) }
                .buttonStyle(.quiet).help("Reset view")
            Rectangle().fill(Palette.edge).frame(width: 1, height: 16).padding(.horizontal, 4)
            ForEach([("orbit", "Orbit"), ("fly", "Fly")], id: \.0) { mode, title in
                Button(title) { viewer.setMode(mode) }
                    .buttonStyle(QuietButtonStyle(tone: viewer.mode == mode ? Palette.ink : Palette.ink3))
            }
        }
        .padding(3)
        .glassPlate()
    }
}

extension View {
    /// Glass where there is something real behind it (the 3D view): native
    /// Liquid Glass on macOS 26, a dark frosted plate before that.
    @ViewBuilder
    func glassPlate() -> some View {
        if #available(macOS 26.0, *) {
            self.glassEffect(.regular.tint(Palette.canvas.opacity(0.35)),
                             in: .rect(cornerRadius: Metrics.controlRadius + 3, style: .continuous))
        } else {
            self.background(.ultraThinMaterial, in: .rect(cornerRadius: Metrics.controlRadius + 3, style: .continuous))
        }
    }
}

// MARK: - Run panel

/// The job in plain words: what it is doing, how far, how long. The stages
/// read as one sentence, the current one in ink.
private struct RunPanel: View {
    let run: JobRun

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Text(run.stepLabel)
                    .font(Typeface.sans(17, .medium)).foregroundStyle(Palette.ink)
                    .contentTransition(.opacity)
                Text(run.status)
                    .font(.crowData).foregroundStyle(Palette.ink3).lineLimit(1)
                Spacer()
                if run.eta > 0 {
                    Text("\(Format.duration(run.eta)) left").font(.crowCaption).foregroundStyle(Palette.ink2)
                }
                Text(run.progress < 0 ? "" : "\(Int(run.progress))%")
                    .font(Typeface.mono(13, medium: true)).foregroundStyle(Palette.ink)
                    .contentTransition(.numericText(value: run.progress))
                    .frame(minWidth: 40, alignment: .trailing)
            }
            ProgressTrack(value: run.progress, height: 3)
            HStack {
                StageLine(run: run)
                Spacer()
                Button("Cancel") { run.cancel() }
                    .buttonStyle(.quiet)
                    .keyboardShortcut(".", modifiers: .command)
            }
        }
        .padding(18)
        .surface(Palette.surface, radius: 12)
        .animation(Motion.smooth, value: run.progress)
        .animation(Motion.smooth, value: run.stepLabel)
    }
}

private struct StageLine: View {
    let run: JobRun
    private static let names = ["split360": "360° split", "reconstruct": "Cameras", "train": "Training",
                                "clean": "Cleaning", "export": "Export"]

    var body: some View {
        // The bridge only names the current step, so the full list comes from
        // the scene manifest when available, else just the count.
        HStack(spacing: 14) {
            ForEach(0..<run.stepCount, id: \.self) { i in
                Text(label(i))
                    .font(i == run.stepIndex ? Typeface.sans(12, .medium) : .crowCaption)
                    .foregroundStyle(i < run.stepIndex ? Palette.ink2 : (i == run.stepIndex ? Palette.ink : Palette.ink4))
            }
        }
        .animation(Motion.smooth, value: run.stepIndex)
    }

    private func label(_ i: Int) -> String {
        if i == run.stepIndex, let id = run.stepID { return Self.names[id] ?? run.stepLabel }
        return run.stepNames.indices.contains(i) ? (Self.names[run.stepNames[i]] ?? run.stepNames[i]) : "Step \(i + 1)"
    }
}

private struct StoppedPanel: View {
    @Environment(AppModel.self) private var model
    let scene: SceneItem
    let run: JobRun?

    var body: some View {
        HStack(spacing: 12) {
            Icon(scene.state == .failed ? .failed : .clock, size: 16)
                .foregroundStyle(scene.state == .failed ? Palette.failure : Palette.ink3)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.crowHeading).foregroundStyle(Palette.ink)
                if let error = scene.manifest.error, scene.state == .failed {
                    Text(error).font(.crowCaption).foregroundStyle(Palette.ink2).lineLimit(2)
                }
            }
            Spacer()
            if !model.showsLog && run != nil {
                Button("Show log") { model.showsLog = true }.buttonStyle(.quiet)
            }
            Button { rerun() } label: { Labeled("Run again", .reset, iconSize: 13) }
                .buttonStyle(.primary)
                .disabled(model.jobs.active != nil || jobSpec == nil)
        }
        .padding(16)
        .surface(Palette.surface, radius: 12)
    }

    private var title: String {
        switch scene.state {
        case .failed: "This scene stopped"
        case .cancelled: "Cancelled"
        default: "Interrupted before it finished"
        }
    }

    private var jobSpec: [String: Any]? {
        guard let data = try? Data(contentsOf: scene.folder.appending(path: "job.json")) else { return nil }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    private func rerun() {
        guard let job = jobSpec else { return }
        model.jobs.start(kind: "scene", title: scene.name, sceneName: scene.name, job: job)
    }
}

// MARK: - Export

private struct ExportMenu: View {
    @Environment(AppModel.self) private var model
    let scene: SceneItem

    var body: some View {
        Menu {
            ForEach(scene.exports, id: \.format) { item in
                Button("Show \(item.format.uppercased())") {
                    NSWorkspace.shared.activateFileViewerSelecting([item.url])
                }
            }
            if !scene.exports.isEmpty { Divider() }
            ForEach(["sog", "spz", "glb"].filter { f in !scene.exports.contains { $0.format == f } }, id: \.self) { f in
                Button("Export \(f.uppercased())") { export(f) }
                    .disabled(model.jobs.active != nil)
            }
            if let splat = scene.splatURL {
                Divider()
                Button("Show trained PLY") { NSWorkspace.shared.activateFileViewerSelecting([splat]) }
            }
        } label: {
            Labeled("Export", .export)
        }
        .menuStyle(.button)
        .buttonStyle(.primary)
        .fixedSize()
    }

    private func export(_ format: String) {
        guard let splat = scene.splatURL else { return }
        model.jobs.start(kind: "convert", title: "\(scene.name) \(format.uppercased())", sceneName: nil,
                         job: ["input": splat.path, "formats": [format],
                               "output": scene.folder.appending(path: "exports").path])
    }
}

// MARK: - Log

private struct LogDrawer: View {
    let run: JobRun
    @State private var showRaw = false

    var body: some View {
        let lines = run.log.filter { showRaw || !$0.raw }.suffix(600)
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Log").font(.crowLabel).foregroundStyle(Palette.ink2)
                Spacer()
                Toggle("Engine output", isOn: $showRaw).toggleStyle(.checkbox).font(.crowCaption)
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(run.log.map(\.text).joined(separator: "\n"), forType: .string)
                } label: { Labeled("Copy", .copy, iconSize: 12) }
                .buttonStyle(.quiet)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(lines)) { line in
                            Text(line.text)
                                .font(.crowData)
                                .foregroundStyle(line.raw ? Palette.ink3 : Palette.ink2)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(line.id)
                        }
                    }
                    .padding(.horizontal, 2)
                }
                .onChange(of: run.log.count) { _, _ in
                    if let last = lines.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
        .padding(14)
        .frame(height: 200)
        .surface(Palette.surface, radius: 12)
    }
}
