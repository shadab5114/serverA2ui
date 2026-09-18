import A2UIClient
import A2UICore
import A2UISwiftUI
import SwiftUI

/// The iOS counterpart of client/src/Chat.tsx: streams a turn from the AG-UI
/// endpoint and renders text and generated surfaces in the same transcript.
struct ChatView: View {
    private struct Turn: Identifiable {
        let id = UUID()
        let role: Role
        var text: String = ""
        var surfaceIds: [String] = []
        var status: String?

        enum Role { case user, assistant }
    }

    @StateObject private var processor = A2UIMessageProcessor()
    @StateObject private var dispatcher = A2UIDispatcher()
    @State private var turns: [Turn] = []
    @State private var input = ""
    @State private var streaming = false
    @State private var error: String?
    @State private var threadId = "thread_\(UUID().uuidString)"

    /// localhost resolves to the host Mac from the simulator. A physical device
    /// needs the Mac's LAN address, and plain HTTP needs an ATS exception —
    /// see ios/README.md.
    private let client = AGUIClient(baseURL: URL(string: "http://localhost:8090")!)

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                transcript
                composer
            }
            .navigationTitle("A2UI Chat")
            .toolbar {
                Button("New") { newChat() }.disabled(streaming)
            }
            .onAppear {
                dispatcher.onCheckFailed = { error = $0 }
                dispatcher.onEvent = { event in
                    // Phase 5 (userAction round-trip) is not built on the server
                    // yet; surfacing the resolved event proves the wiring works.
                    error = "action \(event.name) fired — server round-trip is Phase 5"
                }
            }
        }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    if turns.isEmpty {
                        Text(
                            "Chat, or ask for UI — e.g. “show me a sign-up form with name, email and a submit button”."
                        )
                        .foregroundColor(.secondary)
                        .padding()
                    }
                    ForEach(turns) { turn in
                        bubble(turn).id(turn.id)
                    }
                    if let error {
                        Text(error)
                            .font(.footnote)
                            .foregroundColor(.red)
                    }
                }
                .padding()
            }
            .onChange(of: turns.count) { _ in
                if let last = turns.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }

    @ViewBuilder
    private func bubble(_ turn: Turn) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(turn.role == .user ? "You" : "Assistant")
                .font(.caption).foregroundColor(.secondary)

            if !turn.text.isEmpty {
                Text(turn.text)
            } else if let status = turn.status {
                Text(status).foregroundColor(.secondary).italic()
            }

            ForEach(turn.surfaceIds, id: \.self) { surfaceId in
                if let surface = processor.surfaces[surfaceId] {
                    A2UISurfaceView(
                        surface: surface,
                        catalog: DemoCatalog.shared,
                        dispatcher: dispatcher
                    )
                    .padding(12)
                    .background(Color.secondary.opacity(0.06))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var composer: some View {
        HStack {
            TextField("Type a message, or describe a UI…", text: $input)
                .textFieldStyle(.roundedBorder)
                .disabled(streaming)
                .onSubmit(send)
            Button("Send", action: send)
                .disabled(streaming || input.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding()
    }

    private func send() {
        let text = input.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, !streaming else { return }
        input = ""
        error = nil
        turns.append(Turn(role: .user, text: text))
        turns.append(Turn(role: .assistant))
        streaming = true

        // @MainActor explicitly: the stream is consumed off the caller's context
        // and every branch here touches @State and the processor's @Published
        // surfaces.
        Task { @MainActor in
            do {
                for try await event in client.run(threadId: threadId, message: text) {
                    apply(event)
                }
            } catch {
                self.error = error.localizedDescription
            }
            streaming = false
        }
    }

    private func apply(_ event: AGUIEvent) {
        guard var turn = turns.last, turn.role == .assistant else { return }
        switch event {
        case .textDelta(let delta):
            turn.text += delta
            turn.status = nil
        case .status(let text):
            turn.status = text
        case .a2ui(let messages):
            // Each turn gets its own surface id — the generator always names its
            // surface "main", so without this every bubble would re-render the
            // newest UI.
            let surfaceId = "surface_\(UUID().uuidString)"
            processor.process(
                A2UIMessageProcessor.rewritingSurfaceId(messages, to: surfaceId))
            turn.surfaceIds.append(surfaceId)
            turn.status = nil
        case .runError(let message):
            error = message
        case .runStarted, .textStart, .textEnd, .runFinished:
            return
        }
        turns[turns.count - 1] = turn
    }

    private func newChat() {
        processor.removeAllSurfaces()
        turns.removeAll()
        error = nil
        threadId = "thread_\(UUID().uuidString)"
    }
}
