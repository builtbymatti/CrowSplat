import SwiftUI

/// From capture to running job in one sheet. The left half shows what was
/// dropped (a video with its in/out range, or the photos); the right half asks
/// only what changes the result.
struct NewSceneSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let urls: [URL]

    @State private var source: CaptureSource?
    @State private var name = ""
    @State private var quality = "standard"
    @State private var fps = 3
    @State private var trim: ClosedRange<Double> = 0...1
    @State private var is360 = false
    @State private var clean = true
    @State private var exportSOG = true
    @State private var exportSPZ = false
    @State private var startError: String?

    var body: some View {
        HStack(spacing: 0) {
            preview
                .frame(width: 340)
                .frame(maxHeight: .infinity)
                .background(Palette.canvas)
                .overlay(alignment: .trailing) { Palette.rim.frame(width: 1) }
            form
                .frame(width: 420)
        }
        .frame(minHeight: 560)
        .fixedSize(horizontal: false, vertical: true)
        .background(Palette.surface)
        .task {
            var s = CaptureSource.classify(urls)
            if case .video = s.kind, let input = s.input {
                s.duration = await Media.duration(of: input)
                trim = 0...max(s.duration, 0.1)
            }
            source = s
            name = model.library.uniqueName(s.suggestedName)
        }
    }

    // MARK: Preview

    @ViewBuilder
    private var preview: some View {
        VStack(alignment: .leading, spacing: 16) {
            switch source?.kind {
            case .video?:
                VideoPreview(url: source!.input!, duration: source!.duration, trim: $trim)
            case .photos?:
                PhotoStrip(photos: source!.urls)
            case .unsupported(let reason)?:
                VStack(alignment: .leading, spacing: 10) {
                    Icon(.warning, size: 18).foregroundStyle(Palette.failure)
                    Text(reason).font(.crowBody).foregroundStyle(Palette.ink2)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            case nil:
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(24)
    }

    // MARK: Form

    private var form: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("New scene").font(.crowTitle).foregroundStyle(Palette.ink)
                .padding(.bottom, 22)

            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 7) {
                    FieldLabel("Name")
                    TextField("Kitchen, Loft, Garden…", text: $name).textFieldStyle(FieldStyle())
                }

                VStack(alignment: .leading, spacing: 7) {
                    FieldLabel("Detail")
                    DetentScale(stops: [
                        .init(value: "draft", title: "Draft", readout: "7,000 steps. A quick look, good for checking coverage."),
                        .init(value: "standard", title: "Standard", readout: "30,000 steps. Balanced detail and time, right for most rooms."),
                        .init(value: "fine", title: "Fine", readout: "50,000 steps, denser splats, undistorted frames. The longest run."),
                    ], selection: $quality)
                }

                if case .video? = source?.kind {
                    VStack(alignment: .leading, spacing: 7) {
                        FieldLabel("Frames per second")
                        ScrubValue(values: [1, 2, 3, 4, 5, 6, 8, 10], value: $fps, unit: "fps", readout: frameNote)
                    }
                    CheckRow(title: "360° video", detail: "Split an equirectangular video into camera views first",
                             isOn: $is360)
                }

                VStack(alignment: .leading, spacing: 2) {
                    FieldLabel("When it is trained").padding(.bottom, 4)
                    CheckRow(title: "Remove floaters", detail: "Drops stray, oversized and transparent splats",
                             isOn: $clean)
                    CheckRow(title: "Export SOG", detail: "Small, streams fast on the web", isOn: $exportSOG)
                    CheckRow(title: "Export SPZ", detail: "Compact file for Niantic and other viewers",
                             isOn: $exportSPZ)
                }
            }

            Spacer(minLength: 16)

            if let startError {
                Text(startError).font(.crowCaption).foregroundStyle(Palette.failure).padding(.bottom, 10)
            } else if !model.engines.coreReady && model.engines.probed {
                Text("COLMAP or Brush is missing. Install them in Settings.")
                    .font(.crowCaption).foregroundStyle(Palette.failure).padding(.bottom, 10)
            }

            HStack {
                Button("Cancel") { dismiss() }
                    .buttonStyle(.quiet)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button { start() } label: { Labeled("Start", .play, iconSize: 12) }
                    .buttonStyle(PrimaryButtonStyle(wide: true))
                    .keyboardShortcut(.defaultAction)
                    .disabled(!canStart)
            }
        }
        .padding(28)
    }


    private var frameNote: String {
        let seconds = trim.upperBound - trim.lowerBound
        let frames = Int(seconds * Double(fps))
        return "About \(frames) frames from \(Format.clock(seconds))"
    }

    private var canStart: Bool {
        guard let source, !name.trimmingCharacters(in: .whitespaces).isEmpty, model.jobs.active == nil else { return false }
        if case .unsupported = source.kind { return false }
        return true
    }

    private func start() {
        guard let source else { return }
        let sceneName = model.library.uniqueName(name)
        let folder = model.library.folder.appending(path: sceneName)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let input = try source.stagedInput(in: folder)
            var job: [String: Any] = [
                "input": input.path,
                "library": model.library.folder.path,
                "name": sceneName,
                "quality": quality,
                "export": [exportSOG ? "sog" : nil, exportSPZ ? "spz" : nil].compactMap { $0 },
            ]
            if clean { job["clean"] = "medium" }
            if case .video = source.kind {
                job["fps"] = fps
                if trim.lowerBound > 0.05 || trim.upperBound < source.duration - 0.05 {
                    job["trim"] = [trim.lowerBound, trim.upperBound]
                }
                if is360 { job["source"] = "360" }
            }
            // Kept next to the scene so "Run again" repeats exactly this.
            let data = try JSONSerialization.data(withJSONObject: job, options: [.prettyPrinted])
            try data.write(to: folder.appending(path: "job.json"))
            model.jobs.start(kind: "scene", title: sceneName, sceneName: sceneName, job: job)
            model.library.reload()
            model.destination = .scene(sceneName)
            dismiss()
        } catch {
            startError = error.localizedDescription
        }
    }
}

