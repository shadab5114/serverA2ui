import Foundation

/// One A2UI v0.9 server-to-client message. Each carries `version` plus exactly
/// one message key.
public enum A2UIMessage: Decodable {
    case createSurface(CreateSurface)
    case updateComponents(UpdateComponents)
    case updateDataModel(UpdateDataModel)
    case deleteSurface(DeleteSurface)

    public struct CreateSurface: Decodable {
        public let surfaceId: String
        public let catalogId: String

        public init(surfaceId: String, catalogId: String) {
            self.surfaceId = surfaceId
            self.catalogId = catalogId
        }
    }

    public struct UpdateComponents: Decodable {
        public let surfaceId: String
        public let components: [ComponentModel]

        public init(surfaceId: String, components: [ComponentModel]) {
            self.surfaceId = surfaceId
            self.components = components
        }
    }

    public struct UpdateDataModel: Decodable {
        public let surfaceId: String
        /// JSON Pointer. Absent or "/" means the whole model.
        public let path: String?
        public let value: JSONValue?

        public init(surfaceId: String, path: String?, value: JSONValue?) {
            self.surfaceId = surfaceId
            self.path = path
            self.value = value
        }
    }

    public struct DeleteSurface: Decodable {
        public let surfaceId: String

        public init(surfaceId: String) {
            self.surfaceId = surfaceId
        }
    }

    private enum CodingKeys: String, CodingKey {
        case createSurface, updateComponents, updateDataModel, deleteSurface
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if let value = try container.decodeIfPresent(CreateSurface.self, forKey: .createSurface) {
            self = .createSurface(value)
        } else if let value = try container.decodeIfPresent(
            UpdateComponents.self, forKey: .updateComponents)
        {
            self = .updateComponents(value)
        } else if let value = try container.decodeIfPresent(
            UpdateDataModel.self, forKey: .updateDataModel)
        {
            self = .updateDataModel(value)
        } else if let value = try container.decodeIfPresent(
            DeleteSurface.self, forKey: .deleteSurface)
        {
            self = .deleteSurface(value)
        } else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "No recognized A2UI message key"))
        }
    }

    public var surfaceId: String {
        switch self {
        case .createSurface(let m): return m.surfaceId
        case .updateComponents(let m): return m.surfaceId
        case .updateDataModel(let m): return m.surfaceId
        case .deleteSurface(let m): return m.surfaceId
        }
    }
}

extension A2UIMessage {
    /// Decodes a bare `[message]` array or a `{ "a2ui": [...] }` /
    /// `{ "messages": [...] }` wrapper — the shapes the server and the golden
    /// fixtures actually emit.
    public static func decodeList(from data: Data) throws -> [A2UIMessage] {
        let decoder = JSONDecoder()
        if let list = try? decoder.decode([A2UIMessage].self, from: data) { return list }
        struct Wrapper: Decodable {
            let a2ui: [A2UIMessage]?
            let messages: [A2UIMessage]?
        }
        let wrapper = try decoder.decode(Wrapper.self, from: data)
        guard let list = wrapper.a2ui ?? wrapper.messages else {
            throw DecodingError.dataCorrupted(
                .init(codingPath: [], debugDescription: "No A2UI message list found"))
        }
        return list
    }
}
