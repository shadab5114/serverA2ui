import Combine
import Foundation

/// One rendered A2UI surface: a flat component graph plus the data model its
/// bindings read from.
///
/// Both halves are `@Published`, so a data-model write re-renders the views that
/// observe this surface. That replaces the web renderer's manual
/// subscribe-to-"/" plumbing — SwiftUI's observation does it for free.
///
/// Not thread-safe: mutate on the main thread (`A2UIMessageProcessor` and the
/// SwiftUI views already do; `AGUIClient` hops to the main actor before
/// processing).
public final class A2UISurface: ObservableObject, Identifiable {
    public let id: String
    public let catalogId: String

    /// Components indexed by id. The wire list is flat and unordered — the tree
    /// is discovered by walking child references from "root", so a component may
    /// legitimately be declared before its parent.
    @Published public private(set) var components: [String: ComponentModel] = [:]
    @Published public private(set) var dataModel: JSONValue = .object([:])

    public init(id: String, catalogId: String) {
        self.id = id
        self.catalogId = catalogId
    }

    /// The tree's entry point. A surface without it renders nothing.
    public var rootComponent: ComponentModel? {
        components["root"]
    }

    public func component(id: String) -> ComponentModel? {
        components[id]
    }

    /// True when `name` refers to a component on this surface.
    ///
    /// This is what tells a child REFERENCE apart from literal text: `children:
    /// "signup-form"` is a reference, `children: "Sign up"` is a button label.
    public func isComponentId(_ name: String) -> Bool {
        components[name] != nil
    }

    public func apply(components newComponents: [ComponentModel]) {
        var merged = components
        for model in newComponents {
            merged[model.id] = model
        }
        components = merged
    }

    public func updateData(path: String?, value: JSONValue?) {
        let pointer = path ?? "/"
        let newValue = value ?? .null
        if JSONPointer.tokens(pointer).isEmpty {
            dataModel = newValue
        } else {
            var model = dataModel
            JSONPointer.set(pointer, to: newValue, in: &model)
            dataModel = model
        }
    }

    public func value(at pointer: String, relativeTo basePath: String = "/") -> JSONValue? {
        JSONPointer.get(JSONPointer.resolve(pointer, relativeTo: basePath), from: dataModel)
    }

    public func setValue(
        _ value: JSONValue, at pointer: String, relativeTo basePath: String = "/"
    ) {
        var model = dataModel
        JSONPointer.set(
            JSONPointer.resolve(pointer, relativeTo: basePath), to: value, in: &model)
        dataModel = model
    }
}
