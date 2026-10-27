import SwiftUI

struct Sidebar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Clear of the traffic lights, which float over the hidden title bar.
            HStack(spacing: 9) {
                CrowMark(height: 15)
                Text("CrowSplat")
                    .font(Typeface.sans(14, .semibold))
                    .tracking(0.2)
            }
            .foregroundStyle(Palette.ink)
            .padding(.top, 52)
            .padding(.horizontal, 18)
            .padding(.bottom, 26)

            VStack(spacing: 2) {
                SidebarItem(title: "Library", glyph: .scene, count: model.library.scenes.count,
                            selected: isLibrary) { model.destination = .library }
                SidebarItem(title: "Tools", glyph: .cubes, count: nil,
                            selected: model.destination == .tools) { model.destination = .tools }
            }
            .padding(.horizontal, 10)

            Spacer()

            if let run = model.jobs.active {
                ActiveJobCard(run: run)
                    .padding(.horizontal, 10)
                    .padding(.bottom, 10)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }

            HStack {
                SettingsLink {
                    Labeled("Settings", .settings)
                }
                .buttonStyle(.quiet)
                Spacer()
                if !model.engines.coreReady && model.engines.probed {
                    Icon(.warning, size: 14)
                        .foregroundStyle(Palette.failure)
                        .help("An engine CrowSplat needs is missing. Open Settings.")
                }
            }
            .padding(.horizontal, 10)
            .padding(.bottom, 14)
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Palette.surface)
        .animation(Motion.smooth, value: model.jobs.active?.id)
    }

    private var isLibrary: Bool {
        if case .scene = model.destination { return true }
        return model.destination == .library
    }
}

private struct SidebarItem: View {
    let title: String
    let glyph: Glyph
    let count: Int?
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Icon(glyph, size: 15)
                Text(title).font(selected ? Typeface.sans(13, .medium) : .crowBody)
                Spacer()
                if let count, count > 0 {
                    Text("\(count)").font(.crowData).foregroundStyle(Palette.ink3)
                }
            }
            .foregroundStyle(selected ? Palette.ink : (hovering ? Palette.ink2 : Palette.ink3))
            .padding(.horizontal, 10)
            .frame(height: 32)
            .background(selected ? Palette.lifted : (hovering ? Palette.raised : .clear),
                        in: .rect(cornerRadius: Metrics.controlRadius, style: .continuous))
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(Motion.hover, value: hovering)
        .animation(Motion.snappy, value: selected)
    }
}

/// The running job, always in reach: what it is doing and how far along.
private struct ActiveJobCard: View {
    @Environment(AppModel.self) private var model
    let run: JobRun
    @State private var hovering = false

    var body: some View {
        Button {
            if let name = run.sceneName { model.destination = .scene(name) } else { model.destination = .tools }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(run.title).font(.crowLabel).foregroundStyle(Palette.ink).lineLimit(1)
                    Spacer()
                    Text("\(Int(run.overall))%").font(.crowData).foregroundStyle(Palette.ink2)
                        .contentTransition(.numericText())
                }
                Text(run.stepLabel).font(.crowCaption).foregroundStyle(Palette.ink3).lineLimit(1)
                ProgressTrack(value: run.progress < 0 && run.stepIndex == 0 ? -1 : run.overall, height: 2)
            }
            .padding(12)
            .surface(hovering ? Palette.lifted : Palette.raised)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(Motion.hover, value: hovering)
        .animation(Motion.smooth, value: run.overall)
    }
}
