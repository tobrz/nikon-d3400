import Foundation
import Security
import SwiftUI

// JSON shapes from payload/app/server.py and camera.py.

struct Control: Codable, Identifiable, Hashable {
    var id: String { path }
    let path: String
    var label: String?
    var key: String?
    var type: String?
    var current: String?
    var readonly: Bool?
    var choices: [Choice]?
    struct Choice: Codable, Hashable { var index: String?; var label: String }
    var name: String { (label?.isEmpty == false ? label : nil) ?? key ?? path }
}

struct Shot: Codable, Identifiable, Hashable {
    var id: String { name }
    let name: String
    var size: Int?
    var mtime: Double?
}

struct Jobs: Codable {
    struct Run: Codable { var running: Bool?; var taken: Int?; var count: Int?; var error: String?; var note: String?; var movie: String?
        var triggers: Int?; var downloaded: Int?; var total: Int?; var copied: Int?; var deleted: Int?; var kept: Int? }
    var timelapse: Run?
    var bracket: Run?
    var lightning: Run?
    var offload: Run?
    var anyRunning: Bool { [timelapse, bracket, lightning, offload].contains { $0?.running == true } }
}

struct PiStatus: Codable {
    var gphoto2: Bool?
    var camera: String?
    var jobs: Jobs?
    var revision: String?
    var wifi: Wifi?
    struct Wifi: Codable { var ap_up: Bool?; var client_connected: Bool?; var ssid: String?; var ap_ssid: String? }
}

struct CaptureResult: Codable { var files: [String]?; var shutter: String?; var output: String? }
struct PiError: Codable { var error: String }

enum PiFailure: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let m) = self { return m }; return nil }
}

/// The camera Raspberry Pi: address, password, and every call the app makes.
@MainActor
@Observable
final class Pi {
    var host: String = UserDefaults.standard.string(forKey: "host") ?? "nikon-d3400.local"
    var connected = false
    var status: PiStatus?
    var controls: [Control] = []
    var shots: [Shot] = []
    var lastError: String?
    var busy: String?
    private var password: String = Secrets.read() ?? ""

    var base: URL { URL(string: "http://\(host.trimmingCharacters(in: .whitespaces))")! }
    var cameraName: String? { status?.camera }

    // MARK: connect

