import ImageIO
import Photos
import SwiftUI

/// Pictures stored on the Pi, newest first. A JPEG and its NEF are one picture; the JPEG is what shows.
struct ShotsView: View {
    @Environment(Pi.self) private var pi
    @State private var open: Picture?
    @State private var auroraOnly = false
    @State private var includeRaw = UserDefaults.standard.bool(forKey: "includeRaw")
    @State private var saving: String?

    struct Picture: Identifiable, Hashable {
        var id: String { stem }
        let stem: String
        var jpg: String?
        var nef: String?
        var mtime: Double
        var aurora: Double = 0
        var names: [String] { [jpg, nef].compactMap { $0 } }
        var isMovie: Bool { jpg?.lowercased().hasSuffix(".mp4") == true }
    }

    private var pictures: [Picture] {
        var m: [String: Picture] = [:]
        for s in pi.shots {
            let stem = (s.name as NSString).deletingPathExtension
            var p = m[stem] ?? Picture(stem: stem, mtime: s.mtime ?? 0)
            let ext = (s.name as NSString).pathExtension.lowercased()
            if ext == "jpg" || ext == "jpeg" { p.jpg = s.name } else if ext == "nef" { p.nef = s.name } else if p.jpg == nil { p.jpg = s.name }
            p.mtime = max(p.mtime, s.mtime ?? 0)
            p.aurora = max(p.aurora, s.aurora ?? 0)
            m[stem] = p
        }
        return m.values.sorted { $0.mtime > $1.mtime }
    }

    private var shown: [Picture] { auroraOnly ? pictures.filter { $0.aurora >= 2 } : pictures }

