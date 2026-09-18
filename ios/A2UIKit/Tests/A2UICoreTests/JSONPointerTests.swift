import XCTest

@testable import A2UICore

final class JSONPointerTests: XCTestCase {
    private let document: JSONValue = .object([
        "form": .object(["email": .string("a@b.c"), "agreed": .bool(false)]),
        "products": .array([
            .object(["name": .string("Bottle"), "price": .number(19.99)]),
            .object(["name": .string("Umbrella"), "price": .number(24.5)]),
        ]),
        "a/b": .string("escaped slash"),
        "m~n": .string("escaped tilde"),
    ])

    func testGetsNestedAndIndexedValues() {
        XCTAssertEqual(JSONPointer.get("/form/email", from: document)?.stringValue, "a@b.c")
        XCTAssertEqual(JSONPointer.get("/products/1/name", from: document)?.stringValue, "Umbrella")
        XCTAssertNil(JSONPointer.get("/products/9/name", from: document))
        XCTAssertNil(JSONPointer.get("/nope", from: document))
    }

    /// A2UI (and the server) use "/" to mean the entire model, which is NOT
    /// strict RFC 6901 — there it would address the empty-string key.
    func testRootPointerIsTheWholeDocument() {
        XCTAssertEqual(JSONPointer.get("/", from: document), document)
        XCTAssertEqual(JSONPointer.get("", from: document), document)
    }

    func testUnescapesTokens() {
        XCTAssertEqual(JSONPointer.get("/a~1b", from: document)?.stringValue, "escaped slash")
        XCTAssertEqual(JSONPointer.get("/m~0n", from: document)?.stringValue, "escaped tilde")
    }

    /// Relative pointers are what make list templates work: the template binds
    /// `{ path: "name" }` and each row anchors it at its own index.
    func testResolvesRelativePathsAgainstBase() {
        XCTAssertEqual(JSONPointer.resolve("name", relativeTo: "/products/0"), "/products/0/name")
        XCTAssertEqual(JSONPointer.resolve("/absolute", relativeTo: "/products/0"), "/absolute")
        XCTAssertEqual(JSONPointer.resolve("name", relativeTo: "/"), "/name")
    }

    func testSetsExistingAndMissingPaths() {
        var value = document
        JSONPointer.set("/form/email", to: .string("z@y.x"), in: &value)
        XCTAssertEqual(JSONPointer.get("/form/email", from: value)?.stringValue, "z@y.x")

        JSONPointer.set("/products/0/price", to: .number(9), in: &value)
        XCTAssertEqual(JSONPointer.get("/products/0/price", from: value)?.doubleValue, 9)

        // Intermediate containers are created on demand.
        JSONPointer.set("/ui/modal/open", to: .bool(true), in: &value)
        XCTAssertEqual(JSONPointer.get("/ui/modal/open", from: value)?.boolValue, true)
    }

    func testSetAtRootReplacesDocument() {
        var value = document
        JSONPointer.set("/", to: .object(["fresh": .bool(true)]), in: &value)
        XCTAssertEqual(value, .object(["fresh": .bool(true)]))
    }

    /// A bound quantity of 3 must render "3", never "3.0".
    func testDisplayStringTrimsWholeNumbers() {
        XCTAssertEqual(JSONValue.number(3).displayString, "3")
        XCTAssertEqual(JSONValue.number(19.99).displayString, "19.99")
        XCTAssertEqual(JSONValue.string("hi").displayString, "hi")
        XCTAssertNil(JSONValue.null.displayString)
    }
}
