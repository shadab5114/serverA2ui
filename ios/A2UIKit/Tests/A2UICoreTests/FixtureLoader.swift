import Foundation
import XCTest

@testable import A2UICore

/// Loads the golden fixtures from `test/fixtures/` at the repo root.
///
/// Read in place rather than copied into the package as SwiftPM resources —
/// duplicating them would defeat the point. The React client and this renderer
/// must be conformance-tested against the same bytes.
enum Fixture {
    static var directory: URL {
        // .../ios/A2UIKit/Tests/A2UICoreTests/FixtureLoader.swift -> repo root
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { url.deleteLastPathComponent() }
        return url.appendingPathComponent("test/fixtures")
    }

    struct File: Decodable {
        let name: String
        let description: String
        let a2ui: [A2UIMessage]
    }

    static func load(_ name: String) throws -> File {
        let url = directory.appendingPathComponent("\(name).a2ui.json")
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(File.self, from: data)
    }

    /// A surface with the fixture's messages already applied.
    static func surface(_ name: String) throws -> A2UISurface {
        let processor = A2UIMessageProcessor()
        processor.process(try load(name).a2ui)
        let surface = try XCTUnwrap(processor.surfaces["main"], "fixture has no \"main\" surface")
        return surface
    }
}
