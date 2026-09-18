import Foundation

/// A component's view onto the surface data model, anchored at `basePath`.
///
/// The anchor is what makes list templates work: the template component is
/// declared once, then rendered with a context per row (`/products/0`,
/// `/products/1`, …) so its relative binding `{ path: "name" }` resolves to a
/// different value each time.
public struct DataContext {
    public let surface: A2UISurface
    /// Absolute pointer this context is anchored at. "/" at the surface root.
    public let basePath: String

    public init(surface: A2UISurface, basePath: String = "/") {
        self.surface = surface
        self.basePath = basePath
    }

    /// A context anchored deeper, e.g. `nested("/products").nested("0")`.
    public func nested(_ path: String) -> DataContext {
        DataContext(
            surface: surface, basePath: JSONPointer.resolve(path, relativeTo: basePath))
    }

    public func value(at path: String) -> JSONValue? {
        surface.value(at: path, relativeTo: basePath)
    }

    public func set(_ path: String, _ value: JSONValue) {
        surface.setValue(value, at: path, relativeTo: basePath)
    }

    /// Replaces bindings with their current values, recursing into nested
    /// containers.
    ///
    /// Nested resolution is load-bearing, not defensive: the generator emits
    /// props like `title: { children: { path: "name" } }`, where the binding is
    /// two levels inside the prop value.
    public func resolve(_ value: JSONValue) -> JSONValue {
        if let path = value.bindingPath {
            return self.value(at: path) ?? .null
        }
        switch value {
        case .array(let elements):
            return .array(elements.map { resolve($0) })
        case .object(let fields):
            var resolved: [String: JSONValue] = [:]
            for (key, element) in fields {
                resolved[key] = resolve(element)
            }
            return .object(resolved)
        default:
            return value
        }
    }
}
