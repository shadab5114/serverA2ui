import Combine
import Foundation

/// Applies A2UI messages to a set of surfaces — the Swift counterpart of
/// `MessageProcessor` from `@a2ui/web_core`.
///
/// Mutate on the main thread.
public final class A2UIMessageProcessor: ObservableObject {
    @Published public private(set) var surfaces: [String: A2UISurface] = [:]
    /// Creation order, so a UI can render surfaces in the order they arrived.
    @Published public private(set) var surfaceOrder: [String] = []

    public var onSurfaceCreated: ((A2UISurface) -> Void)?
    public var onSurfaceDeleted: ((String) -> Void)?

    public init() {}

    public func surface(id: String) -> A2UISurface? {
        surfaces[id]
    }

    public func process(_ messages: [A2UIMessage]) {
        for message in messages {
            process(message)
        }
    }

    public func process(_ message: A2UIMessage) {
        switch message {
        case .createSurface(let payload):
            let surface = A2UISurface(id: payload.surfaceId, catalogId: payload.catalogId)
            surfaces[payload.surfaceId] = surface
            if !surfaceOrder.contains(payload.surfaceId) {
                surfaceOrder.append(payload.surfaceId)
            }
            onSurfaceCreated?(surface)

        case .updateComponents(let payload):
            // Tolerate updates that arrive before their createSurface rather
            // than dropping the components on the floor.
            let surface = existingOrCreated(payload.surfaceId)
            surface.apply(components: payload.components)

        case .updateDataModel(let payload):
            let surface = existingOrCreated(payload.surfaceId)
            surface.updateData(path: payload.path, value: payload.value)

        case .deleteSurface(let payload):
            guard surfaces.removeValue(forKey: payload.surfaceId) != nil else { return }
            surfaceOrder.removeAll { $0 == payload.surfaceId }
            onSurfaceDeleted?(payload.surfaceId)
        }
    }

    public func process(jsonData: Data) throws {
        process(try A2UIMessage.decodeList(from: jsonData))
    }

    public func removeAllSurfaces() {
        let ids = surfaceOrder
        surfaces.removeAll()
        surfaceOrder.removeAll()
        for id in ids { onSurfaceDeleted?(id) }
    }

    private func existingOrCreated(_ id: String) -> A2UISurface {
        if let surface = surfaces[id] { return surface }
        let surface = A2UISurface(id: id, catalogId: "")
        surfaces[id] = surface
        surfaceOrder.append(id)
        onSurfaceCreated?(surface)
        return surface
    }
}

extension A2UIMessageProcessor {
    /// Rewrites every `surfaceId` in a batch to `surfaceId`.
    ///
    /// The generator always names its surface "main", so consecutive turns would
    /// otherwise write to the same surface and every earlier chat bubble would
    /// re-render the newest UI. Chat transcripts must give each turn its own id.
    /// (The React client learned this the hard way — see `normalizeA2ui` in
    /// client/src/Chat.tsx.)
    public static func rewritingSurfaceId(
        _ messages: [A2UIMessage], to surfaceId: String
    ) -> [A2UIMessage] {
        messages.map { message in
            switch message {
            case .createSurface(let m):
                return .createSurface(
                    .init(surfaceId: surfaceId, catalogId: m.catalogId))
            case .updateComponents(let m):
                return .updateComponents(
                    .init(surfaceId: surfaceId, components: m.components))
            case .updateDataModel(let m):
                return .updateDataModel(
                    .init(surfaceId: surfaceId, path: m.path, value: m.value))
            case .deleteSurface:
                return .deleteSurface(.init(surfaceId: surfaceId))
            }
        }
    }
}