    var body: some View {
        NavigationStack {
            ScrollView {
                photosReminder
                // The count lives in the page: a phone's top bar shrinks toolbar text to a dot.
                HStack {
                    Text("\(pictures.count) pictures on the Pi").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if pictures.contains(where: { $0.aurora >= 2 }) {
                        Toggle(isOn: $auroraOnly) { Label("Aurora only", systemImage: "sparkles") }
                            .toggleStyle(.button).font(.caption).controlSize(.small)
                    }
                }
                .padding(.horizontal, 8)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 6)], spacing: 6) {
                    ForEach(shown) { p in
                        Button { open = p } label: { Thumb(name: p.isMovie ? nil : p.jpg, movie: p.isMovie)
                            .overlay(alignment: .bottomTrailing) {
                                if p.nef != nil { Text("RAW").font(.caption2.bold()).padding(3).background(.black.opacity(0.6)).foregroundStyle(.white).padding(4) }
                            }
                            .overlay(alignment: .topLeading) {
                                if p.aurora >= 2 { Image(systemName: "sparkles").font(.caption.bold()).padding(4).background(.green.opacity(0.8), in: .circle).foregroundStyle(.black).padding(4) }
                            }
                            .overlay(alignment: .topTrailing) {
                                if !pi.inPhotos.contains(p.stem) { Circle().fill(.yellow).frame(width: 9, height: 9).padding(6) }
                            }
                        }
                    }
                }
                .padding(6)
                if pictures.isEmpty { Text("No pictures on the Pi yet.").foregroundStyle(.secondary).padding() }
            }
            .navigationTitle("Shots")
            .refreshable { await pi.loadShots() }
            .task { await pi.loadShots() }
            .fullScreenCover(item: $open) { ShotViewer(pictures: shown, start: $0) }
        }
    }

    /// The big reminder: pictures on the Pi that aren't in this phone's Photos library yet.
    @ViewBuilder private var photosReminder: some View {
        let waiting = pictures.filter { !pi.inPhotos.contains($0.stem) }
        if !waiting.isEmpty || saving != nil {
            VStack(alignment: .leading, spacing: 8) {
                Label(saving ?? "\(waiting.count) new \(waiting.count == 1 ? "picture isn't" : "pictures aren't") in your Photos library yet",
                      systemImage: "photo.badge.exclamationmark").font(.headline)
                Text("They're only on the Pi until you save them. Yellow dots mark which.").font(.caption).foregroundStyle(.secondary)
                Toggle("Include RAW (NEF) files", isOn: $includeRaw).font(.subheadline)
                    .onChange(of: includeRaw) { _, v in UserDefaults.standard.set(v, forKey: "includeRaw") }
                HStack {
                    Button { Task { await saveAll(waiting) } } label: {
                        Label("Save all to Photos", systemImage: "square.and.arrow.down").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent).tint(.yellow).foregroundStyle(.black).disabled(saving != nil)
                    Menu {
                        Button("They're already in Photos") { pi.markInPhotos(waiting.map(\.stem)) }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
            .padding()
            .background(Color.yellow.opacity(0.15), in: .rect(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(.yellow.opacity(0.6)))
            .padding(.horizontal, 6)
        }
    }

    private func saveAll(_ list: [Picture]) async {
        guard await PhotoSaver.authorized() else { saving = nil; pi.lastError = "Allow adding to Photos in Settings."; return }
        for (i, p) in list.reversed().enumerated() {        // oldest first, so Photos keeps them in shooting order
            saving = "Saving \(i + 1) of \(list.count)…"
            if await PhotoSaver.save(p, pi: pi, includeRaw: includeRaw) { pi.markInPhotos([p.stem]) }
        }
        saving = nil
    }
}

/// Copies pictures (JPEG, optionally its NEF as the RAW half of a pair) and movies from the Pi into Photos.
enum PhotoSaver {
    static func authorized() async -> Bool {
        let s = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        return s == .authorized || s == .limited
    }

    @MainActor static func save(_ p: ShotsView.Picture, pi: Pi, includeRaw: Bool) async -> Bool {
        if p.isMovie, let name = p.jpg {
            guard let d = await pi.data(pi.shotURL(name)) else { return false }
            let tmp = FileManager.default.temporaryDirectory.appending(path: name)
            guard (try? d.write(to: tmp)) != nil else { return false }
            defer { try? FileManager.default.removeItem(at: tmp) }
            return (try? await PHPhotoLibrary.shared().performChanges {
                PHAssetCreationRequest.forAsset().addResource(with: .video, fileURL: tmp, options: nil)
            }) != nil
        }
        let jpg: Data? = if let j = p.jpg { await pi.data(pi.shotURL(j)) } else { nil }
        let nef: Data? = if includeRaw || jpg == nil, let n = p.nef { await pi.data(pi.shotURL(n)) } else { nil }
        guard jpg != nil || nef != nil else { return false }
        return (try? await PHPhotoLibrary.shared().performChanges {
            let r = PHAssetCreationRequest.forAsset()
            if let jpg {
                r.addResource(with: .photo, data: jpg, options: nil)
                if let nef { r.addResource(with: .alternatePhoto, data: nef, options: nil) }
            } else if let nef {
                r.addResource(with: .photo, data: nef, options: nil)
            }
        }) != nil
    }
}

struct Thumb: View {
    @Environment(Pi.self) private var pi
    let name: String?
    var movie = false
    @State private var image: UIImage?

    var body: some View {
        Color.secondary.opacity(0.15)
            .aspectRatio(1, contentMode: .fit)
            .overlay { if let image { Image(uiImage: image).resizable().scaledToFill() } else { Image(systemName: movie ? "film" : "photo").foregroundStyle(.secondary) } }
            .clipped()
            .task(id: name) {
                // Full JPEGs are large; decode a small version once.
                guard let name, let d = await pi.data(pi.shotURL(name)) else { return }
                image = UIImage(data: d)?.preparingThumbnail(of: CGSize(width: 300, height: 300))
            }
    }
}

/// Full-screen pictures: swipe left and right through the set; EXIF under each picture.
struct ShotViewer: View {
    @Environment(Pi.self) private var pi
    @Environment(\.dismiss) private var dismiss
    let pictures: [ShotsView.Picture]
    let start: ShotsView.Picture
    @State private var current: String = ""
    @State private var confirmDelete = false
    @State private var message: String?
    @State private var loaded: [String: Data] = [:]

    private var picture: ShotsView.Picture { pictures.first { $0.id == current } ?? start }

    var body: some View {
        NavigationStack {
            TabView(selection: $current) {
                ForEach(pictures) { p in
                    ShotPage(picture: p) { d in loaded[p.id] = d }.tag(p.id)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .background(.black)
            .navigationTitle(picture.stem).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .bottomBar) {
                    Button { save() } label: { Label("Save to Photos", systemImage: "square.and.arrow.down") }.disabled(loaded[current] == nil)
                    if let d = loaded[current], let img = UIImage(data: d) {
                        ShareLink(item: Image(uiImage: img), preview: SharePreview(picture.stem, image: Image(uiImage: img)))
                    }
                    Spacer()
                    if let message { Text(message).font(.caption) }
                    Spacer()
                    Button(role: .destructive) { confirmDelete = true } label: { Label("Delete", systemImage: "trash") }
                }
            }
            .confirmationDialog("Delete this picture from the Pi?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete \(picture.names.joined(separator: " + "))", role: .destructive) {
                    Task { await pi.deleteShots(picture.names); dismiss() }
                }
            } message: { Text("The camera card is not changed.") }
            .onAppear { current = start.id }
            .onChange(of: current) { _, _ in message = nil }
        }
    }

    private func save() {
        guard let data = loaded[current] else { return }
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
            guard status == .authorized || status == .limited else {
                Task { @MainActor in message = "Allow adding to Photos in Settings." }; return
            }
            PHPhotoLibrary.shared().performChanges({
                PHAssetCreationRequest.forAsset().addResource(with: .photo, data: data, options: nil)
            }) { ok, err in Task { @MainActor in
                message = ok ? "Saved to Photos" : (err?.localizedDescription ?? "Couldn't save")
                if ok { pi.markInPhotos([current]) }
            } }
        }
    }
}

/// One picture in the viewer: the image (pinch is iOS's own in a ScrollView) and its EXIF below.
struct ShotPage: View {
    @Environment(Pi.self) private var pi
    let picture: ShotsView.Picture
    var onLoad: (Data) -> Void
    @State private var image: UIImage?
    @State private var exif: [(String, String)] = []
    @State private var note: String?

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                Group {
                    if let image { Image(uiImage: image).resizable().scaledToFit() }
                    else if let note { Text(note).foregroundStyle(.secondary).padding(40) }
                    else { ProgressView().frame(height: 300) }
                }
                if !exif.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(exif, id: \.0) { k, v in
                            HStack(alignment: .top) {
                                Text(k).foregroundStyle(.secondary).frame(width: 120, alignment: .leading)
                                Text(v).textSelection(.enabled)
                                Spacer(minLength: 0)
                            }
                            .font(.footnote)
                        }
                    }
                    .padding(14)
                    .background(Color(white: 0.12), in: .rect(cornerRadius: 12))
                    .padding(.horizontal)
                }
            }
            .padding(.bottom, 20)
        }
        .foregroundStyle(.white)
        .task(id: picture.id) {
            guard let jpg = picture.jpg else { note = "RAW only (\(picture.nef ?? "")). Save the NEF from the Pi's web page."; return }
            guard let d = await pi.data(pi.shotURL(jpg)) else { note = "Couldn't load \(jpg)."; return }
            image = UIImage(data: d)
            exif = Exif.rows(d, names: picture.names)
            onLoad(d)
        }
    }
}

