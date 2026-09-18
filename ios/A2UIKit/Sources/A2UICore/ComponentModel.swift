import Foundation

/// One entry from `updateComponents.components`.
///
/// A2UI puts component props INLINE next to `id`/`component` (there is no
/// `properties` wrapper on the wire), so decoding sweeps every other key into
/// `properties`.
public struct ComponentModel: Decodable {
    public let id: String
    public let component: String
    public let properties: [String: JSONValue]

    public init(id: String, component: String, properties: [String: JSONValue]) {
        self.id = id
        self.component = component
        self.properties = properties
    }

    private struct AnyCodingKey: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: AnyCodingKey.self)
        var id: String?
        var component: String?
        var properties: [String: JSONValue] = [:]

        for key in container.allKeys {
            switch key.stringValue {
            case "id":
                id = try container.decode(String.self, forKey: key)
            case "component":
                component = try container.decode(String.self, forKey: key)
            default:
                properties[key.stringValue] = try container.decode(JSONValue.self, forKey: key)
            }
        }

        guard let component else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "Component is missing \"component\""))
        }
        // `id` is optional in the spec but the generator's validator gate
        // guarantees it (every component is addressable, exactly one is "root").
        guard let id else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "Component \"\(component)\" is missing \"id\""))
        }

        self.id = id
        self.component = component
        self.properties = properties
    }

    public subscript(property: String) -> JSONValue? {
        properties[property]
    }
}
