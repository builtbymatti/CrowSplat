<p align="center">
  <img src="docs/images/onboarding.png" alt="CrowSplat: the crow drawn as Gaussian splats" width="860">
</p>

# CrowSplat

A native Mac app that turns a video or a set of photos into a Gaussian splat you can orbit, fly through and share. Everything is trained on your own Mac, offline.

CrowSplat is a new frontend for [CorbeauSplat](https://github.com/freddewitt/CorbeauSplat) by Frederick. The pipeline underneath is his: COLMAP for camera poses, Brush for training, cleaning and export. CrowSplat replaces the Qt interface with a SwiftUI app and rethinks the flow around one question: what do you want to capture?

## What it does

- **Drop a capture, get a scene.** One video or a folder of photos. The app shows what it understood (the video with an in/out range, or a strip of your photos) and asks only what changes the result: how much detail, whether to remove floaters, which formats to export.
- **Watch it take shape.** While Brush trains, every new checkpoint loads into the viewer, so you see the splat sharpen instead of a progress bar alone. Progress is read live from COLMAP and Brush, with the time left and the splat count.
- **A library, not a project folder.** Every scene is a plain folder with the splat, its exports and the frames it came from, plus a `scene.json` the app reads. Move it, back it up, open it anywhere.
- **Tools on the side.** Single photo to 3D with Apple ML Sharp, cleaning, conversion to SOG, SPZ and GLB, upscaling, 360° video splitting and 4D dataset preparation.

<p align="center">
  <img src="docs/images/library.png" alt="The CrowSplat library" width="860">
</p>

## Install

Download the DMG from [Releases](https://github.com/builtbymatti/CrowSplat/releases), open it and drag CrowSplat into Applications. On first launch CrowSplat checks what your Mac has and installs the engines it needs:

| Engine | Needed for | Comes from |
| --- | --- | --- |
| COLMAP | every scene | Homebrew (`brew install colmap`) |
| Brush | every scene | downloaded by the app |
| SplatTransform | SOG / SPZ / GLB export | npm (needs [Node.js](https://nodejs.org)) |
| ML Sharp, Upscayl, 360° Extractor, 4DGS prep | the matching tools | downloaded by the app, optional |

Requirements: macOS 15 or later on Apple Silicon. 16 GB of memory is comfortable for room-sized scenes.

## Build from source

```sh
brew install xcodegen uv create-dmg
python3 macos/scripts/sync_assets.py --viewer   # icons, fonts, 3D viewer (pinned)
cd macos && xcodegen generate && open CrowSplat.xcodeproj
```

Debug builds run the Python core straight from this checkout, so set up its environment once:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`macos/scripts/build_release.sh` builds the release app with an embedded CPython, signs every binary, makes the DMG and notarizes it when a `notarytool` profile named `crowsplat` exists.

## How it fits together

```
CrowSplat.app (SwiftUI)
 ├─ Library, capture, scene and tool screens
 ├─ Viewer: PlayCanvas SuperSplat viewer in a WKWebView, its own UI off
 └─ python -m app.bridge  ── one process per job, JSON events on stdout
      └─ app/core  ── the CorbeauSplat engines: COLMAP, Brush, cleaner,
                      export, Sharp, upscale, 360, 4DGS
```

The bridge (`app/bridge`) is the only new piece of the core. It runs a job, streams `step`, `progress`, `eta`, `status`, `log`, `artifact` and `done` events, and stops the running engine on SIGTERM. `tools/progress_demo` contains stand-ins for COLMAP and Brush that print the real output formats, so the whole chain can run without a GPU.

The original Qt app and its CLI still work from this repository: `python main.py`. Its README is in [docs/CorbeauSplat-README.md](docs/CorbeauSplat-README.md).

## Credits

- [CorbeauSplat](https://github.com/freddewitt/CorbeauSplat) by Frederick, MIT
- [COLMAP](https://colmap.github.io), BSD
- [Brush](https://github.com/ArthurBrussee/brush) by Arthur Brussee, Apache-2.0
- [SuperSplat Viewer](https://github.com/playcanvas/supersplat-viewer) and [splat-transform](https://github.com/playcanvas/splat-transform) by PlayCanvas, MIT
- [Geist](https://vercel.com/font) by Vercel, SIL OFL 1.1
- [Gravity UI icons](https://gravity-ui.com/icons), MIT

## License

MIT, see [LICENSE](LICENSE).
