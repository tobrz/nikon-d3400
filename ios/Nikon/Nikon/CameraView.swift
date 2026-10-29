import SwiftUI

/// Every setting the body reports (as on the web Menu tab), plus the Pi's status and a link to its own page.
struct CameraView: View {
    @Environment(Pi.self) private var pi
    @Environment(\.openURL) private var openURL
    @State private var search = ""

    var body: some View {
        NavigationStack {
            List {
                Section("Status") {
                    CameraBadge()
                    LabeledContent("Pi", value: pi.host)
                    if let w = pi.status?.wifi {
                        LabeledContent("Wi-Fi", value: w.client_connected == true ? "Joined a network" : w.ap_up == true ? "Access point \(w.ap_ssid ?? "Nikon-D3400")" : "—")
                    }
                    if let r = pi.status?.revision { LabeledContent("Software", value: r) }
                    Button("Open the Pi's web page (Wi-Fi, Place, Guide, updates)") { openURL(pi.base) }
                    Button("Disconnect", role: .destructive) { pi.disconnect() }
                }
                Section {
                    if pi.controls.isEmpty {
                        Button("Read settings from the camera") { Task { await pi.loadControls() } }.disabled(pi.cameraName == nil)
                    }
                    ForEach(filtered) { c in Row(control: c) }
                } header: {
                    HStack { Text("Camera settings"); Spacer(); if pi.busy != nil { ProgressView().controlSize(.small) } }
                }
                if let e = pi.lastError { Text(e).foregroundStyle(.red) }
            }
            .searchable(text: $search, prompt: "Filter settings")
            .navigationTitle("Camera")
            .refreshable { await pi.refreshStatus(); if pi.cameraName != nil { await pi.loadControls() } }
        }
    }

    private var filtered: [Control] {
        let q = search.lowercased()
        return q.isEmpty ? pi.controls : pi.controls.filter { "\($0.name) \($0.path) \($0.current ?? "")".lowercased().contains(q) }
    }

    struct Row: View {
        @Environment(Pi.self) private var pi
        let control: Control
        @State private var text = ""

        var body: some View {
            let c = control
            if c.readonly == true {
                LabeledContent(c.name, value: c.current ?? "")
            } else if let choices = c.choices, !choices.isEmpty {
                Picker(c.name, selection: Binding(get: { c.current ?? "" }, set: { v in Task { await pi.set(c, v) } })) {
                    ForEach(choices, id: \.label) { Text($0.label).tag($0.label) }
                    if !(choices.contains { $0.label == c.current }) { Text(c.current ?? "").tag(c.current ?? "") }
                }
            } else {
                HStack {
                    Text(c.name)
                    TextField(c.current ?? "", text: $text).multilineTextAlignment(.trailing)
                        .onSubmit { Task { await pi.set(c, text) } }
                }
                .onAppear { text = c.current ?? "" }
            }
        }
    }
}
