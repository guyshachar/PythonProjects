import AVFoundation
import QuartzCore
import UIKit

/// Schedules and fires a Show's cues against TimeSyncService's synced
/// clock. Mirrors web/src/cueEngine.js's two-stage design (coarse Timer,
/// fine loop) — see cheerApp/docs/SYNC_DESIGN.md §3. The one real
/// platform difference from web: `flash` drives the camera torch via
/// AVCaptureDevice instead of a screen strobe (docs/ARCHITECTURE.md §5).
@MainActor
final class CueEngine: NSObject {
    private struct ScheduledCue {
        let cue: Cue
        let targetServerMs: Double
        var fired: Bool = false
    }

    private static let coarseLeadMs: Double = 1500
    private static let catchUpGraceMs: Double = 1500

    private let timeSync: TimeSyncService
    private let zoneId: String
    private let renderers: [CueType: (Cue) -> Void]

    private var pending: [ScheduledCue]
    private var coarseTimer: Timer?
    private var displayLink: CADisplayLink?

    init(show: Show, timeSync: TimeSyncService, zoneId: String, renderers: [CueType: (Cue) -> Void]) {
        self.timeSync = timeSync
        self.zoneId = zoneId
        self.renderers = renderers

        let startMs = show.startAtUtc.timeIntervalSince1970 * 1000
        self.pending = show.cues
            .filter { $0.zones.contains("ALL") || $0.zones.contains(zoneId) }
            .map { ScheduledCue(cue: $0, targetServerMs: $0.targetServerMs(showStartMs: startMs)) }
            .sorted { $0.targetServerMs < $1.targetServerMs }

        super.init()
    }

    func start() {
        Task { await scheduleNext() }
    }

    func stop() {
        coarseTimer?.invalidate()
        coarseTimer = nil
        displayLink?.invalidate()
        displayLink = nil
    }

    private func nextUnfiredIndex() -> Int? {
        pending.firstIndex { !$0.fired }
    }

    private func scheduleNext() async {
        guard let idx = nextUnfiredIndex() else { return }
        guard let serverNow = try? await timeSync.serverNowMs() else {
            // Not synced yet — retry shortly rather than firing blind.
            coarseTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: false) { [weak self] _ in
                Task { await self?.scheduleNext() }
            }
            return
        }

        let msUntil = pending[idx].targetServerMs - serverNow

        if msUntil > Self.coarseLeadMs {
            let delay = (msUntil - Self.coarseLeadMs) / 1000
            coarseTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
                Task { await self?.scheduleNext() }
            }
            return
        }

        if msUntil < -Self.catchUpGraceMs {
            pending[idx].fired = true
            await scheduleNext()
            return
        }

        startFineLoop()
    }

    private func startFineLoop() {
        let link = CADisplayLink(target: self, selector: #selector(fineTick))
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    @objc private func fineTick() {
        guard let idx = nextUnfiredIndex() else {
            displayLink?.invalidate()
            displayLink = nil
            return
        }
        guard let serverNow = timeSync.cachedServerNowMs() else { return }

        if serverNow >= pending[idx].targetServerMs {
            pending[idx].fired = true
            fire(pending[idx].cue)
            displayLink?.invalidate()
            displayLink = nil
            Task { await scheduleNext() }
        }
    }

    private func fire(_ cue: Cue) {
        guard let renderer = renderers[cue.type] else {
            print("CueEngine: no renderer registered for cue type \(cue.type)")
            return
        }
        renderer(cue)
    }
}

// MARK: - Default effect renderers

enum CueRenderers {
    /// True camera-torch strobe (the platform advantage over web — see
    /// docs/ARCHITECTURE.md §5). Falls back to a full-screen strobe view
    /// if the device has no torch (e.g. simulator, some iPads).
    static func flash(view: UIView) -> (Cue) -> Void {
        { cue in
            guard let frequencyHz = cue.params["frequencyHz"]?.asDouble, frequencyHz > 0 else { return }
            let periodMs = 1000.0 / frequencyHz
            let device = AVCaptureDevice.default(for: .video)
            let hasTorch = device?.hasTorch ?? false

            let endAt = Date().addingTimeInterval(Double(cue.durationMs) / 1000)
            var on = false

            func tick() {
                on.toggle()
                if hasTorch, let device {
                    try? device.lockForConfiguration()
                    device.torchMode = on ? .on : .off
                    device.unlockForConfiguration()
                } else {
                    view.backgroundColor = on ? .white : .black
                }
                if Date() < endAt {
                    DispatchQueue.main.asyncAfter(deadline: .now() + periodMs / 2 / 1000, execute: tick)
                } else if hasTorch, let device {
                    try? device.lockForConfiguration()
                    device.torchMode = .off
                    device.unlockForConfiguration()
                } else {
                    view.backgroundColor = .black
                }
            }
            tick()
        }
    }

    static func color(view: UIView) -> (Cue) -> Void {
        { cue in
            guard let hex = cue.params["hex"]?.asString else { return }
            view.backgroundColor = UIColor(cheerHex: hex)
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(cue.durationMs) / 1000) {
                view.backgroundColor = .black
            }
        }
    }
}

private extension UIColor {
    convenience init(cheerHex hex: String) {
        var s = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("#") { s.removeFirst() }
        var rgb: UInt64 = 0
        Scanner(string: s).scanHexInt64(&rgb)
        self.init(
            red: CGFloat((rgb & 0xFF0000) >> 16) / 255,
            green: CGFloat((rgb & 0x00FF00) >> 8) / 255,
            blue: CGFloat(rgb & 0x0000FF) / 255,
            alpha: 1
        )
    }
}
