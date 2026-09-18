import A2UICore
import SwiftUI

extension A2UICatalog {
    /// Built-in components: the four borrowed layout primitives plus plain
    /// SwiftUI stand-ins for the most common design-system components.
    ///
    /// Use it as the base and overlay your design system on top — later
    /// registrations win, so anything you map replaces the stand-in and
    /// anything you haven't mapped yet still renders:
    ///
    ///     var vds = A2UICatalog()
    ///     vds.register("Button") { VDSButton($0.textContent ?? "") { $0.performAction() } }
    ///     vds.register(VDSBadgeComponent.self)
    ///     let catalog = A2UICatalog.standard.overlaying(vds)
    public static var standard: A2UICatalog {
        var catalog = A2UICatalog()
        LayoutComponents.register(into: &catalog)
        ContentComponents.register(into: &catalog)
        FormComponents.register(into: &catalog)
        return catalog
    }
}
