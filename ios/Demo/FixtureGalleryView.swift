import A2UICore
import A2UISwiftUI
import SwiftUI

/// Renders the golden fixtures straight from the app bundle — no server, no
/// API key, no network.
///
/// This is the fastest way to see the renderer working and the right place to
/// check a newly-registered component: pick the fixture that uses it and look.
///
/// Add `test/fixtures/*.a2ui.json` to the app target's "Copy Bundle Resources"
/// build phase for this to find them.
struct FixtureGalleryView: View {
    private static let names = ["signup-form", "product-list", "settings-panel"]

    @State private var selected = Self.names[0]
    @StateObject private var processor = A2UIMessageProcessor()
    @StateObject private var dispatcher = A2UIDispatcher()
    @State private var lastEvent: String?
    @State private var checkMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Picker("Fixture", selection: $selected) {
                        ForEach(Self.names, id: \.self) { Text($0).tag($0) }
                    }
                    .pickerStyle(.segmented)

                    if let surface = processor.surfaces[selected] {
                        A2UISurfaceView(
                            surface: surface,
                            catalog: DemoCatalog.shared,
                            dispatcher: dispatcher
                        )
                    } else {
                        Text("Could not load \(selected).a2ui.json from the app bundle.")
                            .foregroundColor(.secondary)
                    }

                    if let lastEvent {
                        Text("event → \(lastEvent)")
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                }
                .padding()
            }
            .navigationTitle("Fixtures")
            .onAppear(perform: configure)
            .onChange(of: selected) { _ in load(selected) }
            .alert(
                "Validation",
                isPresented: Binding(
                    get: { checkMessage != nil },
                    set: { if !$0 { checkMessage = nil } }),
                presenting: checkMessage
            ) { _ in
                Button("OK", role: .cancel) {}
            } message: { message in
                Text(message)
            }
        }
    }

    private func configure() {
        dispatcher.onEvent = { event in
            // No server round-trip here — showing that the action fired with
            // resolved values is the point of the offline gallery.
            let pairs = event.context
                .map { "\($0.key)=\($0.value.displayString ?? "—")" }
                .sorted()
                .joined(separator: ", ")
            lastEvent = "\(event.name)(\(pairs))"
        }
        dispatcher.onCheckFailed = { checkMessage = $0 }
        load(selected)
    }

    private func load(_ name: String) {
        guard processor.surfaces[name] == nil else { return }
        guard let url = Bundle.main.url(forResource: "\(name).a2ui", withExtension: "json"),
            let data = try? Data(contentsOf: url)
        else { return }
        struct FixtureFile: Decodable { let a2ui: [A2UIMessage] }
        guard let file = try? JSONDecoder().decode(FixtureFile.self, from: data) else { return }
        // One surface per fixture so switching tabs doesn't overwrite the others.
        processor.process(A2UIMessageProcessor.rewritingSurfaceId(file.a2ui, to: name))
    }
}
