import SwiftUI

@main
struct CrowSplatApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()

    var body: some Scene {
        Window("CrowSplat", id: "main") {
            RootView()
                .environment(model)
                .frame(minWidth: 980, minHeight: 640)
                .preferredColorScheme(.dark)
                .tint(Palette.ink)
        }
        .windowStyle(.hiddenTitleBar)
        .windowToolbarStyle(.unifiedCompact)
        .defaultSize(width: 1240, height: 800)
        .commands { AppCommands(model: model) }

        Settings {
            SettingsView()
                .environment(model)
                .preferredColorScheme(.dark)
                .tint(Palette.ink)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Set by the app so quitting can see the running job.
    static var jobs: JobCenter?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
    }

    /// Quitting mid-training throws the run away, so ask first, then stop
    /// the core cleanly instead of leaving it training on its own.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let run = Self.jobs?.active else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "\(run.title) is still running"
        alert.informativeText = "Quitting stops it. You can run it again later from the scene."
        alert.addButton(withTitle: "Keep running")
        alert.addButton(withTitle: "Stop and quit")
        guard alert.runModal() == .alertSecondButtonReturn else { return .terminateCancel }
        run.cancel()
        // Give the core a moment to stop Brush and write its manifest.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { sender.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

/// App-wide state: the library, engines, running jobs and where we are.
@Observable
final class AppModel {
    let library = LibraryStore()
    let engines = EngineStore()
    let jobs = JobCenter()

    enum Destination: Hashable { case library, tools, scene(String) }
    var destination: Destination = .library
    var pendingImport: [URL]?
    var showsLog = false

    var onboarded: Bool {
        didSet { UserDefaults.standard.set(onboarded, forKey: "onboarded") }
    }

    init() {
        onboarded = UserDefaults.standard.bool(forKey: "onboarded")
        jobs.onFinish = { [weak self] _ in self?.library.reload() }
        AppDelegate.jobs = jobs
    }

    /// Anything dropped or picked: captures open the new-scene sheet,
    /// splat files open straight in the viewer.
    func open(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        pendingImport = urls
    }
}

struct AppCommands: Commands {
    let model: AppModel

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("New Scene…") { NewScenePicker.present(model: model) }
                .keyboardShortcut("n")
        }
        CommandGroup(after: .sidebar) {
            Button("Library") { model.destination = .library }.keyboardShortcut("1")
            Button("Tools") { model.destination = .tools }.keyboardShortcut("2")
            Divider()
            Button(model.showsLog ? "Hide Log" : "Show Log") { model.showsLog.toggle() }
                .keyboardShortcut("l", modifiers: [.command, .option])
        }
    }
}

/// The open panel for captures: one video, or photos / a folder of photos.
enum NewScenePicker {
    @MainActor
    static func present(model: AppModel) {
        let panel = NSOpenPanel()
        panel.title = "Choose a video or photos"
        panel.prompt = "Use"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.movie, .image, .folder]
        if panel.runModal() == .OK { model.open(panel.urls) }
    }
}
