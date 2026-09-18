// swift-tools-version: 5.9
import PackageDescription

// Mirrors the web split: A2UICore <- @a2ui/web_core, A2UISwiftUI <- @a2ui/react.
// A2UICore is Foundation-only so the protocol logic is testable without a
// simulator (and on Linux/Windows toolchains).
let package = Package(
    name: "A2UIKit",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "A2UICore", targets: ["A2UICore"]),
        .library(name: "A2UISwiftUI", targets: ["A2UISwiftUI"]),
        .library(name: "A2UIClient", targets: ["A2UIClient"]),
    ],
    targets: [
        .target(name: "A2UICore"),
        .target(name: "A2UISwiftUI", dependencies: ["A2UICore"]),
        .target(name: "A2UIClient", dependencies: ["A2UICore"]),
        .testTarget(name: "A2UICoreTests", dependencies: ["A2UICore"]),
    ]
)
