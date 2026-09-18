import A2UICore
import SwiftUI

/// Renders one A2UI surface, starting from its "root" component.
///
/// The SwiftUI counterpart of `<A2uiSurface surface={…} />`.
public struct A2UISurfaceView: View {
    @ObservedObject private var surface: A2UISurface
    private let catalog: A2UICatalog
    private let dispatcher: A2UIDispatcher

    public init(surface: A2UISurface, catalog: A2UICatalog, dispatcher: A2UIDispatcher) {
        self.surface = surface
        self.catalog = catalog
        self.dispatcher = dispatcher
    }

    public var body: some View {
        if let root = surface.rootComponent {
            A2UIComponentView(
                model: root,
                dataContext: DataContext(surface: surface, basePath: "/"),
                catalog: catalog,
                dispatcher: dispatcher,
                depth: 0
            )
        } else {
            // A surface whose components haven't arrived yet, or that the
            // generator wired without a root — visible, not silently blank.
            Text("Surface \"\(surface.id)\" has no root component")
                .font(.footnote)
                .foregroundColor(.secondary)
        }
    }
}

/// Renders a single component by looking its name up in the catalog.
///
/// Observing the surface here is what makes bindings live: any data-model write
/// republishes the surface and every component view re-resolves its props.
public struct A2UIComponentView: View {
    @ObservedObject private var surface: A2UISurface
    private let model: ComponentModel
    private let dataContext: DataContext
    private let catalog: A2UICatalog
    private let dispatcher: A2UIDispatcher
    private let depth: Int

    public init(
        model: ComponentModel,
        dataContext: DataContext,
        catalog: A2UICatalog,
        dispatcher: A2UIDispatcher,
        depth: Int
    ) {
        self.surface = dataContext.surface
        self.model = model
        self.dataContext = dataContext
        self.catalog = catalog
        self.dispatcher = dispatcher
        self.depth = depth
    }

    public var body: some View {
        catalog.build(
            A2UIComponentContext(
                model: model,
                dataContext: dataContext,
                catalog: catalog,
                dispatcher: dispatcher,
                depth: depth
            )
        )
    }
}
