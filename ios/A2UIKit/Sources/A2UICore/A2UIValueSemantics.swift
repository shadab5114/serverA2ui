import Foundation

/// A2UI's overloaded value shapes.
///
/// The wire reuses plain JSON objects for several distinct meanings, and they
/// are told apart only by which keys are present. Getting this wrong is the
/// classic A2UI renderer bug — e.g. treating a Button's `children: "Sign up"`
/// as a component reference renders an empty button.
extension JSONValue {
    /// A data binding `{ "path": "/form/email" }` — and NOT a child template.
    public var bindingPath: String? {
        guard let object = objectValue,
            let path = object["path"]?.stringValue,
            object["componentId"] == nil
        else { return nil }
        return path
    }

    /// A list template `{ "path": "/products", "componentId": "tile" }`:
    /// repeat `componentId` once per element of the array at `path`.
    public var childTemplate: (path: String, componentId: String)? {
        guard let object = objectValue,
            let path = object["path"]?.stringValue,
            let componentId = object["componentId"]?.stringValue
        else { return nil }
        return (path, componentId)
    }

    /// A static child list: `["a", "b"]` or `[{ "id": "a", "basePath": "/x" }]`.
    public var childReferences: [A2UIChildReference]? {
        guard let array = arrayValue, !array.isEmpty else { return nil }
        var references: [A2UIChildReference] = []
        for element in array {
            if let id = element.stringValue {
                references.append(A2UIChildReference(id: id, basePath: nil))
            } else if let object = element.objectValue, let id = object["id"]?.stringValue {
                references.append(
                    A2UIChildReference(id: id, basePath: object["basePath"]?.stringValue))
            } else {
                return nil  // not a homogeneous child list
            }
        }
        return references
    }

    /// An action value: `{ "event": ... }` or `{ "functionCall": ... }`.
    public var isAction: Bool {
        guard let object = objectValue else { return false }
        return object["event"] != nil || object["functionCall"] != nil
    }
}

public struct A2UIChildReference: Hashable {
    public let id: String
    /// Overrides the data base path for this child's subtree, when present.
    public let basePath: String?

    public init(id: String, basePath: String?) {
        self.id = id
        self.basePath = basePath
    }
}

/// An `event` action, resolved and ready to send back to the agent.
public struct A2UIActionEvent {
    public let surfaceId: String
    public let name: String
    /// Context values with their bindings already resolved against the data model.
    public let context: [String: JSONValue]

    public init(surfaceId: String, name: String, context: [String: JSONValue]) {
        self.surfaceId = surfaceId
        self.name = name
        self.context = context
    }
}

/// A `functionCall` action — handled locally by the renderer, never sent to the
/// agent. Wire shape: `{ "functionCall": { "call": "setData", "args": {…} } }`.
public struct A2UIFunctionCall {
    public let call: String
    public let args: [String: JSONValue]

    public init(call: String, args: [String: JSONValue]) {
        self.call = call
        self.args = args
    }
}
