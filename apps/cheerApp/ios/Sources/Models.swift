import Foundation

// Mirrors shared/show.schema.json. Keep this and web/src/*.js's implicit
// shape in lockstep — see cheerApp/docs/SHOW_FORMAT.md.

struct Zone: Codable, Identifiable {
    let zoneId: String
    let label: String
    let qrToken: String?

    var id: String { zoneId }
}

enum CueType: String, Codable {
    case flash, color, image, video, audio
}

struct Cue: Codable, Identifiable {
    let id: String
    let offsetMs: Int
    let durationMs: Int
    let type: CueType
    let params: [String: AnyCodable]
    let zones: [String]

    /// Absolute server-time fire instant, computed once the parent Show's
    /// startAtUtc is known — see CueEngine.swift.
    func targetServerMs(showStartMs: Double) -> Double {
        showStartMs + Double(offsetMs)
    }
}

struct Asset: Codable, Identifiable {
    let assetId: String
    let type: String // "image" | "video" | "audio"
    let url: URL
    let sha256: String?

    var id: String { assetId }
}

struct Show: Codable {
    let schemaVersion: String
    let showId: String
    let eventId: String
    let startAtUtc: Date
    let assets: [Asset]
    let cues: [Cue]
}

/// Minimal Any-ish Codable box so `params` (which varies by CueType) can
/// round-trip through Decodable without a hand-written case per cue type.
/// Cue renderers pull out the fields they expect by key (see CueEngine.swift).
struct AnyCodable: Codable {
    let value: Any

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let v = try? container.decode(Double.self) { value = v }
        else if let v = try? container.decode(String.self) { value = v }
        else if let v = try? container.decode(Bool.self) { value = v }
        else { value = NSNull() }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let v as Double: try container.encode(v)
        case let v as String: try container.encode(v)
        case let v as Bool: try container.encode(v)
        default: try container.encodeNil()
        }
    }

    var asDouble: Double? { value as? Double }
    var asString: String? { value as? String }
}
