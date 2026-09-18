import Foundation

/// RFC 6901 JSON Pointer read/write over `JSONValue`.
///
/// A2UI bindings are JSON Pointers (`/form/email`, `/products/0/name`). Two
/// deviations from strict RFC 6901, both required to match the server:
///
/// - `"/"` means the WHOLE document (the server's `updateDataModel` uses
///   `path: "/"` to replace the entire model), not the empty-string key.
/// - A pointer with no leading `/` is RELATIVE and resolves against a base
///   path. List templates rely on this: inside `{ path: "/products",
///   componentId: "tile" }` the tile binds `{ path: "name" }`, which must
///   resolve to `/products/0/name` for the first row.
public enum JSONPointer {
    /// Unescaped path segments. `""` and `"/"` both mean the whole document.
    public static func tokens(_ pointer: String) -> [String] {
        if pointer.isEmpty || pointer == "/" { return [] }
        var path = pointer
        if path.hasPrefix("/") { path.removeFirst() }
        return path.split(separator: "/", omittingEmptySubsequences: false).map {
            // ~1 before ~0, per RFC 6901 — the other order corrupts "~01".
            $0.replacingOccurrences(of: "~1", with: "/")
                .replacingOccurrences(of: "~0", with: "~")
        }
    }

    /// Absolute form of `path`. Absolute pointers are returned unchanged;
    /// relative ones are appended to `basePath`.
    public static func resolve(_ path: String, relativeTo basePath: String) -> String {
        if path.hasPrefix("/") { return path }
        if path.isEmpty { return basePath }
        let base = (basePath == "/" || basePath.isEmpty) ? "" : basePath
        return base + "/" + path
    }

    public static func get(_ pointer: String, from root: JSONValue) -> JSONValue? {
        var current = root
        for token in tokens(pointer) {
            switch current {
            case .object(let dict):
                guard let next = dict[token] else { return nil }
                current = next
            case .array(let array):
                guard let index = Int(token), index >= 0, index < array.count else { return nil }
                current = array[index]
            default:
                return nil
            }
        }
        return current
    }

    /// Writes `newValue` at `pointer`, creating intermediate objects as needed.
    /// A numeric token one past the end of an array appends.
    public static func set(_ pointer: String, to newValue: JSONValue, in root: inout JSONValue) {
        let path = tokens(pointer)
        if path.isEmpty {
            root = newValue
            return
        }
        setTokens(path[...], to: newValue, in: &root)
    }

    private static func setTokens(
        _ tokens: ArraySlice<String>, to newValue: JSONValue, in value: inout JSONValue
    ) {
        guard let token = tokens.first else {
            value = newValue
            return
        }
        let rest = tokens.dropFirst()

        switch value {
        case .object(var dict):
            var child = dict[token] ?? .null
            setTokens(rest, to: newValue, in: &child)
            dict[token] = child
            value = .object(dict)

        case .array(var array):
            guard let index = Int(token), index >= 0, index <= array.count else { return }
            if index == array.count {
                var child = JSONValue.null
                setTokens(rest, to: newValue, in: &child)
                array.append(child)
            } else {
                var child = array[index]
                setTokens(rest, to: newValue, in: &child)
                array[index] = child
            }
            value = .array(array)

        default:
            // Nothing (or a scalar) here yet — grow an object to hold the write.
            var child = JSONValue.null
            setTokens(rest, to: newValue, in: &child)
            value = .object([token: child])
        }
    }
}
