import A2UISwiftUI
import SwiftUI

/// Demo host for the A2UI renderer.
///
/// Not part of the Swift package — SwiftPM can't build an iOS app target. Drop
/// these three files into an Xcode app target that depends on A2UIKit (see
/// ios/README.md).
@main
struct A2UIDemoApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                ChatView()
                    .tabItem { Label("Chat", systemImage: "bubble.left.and.bubble.right") }
                FixtureGalleryView()
                    .tabItem { Label("Fixtures", systemImage: "square.grid.2x2") }
            }
        }
    }
}

/// The catalog the demo renders with.
///
/// Swap in the design system here and nowhere else:
///
///     var vds = A2UICatalog()
///     vds.register("Button") { context in
///         VDSButton(context.textContent ?? "") { context.performAction() }
///     }
///     let appCatalog = A2UICatalog.standard.overlaying(vds)
enum DemoCatalog {
    static let shared = A2UICatalog.standard
}
