import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var section = "engines"

    var body: some View {
        VStack(spacing: 0) {
            ChoiceBar(options: [("engines", "Engines"), ("library", "Library"), ("about", "About")],
                      selection: $section)
                .frame(width: 330)
                .padding(.top, 18)
                .padding(.bottom, 20)
            ScrollView {
                Group {
                    switch section {
                    case "library": librarySection
                    case "about": AboutSection()
                    default: enginesSection
                    }
                }
                .padding(.horizontal, 28)
                .padding(.bottom, 28)
            }
        }
        .frame(width: 600, height: 560)
        .background(Palette.surface)
        .task { if !model.engines.probed { await model.engines.probe() } }
    }

    private var enginesSection: some View {
        VStack(alignment: .leading, spacing: 22) {
            engineGroup("Needed for every scene", model.engines.engines.filter { $0.role != "optional" })
            engineGroup("Optional", model.engines.engines.filter { $0.role == "optional" })
            HStack {
                Text(model.engines.machine.values.sorted().joined(separator: " · "))
                    .font(.crowData).foregroundStyle(Palette.ink3)
                Spacer()
                Button { Task { await model.engines.probe() } } label: {
                    Labeled(model.engines.probing ? "Checking" : "Check again", .reset, iconSize: 12)
                }
                .buttonStyle(.quiet)
                .disabled(model.engines.probing)
            }
        }
    }

    private func engineGroup(_ title: String, _ engines: [EngineStatus]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            FieldLabel(title)
            VStack(spacing: 0) {
                ForEach(engines) { engine in
                    EngineRow(engine: engine)
                    if engine.id != engines.last?.id { Divider().overlay(Palette.edge) }
                }
            }
            .padding(.horizontal, 14)
            .surface()
        }
    }

    private var librarySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            FieldLabel("Scenes are saved in")
            LibraryFolderPicker()
            Text("Changing the folder does not move existing scenes. Each scene is a self-contained folder you can move by hand.")
                .font(.crowCaption).foregroundStyle(Palette.ink3)
                .fixedSize(horizontal: false, vertical: true)
            if let data = CoreLocator.shared.dataRoot {
                FieldLabel("Engines and models").padding(.top, 14)
                HStack {
                    Text(data.path.replacingOccurrences(of: NSHomeDirectory(), with: "~"))
                        .font(.crowData).foregroundStyle(Palette.ink2).lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Button("Show") { NSWorkspace.shared.activateFileViewerSelecting([data]) }.buttonStyle(.quiet)
                }
                .padding(.leading, 12).padding(.trailing, 4).frame(height: 42).surface()
            }
        }
    }
}

private struct AboutSection: View {
    private let credits: [(String, String, String)] = [
        ("CorbeauSplat", "by Frederick, the pipeline this app is built on", "https://github.com/freddewitt/CorbeauSplat"),
        ("COLMAP", "structure from motion", "https://colmap.github.io"),
        ("Brush", "Gaussian splat training by Arthur Brussee", "https://github.com/ArthurBrussee/brush"),
        ("SuperSplat Viewer", "rendering, by PlayCanvas", "https://github.com/playcanvas/supersplat-viewer"),
        ("splat-transform", "format conversion, by PlayCanvas", "https://github.com/playcanvas/splat-transform"),
        ("Alpha Lyrae", "typeface by Fontfabric for Vega, SIL OFL", "https://github.com/vegaprotocol/alpha-lyrae"),
        ("Gravity UI icons", "MIT", "https://gravity-ui.com/icons"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 14) {
                CrowMark(height: 30).foregroundStyle(Palette.ink)
                VStack(alignment: .leading, spacing: 3) {
                    Text("CrowSplat").font(Typeface.sans(20, .semibold)).foregroundStyle(Palette.ink)
                    Text("Version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0")")
                        .font(.crowData).foregroundStyle(Palette.ink3)
                }
            }
            Text("Open source under the MIT License. CrowSplat stands on these projects:")
                .font(.crowBody).foregroundStyle(Palette.ink2)
            VStack(spacing: 0) {
                ForEach(credits, id: \.0) { name, role, url in
                    Link(destination: URL(string: url)!) {
                        HStack {
                            Text(name).font(.crowLabel).foregroundStyle(Palette.ink)
                            Text(role).font(.crowCaption).foregroundStyle(Palette.ink3)
                            Spacer()
                            Icon(.external, size: 12).foregroundStyle(Palette.ink3)
                        }
                        .padding(.vertical, 10)
                        .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    if name != credits.last?.0 { Divider().overlay(Palette.edge) }
                }
            }
            .padding(.horizontal, 14)
            .surface()
            Link(destination: URL(string: "https://github.com/builtbymatti/CrowSplat")!) {
                Labeled("Source on GitHub", .external, iconSize: 12)
            }
            .buttonStyle(.quiet)
        }
    }
}
