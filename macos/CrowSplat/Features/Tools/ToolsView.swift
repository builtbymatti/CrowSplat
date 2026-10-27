import SwiftUI
import UniformTypeIdentifiers

/// The standalone tools: everything the core can do outside the main
/// capture-to-splat flow, each one input, a few choices, one run.
enum Tool: String, CaseIterable, Identifiable {
    case sharp, clean, convert, upscale, split360, fourdgs
    var id: String { rawValue }

    var title: String {
        switch self {
        case .sharp: "Single photo to 3D"
        case .clean: "Clean a splat"
        case .convert: "Convert a splat"
        case .upscale: "Upscale photos"
        case .split360: "Split a 360° video"
        case .fourdgs: "Prepare a 4D dataset"
        }
    }

    var detail: String {
        switch self {
        case .sharp: "Apple ML Sharp predicts depth from one image and builds a splat from it."
        case .clean: "Remove floaters, giant splats and transparent haze from a .ply."
        case .convert: "Write SOG for the web, SPZ for compact sharing, or GLB."
        case .upscale: "Sharpen low-resolution input before reconstruction."
        case .split360: "Turn an equirectangular video into ordinary camera views."
        case .fourdgs: "Synchronised multi-camera video to a Nerfstudio dataset."
        }
    }

    var glyph: Glyph {
        switch self {
        case .sharp: .sharp
        case .clean: .clean
        case .convert: .convert
        case .upscale: .upscale
        case .split360: .panorama
        case .fourdgs: .film
        }
    }

    /// Engine the tool needs, checked before it runs.
    var engine: String? {
        switch self {
        case .sharp: "sharp"
        case .convert: "splat-transform"
        case .upscale: "upscayl"
        case .split360: "extractor_360"
        case .fourdgs: "four_dgs"
        case .clean: nil
        }
    }

    var accepts: [UTType] {
        switch self {
        case .sharp: [.image, .movie]
        case .clean, .convert: [UTType(filenameExtension: "ply")!]
        case .upscale: [.image, .folder]
        case .split360: [.movie]
        case .fourdgs: [.folder]
        }
    }

    var inputHint: String {
        switch self {
        case .sharp: "A photo, or a video to process frame by frame"
        case .clean, .convert: "A .ply splat"
        case .upscale: "A photo or a folder of photos"
        case .split360: "An equirectangular 360° video"
        case .fourdgs: "A folder with one video per camera"
        }
    }

    var experimental: Bool { self == .split360 || self == .fourdgs }
}

struct ToolsView: View {
    @State private var open: Tool?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("Tools").font(.crowTitle).foregroundStyle(Palette.ink)
                    .padding(.top, 46).padding(.bottom, 24)
                    .frame(height: 32 + 46 + 24, alignment: .bottomLeading)
                VStack(spacing: 0) {
                    ForEach(Tool.allCases) { tool in
                        ToolRow(tool: tool) { open = tool }
                        if tool != Tool.allCases.last { Divider().overlay(Palette.edge).padding(.leading, 46) }
                    }
                }
                .surface(Palette.surface, radius: 12)
                .frame(maxWidth: 760)
            }
            .padding(.horizontal, Metrics.gutter)
            .padding(.bottom, 40)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .softScrollEdge()
        .sheet(item: $open) { tool in ToolSheet(tool: tool) }
    }
}

private struct ToolRow: View {
    @Environment(AppModel.self) private var model
    let tool: Tool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        let missing = tool.engine.flatMap { model.engines.engine($0) }.map { !$0.installed } ?? false
        Button(action: action) {
            HStack(spacing: 14) {
                Icon(tool.glyph, size: 18)
                    .foregroundStyle(hovering ? Palette.ink : Palette.ink2)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 8) {
                        Text(tool.title).font(.crowHeading).foregroundStyle(Palette.ink)
                        if tool.experimental {
                            Text("Experimental").font(.crowCaption).foregroundStyle(Palette.ink3)
                        }
                    }
                    Text(tool.detail).font(.crowCaption).foregroundStyle(Palette.ink3)
                }
                Spacer()
                if missing {
                    Text("Needs install").font(.crowCaption).foregroundStyle(Palette.ink3)
                }
                Icon(.chevronRight, size: 12)
                    .foregroundStyle(Palette.ink3)
                    .offset(x: hovering ? 2 : 0)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 15)
            .background(hovering ? Palette.raised : .clear)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(Motion.hover, value: hovering)
    }
}

