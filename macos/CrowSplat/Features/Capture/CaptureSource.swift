import AVFoundation
import AppKit
import UniformTypeIdentifiers

/// What the user dropped, understood: one video, or a set of photos.
struct CaptureSource {
    enum Kind { case video, photos, unsupported(String) }

    let kind: Kind
    let urls: [URL]
    /// The path the core reads: the video file, or a folder of photos.
    var input: URL?
    var duration: Double = 0
    var photoCount = 0
    var suggestedName = "Untitled"

    static let imageTypes: [UTType] = [.jpeg, .png, .heic, .tiff, .bmp, .webP]

    static func classify(_ urls: [URL]) -> CaptureSource {
        let fm = FileManager.default
        var files: [URL] = []
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                files += (try? fm.contentsOfDirectory(at: url, includingPropertiesForKeys: nil)) ?? []
            } else {
                files.append(url)
            }
        }
        let videos = files.filter { type(of: $0)?.conforms(to: .movie) == true }
        let photos = files.filter { u in imageTypes.contains { type(of: u)?.conforms(to: $0) == true } }
            .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }

        if videos.count == 1 && photos.isEmpty {
            var s = CaptureSource(kind: .video, urls: urls, input: videos[0])
            s.suggestedName = videos[0].deletingPathExtension().lastPathComponent
            return s
        }
        if videos.isEmpty && photos.count >= 3 {
            var s = CaptureSource(kind: .photos, urls: photos)
            s.photoCount = photos.count
            // A dropped folder is used as is; loose photos get a staging folder.
            if urls.count == 1, (try? urls[0].resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                s.input = urls[0]
                s.suggestedName = urls[0].lastPathComponent
            } else {
                s.suggestedName = photos[0].deletingLastPathComponent().lastPathComponent
            }
            return s
        }
        if videos.count > 1 {
            return CaptureSource(kind: .unsupported("One video per scene. Drop them one at a time."), urls: urls)
        }
        if !videos.isEmpty && !photos.isEmpty {
            return CaptureSource(kind: .unsupported("That mixes video and photos. Pick one kind per scene."), urls: urls)
        }
        if photos.count < 3 {
            return CaptureSource(kind: .unsupported("A scene needs at least a handful of photos, ideally 30 or more."), urls: urls)
        }
        return CaptureSource(kind: .unsupported("CrowSplat reads videos and photos."), urls: urls)
    }

    private static func type(of url: URL) -> UTType? { UTType(filenameExtension: url.pathExtension) }

    /// Loose photos: link them into one folder inside the scene so the core
    /// gets the folder it expects without copying gigabytes.
    func stagedInput(in sceneFolder: URL) throws -> URL {
        if let input { return input }
        let staging = sceneFolder.appending(path: "source")
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        for photo in urls {
            let link = staging.appending(path: photo.lastPathComponent)
            if !FileManager.default.fileExists(atPath: link.path) {
                try FileManager.default.createSymbolicLink(at: link, withDestinationURL: photo)
            }
        }
        return staging
    }
}

enum Media {
    static func duration(of url: URL) async -> Double {
        let asset = AVURLAsset(url: url)
        return (try? await asset.load(.duration).seconds) ?? 0
    }

    static func frame(of url: URL, at seconds: Double, maxWidth: CGFloat = 900) async -> NSImage? {
        let gen = AVAssetImageGenerator(asset: AVURLAsset(url: url))
        gen.appliesPreferredTrackTransform = true
        gen.maximumSize = CGSize(width: maxWidth, height: maxWidth)
        gen.requestedTimeToleranceBefore = .positiveInfinity
        gen.requestedTimeToleranceAfter = CMTime(seconds: 0.5, preferredTimescale: 600)
        guard let cg = try? await gen.image(at: CMTime(seconds: seconds, preferredTimescale: 600)).image else { return nil }
        return NSImage(cgImage: cg, size: .zero)
    }

    static func thumbnail(of url: URL, size: CGFloat = 220) -> NSImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: size,
              ] as CFDictionary) else { return nil }
        return NSImage(cgImage: cg, size: .zero)
    }
}
