import Foundation

/// One event from ``python -m app.bridge`` (see app/bridge/events.py).
struct BridgeEvent: Decodable, Sendable {
    let type: String
    var id: String?
    var label: String?
    var index: Int?
    var count: Int?
    var steps: [String]?
    var step: String?
    var value: Double?
    var seconds: Double?
    var text: String?
    var level: String?
    var kind: String?
    var path: String?
    var ok: Bool?
    var message: String?
    var result: JSONValue?
}

/// Untyped JSON for the ``result`` payloads (probe output, job results).
enum JSONValue: Decodable, Sendable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    var string: String? { if case .string(let s) = self { return s }; return nil }
    var double: Double? { if case .number(let n) = self { return n }; return nil }
    var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    var array: [JSONValue] { if case .array(let a) = self { return a }; return [] }
}

/// A running ``app.bridge`` process. Events arrive on ``events``; raw output
/// (engine logs) arrives as ``log`` events with level "raw".
final class BridgeProcess: @unchecked Sendable {
    private let process = Process()
    private let locator: CoreLocator

    init(arguments: [String], locator: CoreLocator = .shared) {
        self.locator = locator
        process.executableURL = locator.python
        process.arguments = ["-m", "app.bridge"] + arguments
        process.currentDirectoryURL = locator.coreRoot
        process.environment = locator.environment
    }

    /// Start a job from a dictionary (written to a temp file the core reads).
    static func job(_ job: [String: Any]) throws -> BridgeProcess {
        let data = try JSONSerialization.data(withJSONObject: job, options: [.prettyPrinted])
        let file = FileManager.default.temporaryDirectory.appending(path: "crow-job-\(UUID().uuidString).json")
        try data.write(to: file)
        return BridgeProcess(arguments: ["run", file.path])
    }

    var events: AsyncStream<BridgeEvent> {
        AsyncStream { continuation in
            let out = Pipe(), err = Pipe()
            process.standardOutput = out
            process.standardError = err
            process.standardInput = FileHandle.nullDevice
            let decoder = JSONDecoder()

            let group = DispatchGroup()
            group.enter()
            Thread.detachNewThread {
                Self.readLines(out.fileHandleForReading) { line in
                    if let ev = try? decoder.decode(BridgeEvent.self, from: Data(line.utf8)) {
                        continuation.yield(ev)
                    }
                }
                group.leave()
            }
            group.enter()
            Thread.detachNewThread {
                Self.readLines(err.fileHandleForReading) { line in
                    continuation.yield(BridgeEvent(type: "log", text: line, level: "raw"))
                }
                group.leave()
            }
            process.terminationHandler = { proc in
                group.notify(queue: .global()) {
                    if proc.terminationStatus != 0 && proc.terminationStatus != 130 {
                        continuation.yield(BridgeEvent(type: "exit", value: Double(proc.terminationStatus)))
                    }
                    continuation.finish()
                }
            }
            do {
                try process.run()
            } catch {
                continuation.yield(BridgeEvent(type: "done", ok: false,
                                               message: "Could not start the CrowSplat core: \(error.localizedDescription)"))
                continuation.finish()
            }
            continuation.onTermination = { [weak self] reason in
                if case .cancelled = reason { self?.cancel() }
            }
        }
    }

    /// SIGTERM: the core stops the running engine and reports "cancelled".
    func cancel() {
        if process.isRunning { process.terminate() }
    }

    private static func readLines(_ handle: FileHandle, _ onLine: (String) -> Void) {
        var buffer = Data()
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { break }
            buffer.append(chunk)
            while let nl = buffer.firstIndex(of: 0x0A) {
                let line = String(decoding: buffer[buffer.startIndex..<nl], as: UTF8.self)
                buffer.removeSubrange(buffer.startIndex...nl)
                if !line.trimmingCharacters(in: .whitespaces).isEmpty { onLine(line) }
            }
        }
        if !buffer.isEmpty { onLine(String(decoding: buffer, as: UTF8.self)) }
    }
}
