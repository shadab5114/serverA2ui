import A2UICore
import SwiftUI

/// What a `children` / `child` property turned out to mean.
///
/// A2UI overloads one key four ways and they are distinguishable only by shape
/// plus a lookup against the surface. See `A2UIComponentContext.children`.
public enum A2UIChildren {
    case none
    /// Literal content — a Button label, a paragraph of text.
    case text(String)
    /// References to other components on this surface.
    case references([A2UIChildReference])
    /// Repeat `componentId` once per element of the array at `path`.
    case template(path: String, componentId: String)
}

/// Everything a component builder needs: its model, its slice of the data
/// model, and the machinery to build children and fire actions.
public struct A2UIComponentContext {
    public let model: ComponentModel
    public let dataContext: DataContext
    public let catalog: A2UICatalog
    public let dispatcher: A2UIDispatcher
    /// Recursion depth, used to stop a malformed cyclic graph from looping.
    public let depth: Int

    public init(
        model: ComponentModel,
        dataContext: DataContext,
        catalog: A2UICatalog,
        dispatcher: A2UIDispatcher,
        depth: Int = 0
    ) {
        self.model = model
        self.dataContext = dataContext
        self.catalog = catalog
        self.dispatcher = dispatcher
        self.depth = depth
    }

    public var surface: A2UISurface { dataContext.surface }

    // MARK: - Properties

    /// The property exactly as it arrived, bindings unresolved.
    public func raw(_ name: String) -> JSONValue? {
        model.properties[name]
    }

    /// The property with bindings replaced by their current values.
    public func resolved(_ name: String) -> JSONValue? {
        guard let value = model.properties[name] else { return nil }
        return dataContext.resolve(value)
    }

    public func string(_ name: String) -> String? {
        resolved(name)?.displayString
    }

    public func bool(_ name: String) -> Bool? {
        resolved(name)?.boolValue
    }

    public func double(_ name: String) -> Double? {
        resolved(name)?.doubleValue
    }

    public func int(_ name: String) -> Int? {
        resolved(name)?.intValue
    }

    /// Decodes a string-valued prop into a design-system enum.
    ///
    /// Catalog props are string enums on the wire (`kind: "primary"`, `size:
    /// "large"`). If the VDS enum is `String`-backed this maps straight across.
    public func enumValue<T: RawRepresentable>(_ name: String, as type: T.Type = T.self) -> T?
    where T.RawValue == String {
        guard let raw = string(name) else { return nil }
        return T(rawValue: raw)
    }

    // MARK: - Two-way binding

    /// A `Binding` over a bound property: reads resolve through the pointer,
    /// writes go back into the data model.
    ///
    /// Simpler than the web renderer, which has to render such fields
    /// uncontrolled and patch changes back. Here the data model IS the source of
    /// truth and SwiftUI re-renders on write.
    ///
    /// Returns nil when the property isn't a binding (a static value can't be
    /// written back) — render it read-only in that case.
    public func binding(_ name: String) -> Binding<JSONValue>? {
        guard let path = model.properties[name]?.bindingPath else { return nil }
        let context = dataContext
        return Binding(
            get: { context.value(at: path) ?? .null },
            set: { context.set(path, $0) }
        )
    }

    public func stringBinding(_ name: String, default defaultValue: String = "") -> Binding<String>?
    {
        guard let base = binding(name) else { return nil }
        return Binding(
            get: { base.wrappedValue.displayString ?? defaultValue },
            set: { base.wrappedValue = .string($0) }
        )
    }

    public func boolBinding(_ name: String, default defaultValue: Bool = false) -> Binding<Bool>? {
        guard let base = binding(name) else { return nil }
        return Binding(
            get: { base.wrappedValue.boolValue ?? defaultValue },
            set: { base.wrappedValue = .bool($0) }
        )
    }

    // MARK: - Children

    /// Interprets `child` / `children` into one of the four A2UI meanings.
    ///
    /// Order matters. A bare string is a component REFERENCE only if it names a
    /// component on this surface, otherwise it is literal text — without that
    /// lookup every `children: "Sign up"` would render an empty button.
    public var children: A2UIChildren {
        if let single = model.properties["child"]?.stringValue {
            return .references([A2UIChildReference(id: single, basePath: nil)])
        }
        guard let value = model.properties["children"] else { return .none }

        if let template = value.childTemplate {
            return .template(path: template.path, componentId: template.componentId)
        }
        if let references = value.childReferences {
            return .references(references)
        }
        if let name = value.stringValue {
            return surface.isComponentId(name)
                ? .references([A2UIChildReference(id: name, basePath: nil)])
                : .text(name)
        }
        if value.bindingPath != nil {
            return dataContext.resolve(value).displayString.map(A2UIChildren.text) ?? .none
        }
        return value.displayString.map(A2UIChildren.text) ?? .none
    }

    /// Literal text content, when `children` is text. Convenience for leaf
    /// components (Text, Button) whose label arrives that way.
    public var textContent: String? {
        if case .text(let text) = children { return text }
        return nil
    }

    /// Renders this component's children, whatever form they took.
    @ViewBuilder
    public func childrenView() -> some View {
        switch children {
        case .none:
            EmptyView()
        case .text(let text):
            Text(text)
        case .references(let references):
            ForEach(references, id: \.id) { reference in
                childView(reference.id, basePath: reference.basePath)
            }
        case .template(let path, let componentId):
            templateView(path: path, componentId: componentId)
        }
    }

    /// One child by id, optionally re-anchoring its data context.
    @ViewBuilder
    public func childView(_ id: String, basePath: String? = nil) -> some View {
        if depth > A2UIComponentContext.maxDepth {
            A2UIUnknownComponentView(name: "<max depth exceeded at \(id)>")
        } else if let child = surface.component(id: id) {
            A2UIComponentView(
                model: child,
                dataContext: basePath.map { dataContext.nested($0) } ?? dataContext,
                catalog: catalog,
                dispatcher: dispatcher,
                depth: depth + 1
            )
        } else {
            A2UIUnknownComponentView(name: "<missing component \(id)>")
        }
    }

    /// One child per element of the bound array, each anchored at its own index
    /// so the template's relative bindings resolve per row.
    @ViewBuilder
    private func templateView(path: String, componentId: String) -> some View {
        let count = dataContext.value(at: path)?.arrayValue?.count ?? 0
        let rowContext = dataContext.nested(path)
        // Array(0..<count), not 0..<count: SwiftUI requires a constant range in
        // the range-based ForEach, and this count changes with the data model.
        ForEach(Array(0..<count), id: \.self) { index in
            if let child = surface.component(id: componentId) {
                A2UIComponentView(
                    model: child,
                    dataContext: rowContext.nested(String(index)),
                    catalog: catalog,
                    dispatcher: dispatcher,
                    depth: depth + 1
                )
            }
        }
    }

    static let maxDepth = 64

    // MARK: - Actions

    public var hasAction: Bool {
        model.properties["action"] != nil
    }

    /// Runs this component's `action`, gated by its sibling `checks`.
    public func performAction() {
        dispatcher.perform(
            action: model.properties["action"],
            checks: model.properties["checks"],
            in: dataContext
        )
    }

    /// A handler for a property whose VALUE is an action (e.g. Modal `onClose`),
    /// as opposed to the component's own `action`. Nil when the prop isn't one.
    public func actionHandler(for name: String) -> (() -> Void)? {
        guard let value = model.properties[name], value.isAction else { return nil }
        let dispatcher = self.dispatcher
        let dataContext = self.dataContext
        return { dispatcher.perform(action: value, checks: nil, in: dataContext) }
    }
}
