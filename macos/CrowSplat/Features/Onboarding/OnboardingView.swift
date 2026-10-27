import SwiftUI

/// First launch: what this is, what it needs, where scenes go. The crow
/// forms out of splats on the left and stays there, breathing, while the
/// three steps change on the right.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var step = 0
    @State private var formation = 0.0

    var body: some View {
        HStack(spacing: 0) {
            SplatField(formation: formation)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(48)
                .background(Palette.canvas)

            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 8) {
                    CrowMark(height: 14)
                    Text("CrowSplat").font(Typeface.sans(13, .semibold))
                    Spacer()
                    StepDots(count: 3, current: step)
                }
                .foregroundStyle(Palette.ink)
                .padding(.top, 52)

                Spacer(minLength: 24)

                Group {
                    switch step {
                    case 0: WelcomeStep()
                    case 1: EnginesStep()
                    default: LibraryStep()
                    }
                }
                .id(step)
                .transition(.asymmetric(
                    insertion: .offset(x: 24).combined(with: .opacity),
                    removal: .offset(x: -24).combined(with: .opacity)))

                Spacer(minLength: 24)

                HStack {
                    if step > 0 {
                        Button { go(step - 1) } label: { Labeled("Back", .chevronLeft, iconSize: 12) }
                            .buttonStyle(.quiet)
                    }
                    Spacer()
                    Button(primaryTitle) {
                        if step < 2 { go(step + 1) } else { model.onboarded = true }
                    }
                    .buttonStyle(PrimaryButtonStyle(wide: true))
                    .keyboardShortcut(.defaultAction)
                }
                .padding(.bottom, 36)
            }
            .padding(.horizontal, 44)
            .frame(width: 440)
            .frame(maxHeight: .infinity)
            .background(Palette.surface)
        }
        .onAppear {
            withAnimation(.easeOut(duration: 2.6).delay(0.2)) { formation = 1 }
        }
    }

    private var primaryTitle: String {
        switch step {
        case 0: "Get started"
        case 1: model.engines.coreReady ? "Continue" : "Continue without"
        default: "Open CrowSplat"
        }
    }

    private func go(_ s: Int) { withAnimation(Motion.smooth) { step = s } }
}

/// Three short marks; the current one stretches. Progress, not navigation.
private struct StepDots: View {
    let count: Int
    let current: Int
    var body: some View {
        HStack(spacing: 5) {
            ForEach(0..<count, id: \.self) { i in
                Capsule()
                    .fill(i == current ? Palette.ink : Palette.ink4)
                    .frame(width: i == current ? 18 : 6, height: 4)
            }
        }
        .animation(Motion.snappy, value: current)
        .accessibilityLabel("Step \(current + 1) of \(count)")
    }
}

private struct WelcomeStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Walk through it again, from anywhere.")
                .font(Typeface.sans(30, .semibold))
                .foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text("Film a room or take a set of photos. CrowSplat turns them into a Gaussian splat you can orbit, fly through and share, trained right here on your Mac.")
                .font(Typeface.sans(14))
                .foregroundStyle(Palette.ink2)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            if let chip = model.engines.machine["chip"] {
                HStack(spacing: 8) {
                    Icon(.cpu, size: 14)
                    Text([chip, model.engines.machine["memory"]].compactMap { $0 }.joined(separator: " · "))
                        .font(.crowData)
                }
                .foregroundStyle(Palette.ink3)
                .padding(.top, 6)
            }
        }
    }
}

private struct EnginesStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Two engines do the heavy lifting.")
                .font(Typeface.sans(26, .semibold))
                .foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text("COLMAP finds where every frame was taken. Brush trains the splat on your GPU. Everything runs offline.")
                .font(Typeface.sans(14))
                .foregroundStyle(Palette.ink2)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)

            VStack(spacing: 0) {
                if !model.engines.probed {
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small)
                        Text("Looking around this Mac").font(.crowBody).foregroundStyle(Palette.ink3)
                    }
                    .frame(maxWidth: .infinity, minHeight: 120)
                }
                ForEach(model.engines.engines.filter { $0.role != "optional" }) { engine in
                    EngineRow(engine: engine)
                    if engine.id != "splat-transform" { Divider().overlay(Palette.edge) }
                }
            }
            .padding(.horizontal, 14)
            .surface()

            Text("Sharp, Upscayl, 360° and 4D tools are optional. Add them later in Settings.")
                .font(.crowCaption)
                .foregroundStyle(Palette.ink3)
        }
    }
}

/// One engine: name and purpose, then its state on the right. Missing
/// engines install in place, the installer's own last line streaming by.
struct EngineRow: View {
    @Environment(AppModel.self) private var model
    let engine: EngineStatus

    var body: some View {
        let install = model.engines.installing[engine.id]
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(engine.title).font(.crowHeading).foregroundStyle(Palette.ink)
                if let install, install.failed == nil {
                    Text(install.line.isEmpty ? "Installing" : install.line)
                        .font(.crowData).foregroundStyle(Palette.ink3).lineLimit(1)
                        .contentTransition(.opacity)
                } else if let failure = install?.failed {
                    Text(failure).font(.crowCaption).foregroundStyle(Palette.failure).lineLimit(2)
                } else {
                    Text(engine.purpose).font(.crowCaption).foregroundStyle(Palette.ink3).lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            if engine.installed {
                HStack(spacing: 6) {
                    Text(engine.version).font(.crowData).foregroundStyle(Palette.ink3).lineLimit(1)
                    Icon(.done, size: 15).foregroundStyle(Palette.ink)
                }
            } else if install != nil && install?.failed == nil {
                ProgressView().controlSize(.small)
            } else if engine.via == "homebrew" && !model.engines.homebrew {
                Link(destination: URL(string: "https://brew.sh")!) {
                    Labeled("Get Homebrew", .external, iconSize: 12)
                }
                .buttonStyle(.quiet)
            } else {
                Button { Task { await model.engines.install(engine.id) } } label: {
                    Labeled(install?.failed == nil ? "Install" : "Retry", .install, iconSize: 13)
                }
                .buttonStyle(.quiet)
            }
        }
        .padding(.vertical, 12)
        .animation(Motion.smooth, value: engine.installed)
        .animation(Motion.smooth, value: install)
    }
}

private struct LibraryStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Where should scenes live?")
                .font(Typeface.sans(26, .semibold))
                .foregroundStyle(Palette.ink)
            Text("Each scene is a plain folder: the splat, its exports and the frames it was built from. Move it, back it up, open it anywhere.")
                .font(Typeface.sans(14))
                .foregroundStyle(Palette.ink2)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            LibraryFolderPicker()
        }
    }
}

struct LibraryFolderPicker: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 10) {
            Icon(.folder, size: 15).foregroundStyle(Palette.ink2)
            Text(model.library.folder.path.replacingOccurrences(of: NSHomeDirectory(), with: "~"))
                .font(.crowData)
                .foregroundStyle(Palette.ink)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            Button("Change…") {
                let panel = NSOpenPanel()
                panel.canChooseFiles = false
                panel.canChooseDirectories = true
                panel.canCreateDirectories = true
                panel.prompt = "Use folder"
                if panel.runModal() == .OK, let url = panel.url { model.library.folder = url }
            }
            .buttonStyle(.quiet)
        }
        .padding(.leading, 12).padding(.trailing, 4)
        .frame(height: 42)
        .surface()
    }
}
