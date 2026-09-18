import A2UICore
import SwiftUI

/// Plain-SwiftUI stand-ins for the design-system components the generator emits
/// most often.
///
/// They exist so a generated surface renders the day you drop this package in,
/// with no design system wired up. Replace them one at a time — registering
/// `"Text"` with a VDS view silently supersedes the stand-in; nothing else
/// changes.
enum ContentComponents {
    static func register(into catalog: inout A2UICatalog) {
        catalog.register("Text", view: TextComponentView.init)
        catalog.register("Button", view: ButtonComponentView.init)
        catalog.register("Badge", view: BadgeComponentView.init)
        catalog.register("Tilelet", view: TileletComponentView.init)
        catalog.register("Image", view: ImageComponentView.init)
    }
}

struct TextComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let font: Font
        switch (context.string("kind"), context.string("size")) {
        case ("title", "xlarge"): font = .largeTitle
        case ("title", "large"): font = .title
        case ("title", _): font = .title2
        case (_, "xlarge"): font = .title3
        case (_, "large"): font = .body
        case (_, "small"): font = .footnote
        default: font = .body
        }

        Text(context.textContent ?? "")
            .font(font)
            .fontWeight(context.bool("bold") == true ? .bold : nil)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ButtonComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let isPrimary = context.string("kind") != "secondary"
        Button(context.textContent ?? "") {
            context.performAction()
        }
        .buttonStyle(.borderedProminent)
        .tint(isPrimary ? .accentColor : .gray)
        .controlSize(context.string("size") == "large" ? .large : .regular)
        .disabled(context.bool("disabled") == true)
    }
}

struct BadgeComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        Text(context.textContent ?? "")
            .font(.caption).bold()
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.accentColor.opacity(0.15))
            .clipShape(Capsule())
    }
}

struct TileletComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    /// `title` and `subtitle` arrive as slot objects — `{ "children": <value> }`
    /// — and the value inside is usually a binding, so read them through the
    /// RESOLVED property.
    private func slot(_ name: String) -> String? {
        guard let value = context.resolved(name) else { return nil }
        return value["children"]?.displayString ?? value.displayString
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let title = slot("title") {
                Text(title).font(.headline)
            }
            if let subtitle = slot("subtitle") {
                Text(subtitle).font(.subheadline).foregroundColor(.secondary)
            }
            switch context.children {
            case .text(let body):
                Text(body).font(.body).foregroundColor(.secondary)
            case .none:
                EmptyView()
            default:
                context.childrenView()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct ImageComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        if let source = context.string("src") ?? context.string("url"),
            let url = URL(string: source)
        {
            AsyncImage(url: url) { image in
                image.resizable().scaledToFit()
            } placeholder: {
                Color.secondary.opacity(0.1)
            }
            .accessibilityLabel(context.string("alt") ?? "")
        } else {
            Color.secondary.opacity(0.1).frame(height: 120)
        }
    }
}
