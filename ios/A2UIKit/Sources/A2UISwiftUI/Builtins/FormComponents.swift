import A2UICore
import SwiftUI

/// Form controls — the components that write BACK into the data model.
///
/// Each reads its state through a `Binding` derived from the bound property, so
/// the data model stays the single source of truth and the agent sees current
/// values when an action fires. A control whose state prop is a static value
/// (not a binding) renders read-only rather than silently dropping edits.
enum FormComponents {
    static func register(into catalog: inout A2UICatalog) {
        catalog.register("InputField", view: InputFieldComponentView.init)
        catalog.register("TextArea", view: TextAreaComponentView.init)
        catalog.register("Checkbox", view: CheckboxComponentView.init)
        catalog.register("Toggle", view: ToggleComponentView.init)
    }
}

struct InputFieldComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let type = context.string("type") ?? "text"
        let placeholder = context.string("placeholder") ?? ""
        let binding = context.stringBinding("value")

        VStack(alignment: .leading, spacing: 4) {
            if let label = context.string("label") {
                Text(label).font(.caption).foregroundColor(.secondary)
            }
            if let binding {
                if type == "password" {
                    SecureField(placeholder, text: binding)
                        .textFieldStyle(.roundedBorder)
                } else {
                    TextField(placeholder, text: binding)
                        .textFieldStyle(.roundedBorder)
                        .keyboardTypeIfAvailable(for: type)
                        .autocorrectionDisabled(type == "email")
                }
            } else {
                Text(context.string("value") ?? placeholder)
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                    .background(Color.secondary.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}

struct TextAreaComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let label = context.string("label") {
                Text(label).font(.caption).foregroundColor(.secondary)
            }
            if let binding = context.stringBinding("value") {
                TextEditor(text: binding)
                    .frame(minHeight: 96)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.secondary.opacity(0.3))
                    )
            } else {
                Text(context.string("value") ?? "")
                    .frame(maxWidth: .infinity, minHeight: 96, alignment: .topLeading)
            }
        }
    }
}

struct CheckboxComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        // iOS has no native checkbox; a labelled toggle button is the closest
        // affordance that still reads as a checkbox.
        let binding = context.boolBinding("checked")
        let isOn = binding?.wrappedValue ?? context.bool("checked") ?? false

        Button {
            binding?.wrappedValue.toggle()
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: isOn ? "checkmark.square.fill" : "square")
                    .foregroundColor(isOn ? .accentColor : .secondary)
                Text(context.string("label") ?? context.textContent ?? "")
                    .foregroundColor(.primary)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
        }
        .buttonStyle(.plain)
        .disabled(binding == nil)
    }
}

struct ToggleComponentView: View {
    let context: A2UIComponentContext

    init(_ context: A2UIComponentContext) { self.context = context }

    var body: some View {
        let label = context.string("label") ?? context.string("ariaLabel") ?? ""
        if let binding = context.boolBinding("checked") {
            Toggle(label, isOn: binding)
                .hidingLabels(context.string("label") == nil)
        } else {
            Toggle(label, isOn: .constant(context.bool("checked") ?? false))
                .disabled(true)
                .hidingLabels(context.string("label") == nil)
        }
    }
}

extension View {
    /// `keyboardType` is iOS-only; this keeps the package building for macOS.
    @ViewBuilder
    fileprivate func keyboardTypeIfAvailable(for type: String) -> some View {
        #if os(iOS)
            switch type {
            case "email": self.keyboardType(.emailAddress).textInputAutocapitalization(.never)
            case "number": self.keyboardType(.numberPad)
            case "tel": self.keyboardType(.phonePad)
            case "url": self.keyboardType(.URL)
            default: self
            }
        #else
            self
        #endif
    }

    /// `labelsHidden()` only when the payload gave no visible label.
    @ViewBuilder
    fileprivate func hidingLabels(_ hidden: Bool) -> some View {
        if hidden { self.labelsHidden() } else { self }
    }
}
