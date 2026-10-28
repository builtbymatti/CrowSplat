import SwiftUI
import UniformTypeIdentifiers

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var pointer = CGPoint(x: 0.75, y: 0.3)

    var body: some View {
        ZStack {
            InstrumentBackground(strength: model.onboarded ? 0.6 : 1, pointer: pointer)
            if model.onboarded {
                MainView()
                    .transition(.opacity)
            } else {
                OnboardingView()
                    .transition(.opacity)
            }
        }
        .modifier(PointerLight(point: $pointer))
        .animation(Motion.gentle, value: model.onboarded)
        .task {
            #if DEBUG
            // UI tests: start with an import, as if it had been dropped.
            if let path = ProcessInfo.processInfo.environment["CROW_TEST_IMPORT"] {
                model.open([URL(fileURLWithPath: path)])
            }
            #endif
            await model.engines.probe()
        }
    }
}

/// Sidebar + content. The sidebar is the app's spine: the mark, two places,
/// and the job that is running right now.
struct MainView: View {
    @Environment(AppModel.self) private var model
    @State private var dropTargeted = false

    var body: some View {
        @Bindable var model = model
        HStack(spacing: 0) {
            Sidebar()
                .frame(width: Metrics.sidebarWidth)
            ZStack {
                switch model.destination {
                case .library: LibraryView()
                case .tools: ToolsView()
                case .scene(let name): SceneDetailView(sceneName: name)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .overlay { if dropTargeted { DropHighlight() } }
        }
        .ignoresSafeArea(.container, edges: .top)
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            Task { model.open(await providers.fileURLs()) }
            return true
        }
        .sheet(item: Binding(
            get: { model.pendingImport.map(ImportRequest.init) },
            set: { model.pendingImport = $0?.urls })
        ) { request in
            NewSceneSheet(urls: request.urls)
                .environment(model)
        }
    }
}

struct ImportRequest: Identifiable {
    let urls: [URL]
    var id: String { urls.map(\.path).joined(separator: "|") }
}

/// The whole content area answers a drag, with a quiet inset outline.
private struct DropHighlight: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 14, style: .continuous)
            .strokeBorder(Palette.ink.opacity(0.5), style: StrokeStyle(lineWidth: 1.5, dash: [6, 6]))
            .padding(14)
            .overlay {
                Labeled("Drop to start a scene or view a splat", .add)
                    .font(.crowHeading)
                    .foregroundStyle(Palette.ink)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .surface(Palette.raised)
            }
            .allowsHitTesting(false)
            .transition(.opacity)
    }
}

extension [NSItemProvider] {
    func fileURLs() async -> [URL] {
        var urls: [URL] = []
        for provider in self {
            if let url = try? await provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) as? Data,
               let fileURL = URL(dataRepresentation: url, relativeTo: nil) {
                urls.append(fileURL)
            }
        }
        return urls
    }
}
