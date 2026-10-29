import Photos
import SwiftUI

/// Pictures stored on the Pi, newest first. A JPEG and its NEF are one picture; the JPEG is what shows.
struct ShotsView: View {
    @Environment(Pi.self) private var pi
    @State private var open: Picture?

    struct Picture: Identifiable, Hashable {
        var id: String { stem }
        let stem: String
        var jpg: String?
        var nef: String?
        var mtime: Double
        var names: [String] { [jpg, nef].compactMap { $0 } }
    }

    private var pictures: [Picture] {
        var m: [String: Picture] = [:]
        for s in pi.shots {
            let stem = (s.name as NSString).deletingPathExtension
            var p = m[stem] ?? Picture(stem: stem, mtime: s.mtime ?? 0)
            let ext = (s.name as NSString).pathExtension.lowercased()
            if ext == "jpg" || ext == "jpeg" { p.jpg = s.name } else if ext == "nef" { p.nef = s.name } else if p.jpg == nil { p.jpg = s.name }
            p.mtime = max(p.mtime, s.mtime ?? 0)
            m[stem] = p
        }
        return m.values.sorted { $0.mtime > $1.mtime }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 6)], spacing: 6) {
                    ForEach(pictures) { p in
                        Button { open = p } label: { Thumb(name: p.jpg) .overlay(alignment: .bottomTrailing) {
                            if p.nef != nil { Text("RAW").font(.caption2.bold()).padding(3).background(.black.opacity(0.6)).foregroundStyle(.white).padding(4) }
                        } }
                    }
                }
                .padding(6)
                if pictures.isEmpty { Text("No pictures on the Pi yet.").foregroundStyle(.secondary).padding() }
            }
            .navigationTitle("Shots")
            .toolbar { ToolbarItem(placement: .topBarLeading) { Text("\(pictures.count) on the Pi").font(.caption).foregroundStyle(.secondary) } }
            .refreshable { await pi.loadShots() }
            .task { await pi.loadShots() }
            .sheet(item: $open) { ShotViewer(picture: $0) }
        }
    }
}

struct Thumb: View {
    @Environment(Pi.self) private var pi
    let name: String?
    @State private var image: UIImage?

    var body: some View {
        Color.secondary.opacity(0.15)
            .aspectRatio(1, contentMode: .fit)
            .overlay { if let image { Image(uiImage: image).resizable().scaledToFill() } else { Image(systemName: "photo").foregroundStyle(.secondary) } }
            .clipped()
            .task(id: name) {
                // Full JPEGs are large; decode a small version once.
                guard let name, let d = await pi.data(pi.shotURL(name)) else { return }
                image = UIImage(data: d)?.preparingThumbnail(of: CGSize(width: 300, height: 300))
            }
    }
}

struct ShotViewer: View {
    @Environment(Pi.self) private var pi
    @Environment(\.dismiss) private var dismiss
    let picture: ShotsView.Picture
    @State private var image: UIImage?
    @State private var data: Data?
    @State private var message: String?
    @State private var confirmDelete = false

    var body: some View {
        NavigationStack {
            VStack {
                if let image { Image(uiImage: image).resizable().scaledToFit() } else { ProgressView() }
                if let message { Text(message).font(.footnote).foregroundStyle(.secondary) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(.black)
            .navigationTitle(picture.stem).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .bottomBar) {
                    Button { save() } label: { Label("Save to Photos", systemImage: "square.and.arrow.down") }.disabled(data == nil)
                    if let image { ShareLink(item: Image(uiImage: image), preview: SharePreview(picture.stem, image: Image(uiImage: image))) }
                    Spacer()
                    Button(role: .destructive) { confirmDelete = true } label: { Label("Delete", systemImage: "trash") }
                }
            }
            .confirmationDialog("Delete this picture from the Pi?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete \(picture.names.joined(separator: " + "))", role: .destructive) {
                    Task { await pi.deleteShots(picture.names); dismiss() }
                }
            } message: { Text("The camera card is not changed.") }
            .task {
                guard let jpg = picture.jpg, let d = await pi.data(pi.shotURL(jpg)) else { message = "This picture is RAW only; save the NEF from the web page."; return }
                data = d; image = UIImage(data: d)
            }
        }
    }

    private func save() {
        guard let data else { return }
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
            guard status == .authorized || status == .limited else {
                Task { @MainActor in message = "Allow adding to Photos in Settings." }; return
            }
            PHPhotoLibrary.shared().performChanges({
                PHAssetCreationRequest.forAsset().addResource(with: .photo, data: data, options: nil)
            }) { ok, err in Task { @MainActor in message = ok ? "Saved to Photos." : (err?.localizedDescription ?? "Couldn't save.") } }
        }
    }
}
