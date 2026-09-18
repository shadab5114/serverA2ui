import A2UICore
import SwiftUI

/// A component **type** in a catalog. Adopt this when a custom component
/// deserves its own type rather than an inline closure.
///
///     struct VDSButtonComponent: A2UIComponent {
///         static let a2uiName = "Button"
///         let context: A2UIComponentContext
///         init(context: A2UIComponentContext) { self.context = context }
///         var body: some View {
///             VDSButton(context.string("children") ?? "") { context.performAction() }
///         }
///     }
///
///     catalog.register(VDSButtonComponent.self)
public protocol A2UIComponent: View {
    /// The name on the wire — the platform-agnostic catalog name ("Button"),
    /// NOT the Swift type name. This is where a `VDS`-prefixed design system
    /// reconciles with a platform-neutral payload.
    static var a2uiName: String { get }
    init(context: A2UIComponentContext)
}

/// Maps A2UI component names to the SwiftUI views that render them.
///
/// The whole platform difference lives here. The wire stays neutral
/// ("Button", "Badge"); the catalog decides that "Button" means `VDSButton`.
/// Adding a component — design-system or bespoke — is one `register` call and
/// needs no change to the renderer, the server, or the prompt.
public struct A2UICatalog {
    public typealias Builder = (A2UIComponentContext) -> AnyView

    private var builders: [String: Builder]

    /// Rendered when a payload names a component this catalog doesn't have.
    ///
    /// Deliberately visible rather than blank: the payload is platform-neutral,
    /// so the generator can legitimately emit something this platform hasn't
    /// mapped yet. Seeing which name is missing is the point.
    public var fallback: Builder

    public init(
        builders: [String: Builder] = [:],
        fallback: @escaping Builder = { context in
            AnyView(A2UIUnknownComponentView(name: context.model.component))
        }
    ) {
        self.builders = builders
        self.fallback = fallback
    }

    // MARK: - Registration

    public mutating func register(_ name: String, builder: @escaping Builder) {
        builders[name] = builder
    }

    public mutating func register<V: View>(
        _ name: String, view: @escaping (A2UIComponentContext) -> V
    ) {
        builders[name] = { AnyView(view($0)) }
    }

    public mutating func register<C: A2UIComponent>(_ type: C.Type) {
        builders[C.a2uiName] = { AnyView(C(context: $0)) }
    }

    /// Chainable form, for building a catalog in one expression.
    public func registering<V: View>(
        _ name: String, view: @escaping (A2UIComponentContext) -> V
    ) -> A2UICatalog {
        var copy = self
        copy.register(name, view: view)
        return copy
    }

    public func registering<C: A2UIComponent>(_ type: C.Type) -> A2UICatalog {
        var copy = self
        copy.register(type)
        return copy
    }

    /// Merges `other` on top of this catalog — **other wins** on any name
    /// collision. Mirrors the web client's "design system beats the fallback
    /// layout primitives" rule.
    ///
    ///     let catalog = A2UICatalog.standard.overlaying(.vds)
    public func overlaying(_ other: A2UICatalog) -> A2UICatalog {
        var merged = self
        for (name, builder) in other.builders {
            merged.builders[name] = builder
        }
        merged.fallback = other.fallback
        return merged
    }

    // MARK: - Lookup

    public func contains(_ name: String) -> Bool {
        builders[name] != nil
    }

    public var componentNames: [String] {
        builders.keys.sorted()
    }

    public func build(_ context: A2UIComponentContext) -> AnyView {
        (builders[context.model.component] ?? fallback)(context)
    }
}

/// Placeholder for an unmapped component name.
public struct A2UIUnknownComponentView: View {
    public let name: String

    public init(name: String) {
        self.name = name
    }

    public var body: some View {
        Text("Unknown component: \(name)")
            .font(.system(.footnote, design: .monospaced))
            .foregroundColor(.red)
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(Color.red.opacity(0.4), style: StrokeStyle(lineWidth: 1, dash: [4]))
            )
    }
}
