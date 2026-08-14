import Foundation

/// SNTP-style clock offset estimation against the CheerApp backend's
/// `/time` endpoint. Behaviorally mirrors web/src/timeSync.js — see
/// cheerApp/docs/SYNC_DESIGN.md §1-2 for the math and sampling rationale.
actor TimeSyncService {
    private static let requestTimeout: TimeInterval = 3.0 // abort one hung /time round trip

    private let timeEndpoint: URL
    private let sampleCount: Int
    private let keepFraction: Double
    private let resyncInterval: TimeInterval
    private let maxAttempts: Int // bound retries so a fully dead network still fails fast
    private let minSamples: Int // don't trust an offset built from too few samples

    private(set) var offsetMs: Double? {
        didSet {
            cacheLock.lock()
            cachedOffsetMs = offsetMs
            cacheLock.unlock()
        }
    }
    private(set) var confidenceMs: Double?
    private var resyncTask: Task<Void, Never>?

    // CADisplayLink's per-frame callback (CueEngine's fine scheduling
    // loop, see docs/SYNC_DESIGN.md §3) runs synchronously on the main
    // thread and can't `await` an actor hop without adding the very
    // latency the fine loop exists to avoid. This lock-guarded mirror
    // lets it read the latest offset synchronously; it's the only
    // non-actor-isolated state here and only ever written from `offsetMs`'s
    // didSet.
    private nonisolated(unsafe) var cachedOffsetMs: Double?
    private let cacheLock = NSLock()

    init(
        timeEndpoint: URL,
        sampleCount: Int = 8,
        keepFraction: Double = 0.75,
        resyncInterval: TimeInterval = 60
    ) {
        self.timeEndpoint = timeEndpoint
        self.sampleCount = sampleCount
        self.keepFraction = keepFraction
        self.resyncInterval = resyncInterval
        self.maxAttempts = sampleCount * 2
        self.minSamples = Int((Double(sampleCount) / 2).rounded(.up))
    }

    var isSynced: Bool { offsetMs != nil }

    /// Best current estimate of server time, in epoch ms.
    func serverNowMs() throws -> Double {
        guard let offsetMs else {
            throw TimeSyncError.notYetSynced
        }
        return nowMs() + offsetMs
    }

    /// Resolves once the first sample lands; keeps resyncing on `resyncInterval` after.
    func start() async {
        await resync()
        resyncTask = Task { [resyncInterval] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(resyncInterval * 1_000_000_000))
                await self.resync()
            }
        }
    }

    func stop() {
        resyncTask?.cancel()
        resyncTask = nil
    }

    private func resync() async {
        var samples: [(delay: Double, offset: Double)] = []
        samples.reserveCapacity(sampleCount)

        // One bad round trip (timeout, dropped connection, bad body, ...)
        // doesn't cost the whole batch — skip it and keep sampling, bounded
        // by maxAttempts so a fully dead network still fails in finite time.
        // Matches web/src/timeSync.js's measureOffset().
        var attempts = 0
        while samples.count < sampleCount && attempts < maxAttempts {
            attempts += 1
            guard let sample = try? await fetchSample() else { continue }
            samples.append(sample)
        }

        guard samples.count >= minSamples else {
            // Keep the previous offset on a failed resync (stale beats none).
            return
        }

        samples.sort { $0.delay < $1.delay }
        let keepCount = max(1, Int((Double(samples.count) * keepFraction).rounded(.up)))
        let kept = samples.prefix(keepCount)
        let offsets = kept.map(\.offset).sorted()

        self.offsetMs = median(of: offsets)
        self.confidenceMs = kept.map(\.delay).min()
    }

    private func fetchSample() async throws -> (delay: Double, offset: Double) {
        let t0 = nowMs()
        var request = URLRequest(url: timeEndpoint)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = Self.requestTimeout
        let (data, _) = try await URLSession.shared.data(for: request)
        let t3 = nowMs()

        let response = try JSONDecoder().decode(TimeResponse.self, from: data)
        let t1 = Double(response.t1)
        let t2 = Double(response.t2)

        return (delay: (t3 - t0) - (t2 - t1), offset: ((t1 - t0) + (t2 - t3)) / 2)
    }

    /// True median: averages the two middle values on an even-sized set
    /// instead of just taking the upper-middle one.
    private func median(of sorted: [Double]) -> Double {
        let n = sorted.count
        return n % 2 == 0 ? (sorted[n / 2 - 1] + sorted[n / 2]) / 2 : sorted[n / 2]
    }

    private func nowMs() -> Double {
        Date().timeIntervalSince1970 * 1000
    }

    /// Synchronous, best-effort read of the latest synced server time —
    /// for CueEngine's CADisplayLink fine loop only (see class comment on
    /// `cachedOffsetMs`). Everywhere else, prefer the async `serverNowMs()`.
    nonisolated func cachedServerNowMs() -> Double? {
        cacheLock.lock()
        let offset = cachedOffsetMs
        cacheLock.unlock()
        guard let offset else { return nil }
        return Date().timeIntervalSince1970 * 1000 + offset
    }
}

enum TimeSyncError: Error {
    case notYetSynced
}

private struct TimeResponse: Decodable {
    let t1: Int
    let t2: Int
}
