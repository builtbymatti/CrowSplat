import SwiftUI

struct LibraryView: View {
    @Environment(AppModel.self) private var model
    @State private var query = ""

    private var scenes: [SceneItem] {
        let all = model.library.scenes
        guard !query.isEmpty else { return all }
        return all.filter { $0.name.localizedCaseInsensitiveContains(query) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if model.library.scenes.isEmpty {
                EmptyLibrary()
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 232, maximum: 340), spacing: 22, alignment: .top)],
                              alignment: .leading, spacing: 30) {
                        ForEach(scenes) { scene in
                            SceneCard(scene: scene)
                                .onTapGesture { model.destination = .scene(scene.name) }
                        }
                    }
                    .padding(.horizontal, Metrics.gutter)
                    .padding(.bottom, 40)
                    .animation(Motion.smooth, value: scenes.map(\.id))
                }
            }
        }
        .softScrollEdge()
        .onAppear { model.library.reload() }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 14) {
            Text("Library").font(.crowTitle).foregroundStyle(Palette.ink)
            Spacer()
            if !model.library.scenes.isEmpty {
                HStack(spacing: 7) {
                    Icon(.search, size: 13).foregroundStyle(Palette.ink3)
                    TextField("Find a scene", text: $query)
                        .textFieldStyle(.plain)
                        .font(.crowBody)
                        .frame(width: 150)
                }
                .padding(.horizontal, 10)
                .frame(height: 30)
                .sunk(radius: Metrics.controlRadius)
            }
            Button { NewScenePicker.present(model: model) } label: { Labeled("New scene", .add) }
                .buttonStyle(.primary)
                .keyboardShortcut("n")
        }
        .padding(.horizontal, Metrics.gutter)
        .padding(.top, 46)
        .padding(.bottom, 24)
    }
}

/// A scene: its picture first, then name and one line of facts. While it
/// trains, the progress runs along the bottom edge of the picture.
private struct SceneCard: View {
    @Environment(AppModel.self) private var model
    let scene: SceneItem
    @State private var hovering = false

    var body: some View {
        let run = model.jobs.run(for: scene.name).flatMap { $0.isRunning ? $0 : nil }
        VStack(alignment: .leading, spacing: 11) {
            ZStack(alignment: .bottom) {
                Thumbnail(url: run?.thumbnail ?? scene.thumbnailURL)
                    .brightness(hovering ? 0.04 : 0)
                if let run {
                    ProgressTrack(value: run.overall, height: 4)
                        .padding(10)
                }
            }
            .aspectRatio(16 / 10, contentMode: .fit)
            .clipShape(.rect(cornerRadius: Metrics.radius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous)
                    .strokeBorder(Palette.edge, lineWidth: 1)
            }
            .background {
                RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous).fill(Palette.rim).offset(y: 1)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(scene.name).font(.crowHeading).foregroundStyle(Palette.ink).lineLimit(1)
                detail(run: run)
            }
            .padding(.horizontal, 2)
        }
        .contentShape(.rect)
        .onHover { hovering = $0 }
        .animation(Motion.smooth, value: hovering)
        .contextMenu {
            Button("Open") { model.destination = .scene(scene.name) }
            Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([scene.folder]) }
            Divider()
            Button("Move to Trash") { model.library.moveToTrash(scene) }
                .disabled(run != nil)
        }
    }

    @ViewBuilder
    private func detail(run: JobRun?) -> some View {
        if let run {
            HStack(spacing: 6) {
                Text(run.stepLabel)
                Text("\(Int(run.overall))%").font(.crowData)
            }
            .font(.crowCaption).foregroundStyle(Palette.ink2)
        } else {
            switch scene.state {
            case .failed:
                Text("Stopped. \(scene.manifest.error ?? "")").font(.crowCaption)
                    .foregroundStyle(Palette.failure).lineLimit(1)
            case .cancelled:
                Text("Cancelled").font(.crowCaption).foregroundStyle(Palette.ink3)
            case .running:
                // Running in a previous session that did not finish.
                Text("Interrupted").font(.crowCaption).foregroundStyle(Palette.ink3)
            default:
                Text("\(scene.kindLabel) · \(scene.qualityLabel) · \(Format.relative(scene.created))")
                    .font(.crowCaption).foregroundStyle(Palette.ink3).lineLimit(1)
            }
        }
    }
}

/// A scene's picture, or the crow on a quiet plate while there is none yet.
struct Thumbnail: View {
    let url: URL?

    var body: some View {
        GeometryReader { geo in
            if let url, let image = NSImage(contentsOf: url) {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(width: geo.size.width, height: geo.size.height)
                    .clipped()
            } else {
                ZStack {
                    Palette.raised
                    CrowMark(height: min(geo.size.height * 0.28, 44))
                        .foregroundStyle(Palette.ink4)
                }
            }
        }
    }
}

private struct EmptyLibrary: View {
    @Environment(AppModel.self) private var model
    @State private var formation = 0.0

    var body: some View {
        VStack(spacing: 0) {
            SplatField(formation: formation, count: 900, splatScale: 0.8)
                .frame(width: 380, height: 260)
            Text("Drop a video or a folder of photos")
                .font(Typeface.sans(20, .semibold))
                .foregroundStyle(Palette.ink)
                .padding(.top, 8)
            Text("A slow walk through the room works best. MP4, MOV, JPG, PNG and HEIC.")
                .font(.crowBody)
                .foregroundStyle(Palette.ink3)
                .padding(.top, 8)
            Button { NewScenePicker.present(model: model) } label: { Labeled("Choose files", .folder) }
                .buttonStyle(.quiet)
                .padding(.top, 18)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.bottom, 60)
        .onAppear { withAnimation(.easeOut(duration: 2.2)) { formation = 1 } }
    }
}
