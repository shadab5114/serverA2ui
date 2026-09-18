import A2UICore
import SwiftUI

#if canImport(UIKit)
    import UIKit
#endif

/// Runs A2UI actions.
///
/// An action is either a `functionCall` handled locally by the renderer, or an
/// `event` forwarded to the agent. A sibling `checks` array gates both.
///
/// The function table is open for the same reason the catalog is: a design
/// system can ship its own renderer functions without forking this package.
public final class A2UIDispatcher: ObservableObject {
    public typealias Function = (_ args: [String: JSONValue], _ context: DataContext) -> Void

    private var functions: [String: Function] = [:]

    /// Called with a resolved `event` action — wire this to the AG-UI client to
    /// send it back to the agent.
    public var onEvent: ((A2UIActionEvent) -> Void)?

    /// Called with a failed check's message, so the app can surface it however
    /// it likes (alert, inline error, toast).
    public var onCheckFailed: ((String) -> Void)?

    public init(includeDefaults: Bool = true) {
        if includeDefaults {
            registerDefaults()
        }
    }

    public func register(_ name: String, _ function: @escaping Function) {
        functions[name] = function
    }

    /// The three renderer functions the server's prompt promises the model.
    /// Keep in sync with the "Renderer functions you may call" list in
    /// src/systemPrompt.js.
    private func registerDefaults() {
        register("setData") { args, context in
            guard let path = args["path"]?.stringValue else { return }
            context.set(path, args["value"] ?? .null)
        }
        register("toggleData") { args, context in
            guard let path = args["path"]?.stringValue else { return }
            let current = context.value(at: path)?.boolValue ?? false
            context.set(path, .bool(!current))
        }
        register("openUrl") { args, _ in
            guard let string = args["url"]?.stringValue, let url = URL(string: string) else {
                return
            }
            #if canImport(UIKit)
                UIApplication.shared.open(url)
            #endif
        }
    }

    // MARK: - Running

    public func perform(action: JSONValue?, checks: JSONValue?, in dataContext: DataContext) {
        guard let action else { return }
        guard passes(checks: checks, in: dataContext) else { return }

        if let functionCall = action["functionCall"] {
            runFunctionCall(functionCall, in: dataContext)
        } else if let event = action["event"] {
            runEvent(event, in: dataContext)
        }
    }

    /// Every check must hold or the action is blocked and its message reported.
    private func passes(checks: JSONValue?, in dataContext: DataContext) -> Bool {
        guard let entries = checks?.arrayValue else { return true }
        for entry in entries {
            guard let condition = entry["condition"] else { continue }
            if !A2UIDispatcher.isTruthy(dataContext.resolve(condition)) {
                onCheckFailed?(entry["message"]?.stringValue ?? "Validation failed")
                return false
            }
        }
        return true
    }

    private func runFunctionCall(_ call: JSONValue, in dataContext: DataContext) {
        guard let name = call["call"]?.stringValue else { return }
        guard let function = functions[name] else {
            assertionFailure("A2UI: no renderer function registered for \"\(name)\"")
            return
        }
        let args = (call["args"]?.objectValue ?? [:]).mapValues { dataContext.resolve($0) }
        function(args, dataContext)
    }

    private func runEvent(_ event: JSONValue, in dataContext: DataContext) {
        guard let name = event["name"]?.stringValue else { return }
        // Context values are bindings; the agent needs the values, not the paths.
        let context = (event["context"]?.objectValue ?? [:]).mapValues { dataContext.resolve($0) }
        onEvent?(
            A2UIActionEvent(
                surfaceId: dataContext.surface.id, name: name, context: context))
    }

    static func isTruthy(_ value: JSONValue) -> Bool {
        switch value {
        case .null: return false
        case .bool(let flag): return flag
        case .number(let number): return number != 0
        case .string(let string): return !string.isEmpty
        case .array(let array): return !array.isEmpty
        case .object(let object): return !object.isEmpty
        }
    }
}