    func connect(host: String, password: String) async -> Bool {
        self.host = host.trimmingCharacters(in: .whitespaces)
        self.password = password
        do {
            struct OK: Codable { var ok: Bool? }
            let _: OK = try await send("POST", "api/login", ["password": password])
            UserDefaults.standard.set(self.host, forKey: "host")
            Secrets.save(password)
            connected = true
            lastError = nil
            await refreshStatus()
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    /// At launch: reconnect with the saved address and password. With nothing saved, look for a Pi that still has the
    /// factory password (the page says so in /api/login-info) at the usual addresses and connect to it.
    func resume() async {
        if !password.isEmpty { _ = await connect(host: host, password: password); return }
        for h in [host, "nikon-d3400.local", "192.168.50.1"] {
            struct Info: Codable { var factory: Bool? }
            var req = URLRequest(url: URL(string: "http://\(h)/api/login-info")!)
            req.timeoutInterval = 4
            guard let (d, _) = try? await URLSession.shared.data(for: req), let info = try? JSONDecoder().decode(Info.self, from: d) else { continue }
            if info.factory == true, await connect(host: h, password: "nikon-d3400") { return }
            self.host = h          // found a Pi with its own password: ask for it on the connect screen
            return
        }
    }

    func disconnect() {
        Secrets.delete(); password = ""; connected = false; status = nil
    }

    // MARK: reads

    func refreshStatus() async {
        if let s: PiStatus = try? await get("api/status") { status = s }
    }

    func loadControls() async {
        busy = "Reading the camera's settings…"
        defer { busy = nil }
        do {
            struct R: Codable { var controls: [Control] }
            let r: R = try await get("api/config")
            controls = r.controls
            lastError = nil
        } catch { lastError = error.localizedDescription }
    }

    func loadShots() async {
        struct R: Codable { var shots: [Shot] }
        if let r: R = try? await get("api/shots") { shots = r.shots.sorted { ($0.mtime ?? 0) > ($1.mtime ?? 0) } }
    }

    /// One live-view frame; nil with lastError set when the body refuses.
    func previewFrame() async -> UIImage? {
        do {
            let data = try await raw(URLRequest(url: base.appending(path: "preview.jpg")), timeout: 15)
            return UIImage(data: data)
        } catch { lastError = error.localizedDescription; return nil }
    }

    func shotURL(_ name: String, download: Bool = false) -> URL {
        var c = URLComponents(url: base.appending(path: "shots/\(name)"), resolvingAgainstBaseURL: false)!
        if download { c.queryItems = [URLQueryItem(name: "download", value: "1")] }
        return c.url!
    }

    func data(_ url: URL) async -> Data? { try? await raw(URLRequest(url: url), timeout: 60) }

    /// The control whose key (last path part) is one of these names, e.g. "iso".
    func control(_ keys: String...) -> Control? {
        controls.first { c in keys.contains { k in (c.key ?? c.path.split(separator: "/").last.map(String.init) ?? "") == k } }
    }

    // MARK: writes

    func set(_ c: Control, _ value: String) async {
        do {
            struct R: Codable { var path: String?; var value: String? }
            let _: R = try await send("POST", "api/config", ["path": c.path, "value": value])
            if let i = controls.firstIndex(of: c) { controls[i].current = value }
            lastError = nil
        } catch { lastError = error.localizedDescription }
    }

    /// One picture; returns the files saved on the Pi. A long exposure waits until the shutter closes.
    func capture(seconds: Double?) async -> [String] {
        busy = seconds.map { "Exposing for \(Int($0)) s…" } ?? "Taking the picture…"
        defer { busy = nil }
        do {
            var body: [String: Any] = [:]
            if let seconds { body["seconds"] = seconds }
            let r: CaptureResult = try await send("POST", "api/capture", body, timeout: max(90, (seconds ?? 0) + 60))
            lastError = nil
            await loadShots()
            return r.files ?? []
        } catch { lastError = error.localizedDescription; return [] }
    }

    func focus(_ direction: String) async {
        do { struct R: Codable {}; let _: R = try await send("POST", "api/focus", ["direction": direction]); lastError = nil }
        catch { lastError = error.localizedDescription }
    }

    func start(_ job: String, _ body: [String: Any]) async {
        do { struct R: Codable {}; let _: R = try await send("POST", "api/\(job)/start", body); lastError = nil }
        catch { lastError = error.localizedDescription }
        await refreshStatus()
    }

    func stop(_ job: String) async {
        struct R: Codable {}
        _ = try? await send("POST", "api/\(job)/stop", [:]) as R
        await refreshStatus()
    }

    func deleteShots(_ names: [String]) async {
        struct R: Codable {}
        do { let _: R = try await send("POST", "api/shots/delete", ["names": names]); lastError = nil }
        catch { lastError = error.localizedDescription }
        await loadShots()
    }

    // MARK: HTTP

    private func get<T: Decodable>(_ path: String) async throws -> T {
        try decode(try await raw(URLRequest(url: base.appending(path: path)), timeout: 70))
    }

    private func send<T: Decodable>(_ method: String, _ path: String, _ body: [String: Any], timeout: Double = 70) async throws -> T {
        var req = URLRequest(url: base.appending(path: path))
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try decode(try await raw(req, timeout: timeout))
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw PiFailure.message("Unexpected answer from the Pi.") }
    }

    private func raw(_ req: URLRequest, timeout: Double) async throws -> Data {
        var req = req
        req.timeoutInterval = timeout
        req.cachePolicy = .reloadIgnoringLocalCacheData
        req.setValue(password, forHTTPHeaderField: "X-Nikon-Password")
        let (data, resp): (Data, URLResponse)
        do { (data, resp) = try await URLSession.shared.data(for: req) }
        catch { throw PiFailure.message("Can't reach \(host). Join the Nikon-D3400 Wi-Fi or the same network as the Pi.") }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            if code == 401 { connected = false }
            if let e = try? JSONDecoder().decode(PiError.self, from: data) { throw PiFailure.message(e.error) }
            throw PiFailure.message("The Pi answered \(code).")
        }
        return data
    }
}

/// The page password, in this device's Keychain.
enum Secrets {
    private static let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.tobrz.nikon.pi"]
    static func save(_ s: String) {
        delete()
        var a = q; a[kSecValueData as String] = Data(s.utf8); a[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(a as CFDictionary, nil)
    }
    static func read() -> String? {
        var a = q; a[kSecReturnData as String] = true
        var out: CFTypeRef?
        guard SecItemCopyMatching(a as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }
    static func delete() { SecItemDelete(q as CFDictionary) }
}
