import A2UICore
import Foundation

/// One event off the AG-UI SSE stream, already decoded.
public enum AGUIEvent {
    case runStarted
    case textStart
    case textDelta(String)
    case textEnd
    /// A validated surface. The agent emits these as `CUSTOM { name: "a2ui" }`.
    case a2ui([A2UIMessage])
    /// Transient progress note — UI generation is a multi-second silent call.
    case status(String)
    case runError(String)
    case runFinished
}

/// Streams a turn from the AG-UI endpoint (`POST /agui/run`).
///
/// URLSession has no SSE support, so this reads the response as an async byte
/// stream and decodes `data:` lines itself. The server writes one JSON event per
/// frame.
public final class AGUIClient {
    private let endpoint: URL
    private let session: URLSession

    /// - Parameter baseURL: the server root, e.g.
    ///   `http://localhost:8090` — reachable as-is from the iOS simulator.
    ///   A physical device needs the Mac's LAN address instead.
    public init(baseURL: URL, session: URLSession = .shared) {
        self.endpoint = baseURL.appendingPathComponent("agui/run")
        self.session = session
    }

    /// Sends one user message and streams the turn's events.
    ///
    /// Only the newest message goes up: the server restores prior turns from its
    /// checkpointer, keyed by `threadId`. Keep the thread id stable for the life
    /// of a conversation.
    public func run(threadId: String, message: String) -> AsyncThrowingStream<AGUIEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = URLRequest(url: endpoint)
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    request.timeoutInterval = 300
                    request.httpBody = try JSONSerialization.data(withJSONObject: [
                        "threadId": threadId,
                        "runId": "run_\(UUID().uuidString)",
                        "messages": [
                            [
                                "id": "u_\(UUID().uuidString)",
                                "role": "user",
                                "content": message,
                            ]
                        ],
                    ])

                    let (bytes, response) = try await session.bytes(for: request)
                    if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                        throw AGUIClientError.httpStatus(http.statusCode)
                    }

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        guard !payload.isEmpty, let data = payload.data(using: .utf8) else {
                            continue
                        }
                        if let event = Self.decode(data) {
                            continuation.yield(event)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Maps one AG-UI event frame. Unrecognized types are dropped — the protocol
    /// carries lifecycle events this renderer has no use for.
    static func decode(_ data: Data) -> AGUIEvent? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = object["type"] as? String
        else { return nil }

        switch type {
        case "RUN_STARTED":
            return .runStarted
        case "TEXT_MESSAGE_START":
            return .textStart
        case "TEXT_MESSAGE_CONTENT":
            return (object["delta"] as? String).map(AGUIEvent.textDelta)
        case "TEXT_MESSAGE_END":
            return .textEnd
        case "RUN_ERROR":
            return .runError(object["message"] as? String ?? "Run error")
        case "RUN_FINISHED":
            return .runFinished
        case "CUSTOM":
            return decodeCustom(object)
        default:
            return nil
        }
    }

    private static func decodeCustom(_ object: [String: Any]) -> AGUIEvent? {
        let name = object["name"] as? String
        guard let value = object["value"] as? [String: Any] else { return nil }

        switch name {
        case "a2ui":
            guard let list = value["a2ui"],
                let data = try? JSONSerialization.data(withJSONObject: list),
                let messages = try? JSONDecoder().decode([A2UIMessage].self, from: data)
            else { return nil }
            return .a2ui(messages)
        case "status":
            return (value["text"] as? String).map(AGUIEvent.status)
        default:
            return nil
        }
    }
}

public enum AGUIClientError: Error, LocalizedError {
    case httpStatus(Int)

    public var errorDescription: String? {
        switch self {
        case .httpStatus(let code):
            return "AG-UI server returned HTTP \(code). Is it running (npm run agui)?"
        }
    }
}
