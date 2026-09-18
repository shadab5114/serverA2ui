import A2UICore
import SwiftUI

/// The four layout primitives the server borrows from the A2UI basic catalog
/// because the design system has no generic container.
///
/// These MUST stay in sync with `BASIC_LAYOUT_COMPONENTS` in
/// src/basicLayoutCatalog.js — that file is what teaches the model they exist.
enum LayoutComponents {
    static func register(into catalog: inout A2UICatalog) {
        catalog.register("Column", view: ColumnView.init)
        catalog.register("Row", view: RowView.init)
        catalog.register("List", view: ListView.init)
        catalog.register("Divider", view: DividerView.init)
    }
}

/// How a container distributes children along its main axis.
private enum Justify: String {
    case start, center, end, spaceBetween, spaceAround, spaceEvenly, stretch
}

/// How a container aligns children across its cross axis.
private enum CrossAlign: String {
    case start, center, end, stretch
}

extension A2UIComponentContext {
    /// Children as a concrete array, so a container can interleave spacers.
    /// Empty for text or template children — those have no per-child layout.
    fileprivate var childViews: [AnyView] {
        guard case .references(let references) = children else { return [] }
        return references.map { AnyView(childView($0.id, basePath: $0.basePath)) }
    }

    fileprivate var justify: Justify {
        Justify(rawValue: string("justify") ?? "") ?? .start
    }

    fileprivate var crossAlign: CrossAlign {
        CrossAlign(rawValue: string("align") ?? "") ?? .stretch
    }
}

/// Lays children out with leading/interleaved/trailing spacers to approximate
/// the flexbox `justify-content` the catalog schema describes.
@ViewBuilder
private func justified(_ views: [AnyView], _ justify: Justify) -> some View {
    let interleave = justify == .spaceBetween || justify == .spaceAround || justify == .spaceEvenly
    let leading = justify == .center || justify == .end || justify == .spaceAround
        || justify == .spaceEvenly
    let trailing = justify == .center || justify == .start || justify == .spaceAround
        || justify == .spaceEvenly

    if leading { Spacer(minLength: 0) }
    ForEach(views.indices, id: \.self) { index in
        views[index]
        if interleave && index < views.count - 1 {
            Spacer(minLength: 0)
        }
    }
    if trailing { Spacer(minLength: 0) }
}

struct ColumnView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let alignment: HorizontalAlignment
        switch context.crossAlign {
        case .start, .stretch: alignment = .leading
        case .center: alignment = .center
        case .end: alignment = .trailing
        }
        let views = context.childViews

        VStack(alignment: alignment, spacing: 12) {
            if views.isEmpty {
                context.childrenView()
            } else {
                justified(views, context.justify)
            }
        }
        .frame(
            maxWidth: context.crossAlign == .stretch ? .infinity : nil,
            alignment: Alignment(horizontal: alignment, vertical: .center))
    }
}

struct RowView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let alignment: VerticalAlignment
        switch context.crossAlign {
        case .start: alignment = .top
        case .center, .stretch: alignment = .center
        case .end: alignment = .bottom
        }
        let views = context.childViews

        HStack(alignment: alignment, spacing: 12) {
            if views.isEmpty {
                context.childrenView()
            } else {
                justified(views, context.justify)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ListView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let horizontal = context.string("direction") == "horizontal"
        // A plain ScrollView + stack, not SwiftUI's `List`: generated surfaces
        // nest these inside other containers, where `List` brings its own
        // scrolling, insets and separators and fights the layout.
        ScrollView(horizontal ? .horizontal : .vertical) {
            if horizontal {
                HStack(alignment: .top, spacing: 12) { context.childrenView() }
            } else {
                VStack(alignment: .leading, spacing: 12) { context.childrenView() }
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

struct DividerView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        if context.string("axis") == "vertical" {
            Divider().frame(maxHeight: .infinity)
        } else {
            Divider()
        }
    }
}