/// One tool: pick the input, set the few options it has, run, see the result.
private struct ToolSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let tool: Tool

    @State private var input: URL?
    @State private var strength = "medium"
    @State private var formats: Set<String> = ["sog"]
    @State private var scale = 4
    @State private var fps = 5
    @State private var run: JobRun?
    @State private var dropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                Icon(tool.glyph, size: 20).foregroundStyle(Palette.ink)
                Text(tool.title).font(.crowTitle).foregroundStyle(Palette.ink)
            }
            Text(tool.detail).font(.crowBody).foregroundStyle(Palette.ink2)

            if let engine = tool.engine.flatMap({ model.engines.engine($0) }), !engine.installed {
                EngineRow(engine: engine)
                    .padding(.horizontal, 14)
                    .surface()
            }

            inputWell
            options

            if let run { ToolRunStatus(run: run) }

            Spacer(minLength: 0)
            HStack {
                Button(run?.state == .succeeded ? "Done" : "Close") { dismiss() }
                    .buttonStyle(.quiet)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                if let run, run.isRunning {
                    Button("Cancel") { run.cancel() }.buttonStyle(.quiet)
                } else if let path = run?.resultPath ?? run?.outputs.values.first, run?.state == .succeeded {
                    Button { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)]) } label: {
                        Labeled("Show in Finder", .folder)
                    }
                    .buttonStyle(.primary)
                } else {
                    Button { start() } label: { Labeled("Run", .play, iconSize: 12) }
                        .buttonStyle(PrimaryButtonStyle(wide: true))
                        .keyboardShortcut(.defaultAction)
                        .disabled(!canRun)
                }
            }
        }
        .padding(28)
        .frame(width: 520, height: 540)
        .background(Palette.surface)
    }

    private var inputWell: some View {
        Button { choose() } label: {
            HStack(spacing: 12) {
                Icon(input == nil ? .add : .check, size: 16)
                VStack(alignment: .leading, spacing: 3) {
                    Text(input?.lastPathComponent ?? "Choose or drop").font(.crowHeading).lineLimit(1)
                    Text(input.map { $0.deletingLastPathComponent().path.replacingOccurrences(of: NSHomeDirectory(), with: "~") } ?? tool.inputHint)
                        .font(input == nil ? .crowCaption : .crowData)
                        .foregroundStyle(Palette.ink3).lineLimit(1).truncationMode(.middle)
                }
                Spacer()
            }
            .foregroundStyle(Palette.ink)
            .padding(16)
            .frame(maxWidth: .infinity)
            .background(dropTargeted ? Palette.lifted : Palette.sunk,
                        in: .rect(cornerRadius: Metrics.radius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous)
                    .strokeBorder(input == nil ? Palette.ink4 : Palette.edge,
                                  style: StrokeStyle(lineWidth: 1, dash: input == nil ? [5, 5] : []))
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(run?.isRunning == true)
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            Task { if let url = await providers.fileURLs().first { input = url } }
            return true
        }
        .animation(Motion.hover, value: dropTargeted)
    }

    @ViewBuilder
    private var options: some View {
        switch tool {
        case .clean:
            VStack(alignment: .leading, spacing: 7) {
                FieldLabel("Strength")
                DetentScale(stops: [
                    .init(value: "light", title: "Light", readout: "Only the obvious: near-invisible and giant splats."),
                    .init(value: "medium", title: "Medium", readout: "Also floaters far from the scene. Right for most splats."),
                    .init(value: "strong", title: "Strong", readout: "Aggressive. Check thin details like plants and railings after."),
                ], selection: $strength)
            }
        case .convert:
            VStack(alignment: .leading, spacing: 10) {
                FieldLabel("Formats")
                ForEach([("sog", "SOG", "Small, streams fast on the web"), ("spz", "SPZ", "Compact, widely supported"),
                         ("glb", "GLB", "For 3D tools that read glTF")], id: \.0) { id, title, detail in
                    CheckRow(title: title, detail: detail, isOn: Binding(
                        get: { formats.contains(id) },
                        set: { if $0 { formats.insert(id) } else { formats.remove(id) } }))
                }
            }
        case .upscale:
            VStack(alignment: .leading, spacing: 7) {
                FieldLabel("Scale")
                DetentScale(stops: [
                    .init(value: 2, title: "2×", readout: "Twice the width and height. Fast."),
                    .init(value: 3, title: "3×", readout: "Three times. A good middle."),
                    .init(value: 4, title: "4×", readout: "Four times, the model's native scale. Slowest, sharpest."),
                ], selection: $scale)
            }
        case .fourdgs:
            VStack(alignment: .leading, spacing: 7) {
                FieldLabel("Frames per second")
                ScrubValue(values: [1, 2, 3, 5, 8, 10, 15], value: $fps, unit: "fps",
                           readout: "Taken from every camera's video")
            }
        default:
            EmptyView()
        }
    }

    private var canRun: Bool {
        guard input != nil, model.jobs.active == nil else { return false }
        if let engine = tool.engine.flatMap({ model.engines.engine($0) }), !engine.installed { return false }
        if tool == .convert && formats.isEmpty { return false }
        return true
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = tool.accepts
        panel.canChooseDirectories = tool.accepts.contains(.folder)
        panel.canChooseFiles = tool != .fourdgs
        if panel.runModal() == .OK { input = panel.url }
    }

    private func start() {
        guard let input else { return }
        let outDir = input.deletingLastPathComponent()
        let stem = input.deletingPathExtension().lastPathComponent
        var job: [String: Any] = ["input": input.path]
        switch tool {
        case .sharp: job["output"] = outDir.appending(path: "\(stem) sharp").path
        case .clean: job["strength"] = strength
        case .convert: job["formats"] = Array(formats).sorted(); job["output"] = outDir.path
        case .upscale: job["output"] = outDir.appending(path: "\(stem) upscaled").path; job["scale"] = scale
        case .split360: job["output"] = outDir.appending(path: "\(stem) views").path
        case .fourdgs: job["output"] = outDir.appending(path: "\(stem) 4d").path; job["fps"] = fps
        }
        run = model.jobs.start(kind: tool.rawValue, title: tool.title, job: job)
    }
}

private struct ToolRunStatus: View {
    let run: JobRun

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                switch run.state {
                case .running: Text(run.status.isEmpty ? run.stepLabel : run.status).lineLimit(1)
                case .succeeded: Labeled("Finished", .done)
                case .cancelled: Text("Cancelled")
                case .failed(let m): Text(m).foregroundStyle(Palette.failure).lineLimit(2)
                }
                Spacer()
                if run.isRunning && run.progress >= 0 {
                    Text("\(Int(run.progress))%").font(.crowData)
                }
            }
            .font(.crowBody)
            .foregroundStyle(Palette.ink2)
            if run.isRunning { ProgressTrack(value: run.progress) }
        }
        .padding(14)
        .surface()
        .animation(Motion.smooth, value: run.progress)
    }
}