/// Camera, lens and exposure from a JPEG's EXIF/TIFF/GPS blocks, in the order a photographer reads them.
enum Exif {
    static func rows(_ data: Data, names: [String]) -> [(String, String)] {
        guard let src = CGImageSourceCreateWithData(data as CFData, nil),
              let p = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] else { return [] }
        let e = p[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
        let t = p[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]
        let g = p[kCGImagePropertyGPSDictionary] as? [CFString: Any] ?? [:]
        var out: [(String, String)] = []
        func add(_ k: String, _ v: String?) { if let v, !v.isEmpty { out.append((k, v)) } }
        add("Taken", (e[kCGImagePropertyExifDateTimeOriginal] as? String).map(prettyDate))
        add("Camera", [t[kCGImagePropertyTIFFMake] as? String, t[kCGImagePropertyTIFFModel] as? String].compactMap { $0 }.joined(separator: " "))
        add("Lens", e[kCGImagePropertyExifLensModel] as? String)
        if let f = e[kCGImagePropertyExifFocalLength] as? Double {
            let eq = e[kCGImagePropertyExifFocalLenIn35mmFilm] as? Int
            add("Focal length", "\(trim(f)) mm" + (eq.map { " (\($0) mm full-frame)" } ?? ""))
        }
        add("Aperture", (e[kCGImagePropertyExifFNumber] as? Double).map { "f/\(trim($0))" })
        add("Shutter", (e[kCGImagePropertyExifExposureTime] as? Double).map(shutter))
        add("ISO", ((e[kCGImagePropertyExifISOSpeedRatings] as? [Int])?.first).map { "\($0)" })
        add("Exposure comp.", (e[kCGImagePropertyExifExposureBiasValue] as? Double).map { $0 == 0 ? "0 EV" : String(format: "%+.1f EV", $0) })
        add("Mode", (e[kCGImagePropertyExifExposureProgram] as? Int).map { ["Not set", "Manual", "Program", "Aperture priority", "Shutter priority", "Creative", "Action", "Portrait", "Landscape"][safe: $0] ?? "\($0)" })
        add("Metering", (e[kCGImagePropertyExifMeteringMode] as? Int).map { [0: "Unknown", 1: "Average", 2: "Center-weighted", 3: "Spot", 4: "Multi-spot", 5: "Matrix", 6: "Partial"][$0] ?? "\($0)" })
        add("White balance", (e[kCGImagePropertyExifWhiteBalance] as? Int).map { $0 == 0 ? "Auto" : "Manual" })
        add("Flash", (e[kCGImagePropertyExifFlash] as? Int).map { $0 & 1 == 1 ? "Fired" : "Off" })
        if let w = p[kCGImagePropertyPixelWidth] as? Int, let h = p[kCGImagePropertyPixelHeight] as? Int {
            add("Size", "\(w) × \(h) (\(String(format: "%.1f", Double(w * h) / 1_000_000)) MP)")
        }
        if let lat = g[kCGImagePropertyGPSLatitude] as? Double, let lon = g[kCGImagePropertyGPSLongitude] as? Double {
            let ns = (g[kCGImagePropertyGPSLatitudeRef] as? String) ?? "N", ew = (g[kCGImagePropertyGPSLongitudeRef] as? String) ?? "W"
            add("Location", String(format: "%.5f %@, %.5f %@", lat, ns, lon, ew))
        }
        add("Files", names.joined(separator: " + "))
        return out
    }

    private static func trim(_ v: Double) -> String { v == v.rounded() ? String(Int(v)) : String(format: "%.1f", v) }
    private static func shutter(_ s: Double) -> String { s >= 1 ? "\(trim(s)) s" : "1/\(Int((1 / s).rounded())) s" }
    private static func prettyDate(_ s: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy:MM:dd HH:mm:ss"
        guard let d = f.date(from: s) else { return s }
        return d.formatted(date: .abbreviated, time: .shortened)
    }
}

extension Array { subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil } }
