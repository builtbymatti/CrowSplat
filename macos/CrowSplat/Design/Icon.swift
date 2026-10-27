import SwiftUI

/// Gravity UI icons (MIT), copied under the app's own names by
/// ``macos/scripts/sync_assets.py``. Template images: they take the
/// foreground colour, and sit bare on the surface, never in a tile.
enum Glyph: String {
    case add, video, photo, folder, scene, play, stop, trash, external, export, settings
    case search, check, clock, cpu, layers, close, reset, eye, more, install, clean
    case convert, upscale, panorama, film, log, warning, done, failed, copy, disk
    case sliders, camera, trim, sharp, sphere, cubes
    case chevronDown = "chevron.down"
    case chevronRight = "chevron.right"
    case chevronLeft = "chevron.left"
}

struct Icon: View {
    let glyph: Glyph
    var size: CGFloat = 16

    init(_ glyph: Glyph, size: CGFloat = 16) {
        self.glyph = glyph
        self.size = size
    }

    var body: some View {
        Image("Icons/\(glyph.rawValue)")
            .renderingMode(.template)
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}