// MARK: - Video

private struct VideoPreview: View {
    let url: URL
    let duration: Double
    @Binding var trim: ClosedRange<Double>
    @State private var poster: NSImage?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ZStack {
                Palette.raised
                if let poster {
                    Image(nsImage: poster).resizable().aspectRatio(contentMode: .fit)
                        .transition(.opacity)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 300)
            .clipShape(.rect(cornerRadius: Metrics.radius, style: .continuous))
            .animation(Motion.smooth, value: poster != nil)

            HStack(spacing: 8) {
                Icon(.video, size: 14)
                Text(url.lastPathComponent).font(.crowLabel).lineLimit(1).truncationMode(.middle)
                Spacer()
                Text(Format.clock(duration)).font(.crowData)
            }
            .foregroundStyle(Palette.ink2)

            VStack(alignment: .leading, spacing: 8) {
                FieldLabel("Use this part")
                RangeSlider(range: $trim, bounds: 0...max(duration, 0.1))
                HStack {
                    Text(Format.clock(trim.lowerBound))
                    Spacer()
                    Text(Format.clock(trim.upperBound))
                }
                .font(.crowData).foregroundStyle(Palette.ink3)
            }
            Spacer()
        }
        .task(id: Int(trim.lowerBound * 2)) {
            // The poster follows the in point, so trimming shows where it starts.
            poster = await Media.frame(of: url, at: trim.lowerBound)
        }
    }
}

/// Two handles on one track. The kept span is ink, the cut ends stay dim.
struct RangeSlider: View {
    @Binding var range: ClosedRange<Double>
    let bounds: ClosedRange<Double>
    private let knob: CGFloat = 14

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width - knob
            let span = bounds.upperBound - bounds.lowerBound
            let x0 = CGFloat((range.lowerBound - bounds.lowerBound) / span) * w
            let x1 = CGFloat((range.upperBound - bounds.lowerBound) / span) * w
            ZStack(alignment: .leading) {
                Capsule().fill(Palette.ink4).frame(height: 3).padding(.horizontal, knob / 2)
                Capsule().fill(Palette.ink).frame(width: max(0, x1 - x0), height: 3)
                    .offset(x: x0 + knob / 2)
                handle(lower: true, span: span).offset(x: x0).gesture(drag(w: w, span: span, lower: true))
                handle(lower: false, span: span).offset(x: x1).gesture(drag(w: w, span: span, lower: false))
            }
            .frame(height: knob)
            .coordinateSpace(name: "track")
        }
        .frame(height: 14)
    }

    private func handle(lower: Bool, span: Double) -> some View {
        Circle().fill(Palette.ink).frame(width: knob, height: knob)
            .overlay(Circle().strokeBorder(Palette.canvas, lineWidth: 2))
            .contentShape(Circle().inset(by: -6))
            .accessibilityElement()
            .accessibilityLabel(lower ? "Start" : "End")
            .accessibilityValue(Format.clock(lower ? range.lowerBound : range.upperBound))
            .accessibilityAdjustableAction { direction in
                let step = span / 100 * (direction == .increment ? 1 : -1)
                set(lower: lower, to: (lower ? range.lowerBound : range.upperBound) + step, span: span)
            }
    }

    /// Clamped so the handles never cross and keep a 2 % gap.
    private func set(lower: Bool, to value: Double, span: Double) {
        let v = min(bounds.upperBound, max(bounds.lowerBound, value))
        let minGap = span * 0.02
        if lower {
            range = min(v, range.upperBound - minGap)...range.upperBound
        } else {
            range = range.lowerBound...max(v, range.lowerBound + minGap)
        }
    }

    private func drag(w: CGFloat, span: Double, lower: Bool) -> some Gesture {
        // Measured on the whole track, not on the 14 pt handle being dragged.
        DragGesture(minimumDistance: 0, coordinateSpace: .named("track")).onChanged { g in
            let v = bounds.lowerBound + Double(max(0, min(w, g.location.x - knob / 2)) / w) * span
            set(lower: lower, to: v, span: span)
        }
    }
}

// MARK: - Photos

private struct PhotoStrip: View {
    let photos: [URL]
    @State private var thumbs: [NSImage] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
                ForEach(Array(thumbs.enumerated()), id: \.offset) { _, img in
                    Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                        .frame(minWidth: 0, maxWidth: .infinity).frame(height: 88).clipped()
                        .clipShape(.rect(cornerRadius: 6, style: .continuous))
                        .transition(.opacity)
                }
            }
            .animation(Motion.smooth, value: thumbs.count)
            HStack(spacing: 8) {
                Icon(.photo, size: 14)
                Text("\(photos.count) photos").font(.crowLabel)
                Spacer()
            }
            .foregroundStyle(Palette.ink2)
            Text("Overlap matters more than count: each spot should be seen from a few angles.")
                .font(.crowCaption).foregroundStyle(Palette.ink3)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
        }
        .task {
            // Evenly spread picks, so the strip shows the whole walk, not its start.
            let picks = stride(from: 0, to: photos.count, by: max(1, photos.count / 9)).prefix(9)
            for i in picks {
                if let t = Media.thumbnail(of: photos[i]) { thumbs.append(t) }
            }
        }
    }
}
