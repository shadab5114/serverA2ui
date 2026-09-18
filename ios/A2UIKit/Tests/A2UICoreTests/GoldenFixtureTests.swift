import XCTest

@testable import A2UICore

/// Conformance tests against the golden fixtures in `test/fixtures/`.
///
/// Each asserts a capability the React renderer already has, so "the iOS
/// renderer matches" is a checkable claim rather than an assumption.
final class GoldenFixtureTests: XCTestCase {

    // MARK: - signup-form

    func testSignupFormBuildsItsGraph() throws {
        let surface = try Fixture.surface("signup-form")
        let root = try XCTUnwrap(surface.rootComponent)

        XCTAssertEqual(root.component, "Column")
        XCTAssertEqual(
            root.properties["children"]?.childReferences?.map(\.id),
            ["title", "fullNameField", "emailField", "passwordField", "submitButton"])
    }

    /// The disambiguation that breaks renderers: a `children` string is a
    /// component reference only when it names one.
    func testDistinguishesTextChildrenFromComponentReferences() throws {
        let surface = try Fixture.surface("signup-form")

        let button = try XCTUnwrap(surface.component(id: "submitButton"))
        let label = try XCTUnwrap(button.properties["children"]?.stringValue)
        XCTAssertEqual(label, "Sign up")
        XCTAssertFalse(
            surface.isComponentId(label),
            "\"Sign up\" is a button label, not a component id")

        XCTAssertTrue(surface.isComponentId("title"), "\"title\" IS a component on this surface")
    }

    func testFormFieldsBindIntoTheDataModel() throws {
        let surface = try Fixture.surface("signup-form")
        let context = DataContext(surface: surface)

        let field = try XCTUnwrap(surface.component(id: "emailField"))
        let path = try XCTUnwrap(field.properties["value"]?.bindingPath)
        XCTAssertEqual(path, "/form/email")

        // Seeded empty, then written back the way a bound TextField does.
        XCTAssertEqual(context.value(at: path)?.stringValue, "")
        context.set(path, .string("someone@example.com"))
        XCTAssertEqual(context.value(at: path)?.stringValue, "someone@example.com")
    }

    func testResolvesActionEventContextToValues() throws {
        let surface = try Fixture.surface("signup-form")
        let context = DataContext(surface: surface)
        context.set("/form/email", .string("someone@example.com"))

        let button = try XCTUnwrap(surface.component(id: "submitButton"))
        let action = try XCTUnwrap(button.properties["action"])
        XCTAssertTrue(action.isAction)

        let event = try XCTUnwrap(action["event"])
        XCTAssertEqual(event["name"]?.stringValue, "submit_signup")

        // The agent must receive values, not the pointers they came from.
        let resolved = context.resolve(try XCTUnwrap(event["context"]))
        XCTAssertEqual(resolved["email"]?.stringValue, "someone@example.com")
    }

    // MARK: - product-list

    func testProductListUsesAChildTemplate() throws {
        let surface = try Fixture.surface("product-list")
        let root = try XCTUnwrap(surface.rootComponent)

        let template = try XCTUnwrap(root.properties["children"]?.childTemplate)
        XCTAssertEqual(template.path, "/products")
        XCTAssertEqual(template.componentId, "product-tile")
        XCTAssertNil(
            root.properties["children"]?.bindingPath,
            "a template must not be mistaken for a plain data binding")
    }

    /// The template component is declared BEFORE root in this fixture — the
    /// renderer must index by id rather than assume document order.
    func testComponentsAreIndexedRegardlessOfWireOrder() throws {
        let surface = try Fixture.surface("product-list")
        XCTAssertNotNil(surface.component(id: "product-tile"))
        XCTAssertNotNil(surface.rootComponent)
    }

    func testTemplateRowsResolveRelativeBindings() throws {
        let surface = try Fixture.surface("product-list")
        let rows = DataContext(surface: surface).nested("/products")
        let tile = try XCTUnwrap(surface.component(id: "product-tile"))

        // `title` is a slot object whose inner value is a RELATIVE binding:
        // { "children": { "path": "name" } }
        let title = try XCTUnwrap(tile.properties["title"])

        let first = rows.nested("0").resolve(title)
        XCTAssertEqual(first["children"]?.stringValue, "Everyday Water Bottle")

        let third = rows.nested("2").resolve(title)
        XCTAssertEqual(third["children"]?.stringValue, "Compact Travel Umbrella")
    }

    func testTemplateRowCountComesFromTheDataModel() throws {
        let surface = try Fixture.surface("product-list")
        XCTAssertEqual(surface.value(at: "/products")?.arrayValue?.count, 3)
    }

    // MARK: - settings-panel

    func testTogglesAreTwoWayBound() throws {
        let surface = try Fixture.surface("settings-panel")
        let context = DataContext(surface: surface)

        let toggle = try XCTUnwrap(surface.component(id: "emailToggle"))
        let path = try XCTUnwrap(toggle.properties["checked"]?.bindingPath)
        XCTAssertEqual(context.value(at: path)?.boolValue, false)

        context.set(path, .bool(true))
        XCTAssertEqual(surface.value(at: "/settings/emailAlerts")?.boolValue, true)
    }

    /// `checks` is a SIBLING of `action`, not nested inside it — a renderer that
    /// looks for it in the wrong place silently skips validation.
    func testChecksAreSiblingsOfTheAction() throws {
        let surface = try Fixture.surface("settings-panel")
        let button = try XCTUnwrap(surface.component(id: "saveButton"))

        let checks = try XCTUnwrap(button.properties["checks"]?.arrayValue)
        XCTAssertEqual(checks.count, 1)
        XCTAssertNil(button.properties["action"]?["checks"])

        let condition = try XCTUnwrap(checks[0]["condition"])
        XCTAssertEqual(condition.bindingPath, "/settings/agreeTerms")
        XCTAssertFalse(checks[0]["message"]?.stringValue?.isEmpty ?? true)
    }

    // MARK: - across all fixtures

    func testEveryFixtureHasReachableComponents() throws {
        for name in ["signup-form", "product-list", "settings-panel"] {
            let surface = try Fixture.surface(name)
            XCTAssertNotNil(surface.rootComponent, "\(name) has no root")

            // Every referenced child id must exist, or the surface renders holes.
            for (_, model) in surface.components {
                if let references = model.properties["children"]?.childReferences {
                    for reference in references {
                        XCTAssertNotNil(
                            surface.component(id: reference.id),
                            "\(name): \(model.id) references missing child \(reference.id)")
                    }
                }
                if let template = model.properties["children"]?.childTemplate {
                    XCTAssertNotNil(
                        surface.component(id: template.componentId),
                        "\(name): \(model.id) templates missing component \(template.componentId)")
                }
            }
        }
    }

    /// Each turn must land on its own surface; the generator always says "main".
    func testSurfaceIdRewriteIsolatesTurns() throws {
        let processor = A2UIMessageProcessor()
        let first = try Fixture.load("signup-form").a2ui
        let second = try Fixture.load("product-list").a2ui

        processor.process(A2UIMessageProcessor.rewritingSurfaceId(first, to: "turn_1"))
        processor.process(A2UIMessageProcessor.rewritingSurfaceId(second, to: "turn_2"))

        XCTAssertNil(processor.surfaces["main"])
        XCTAssertEqual(processor.surfaces["turn_1"]?.rootComponent?.component, "Column")
        XCTAssertEqual(processor.surfaces["turn_2"]?.rootComponent?.component, "List")
    }
}
