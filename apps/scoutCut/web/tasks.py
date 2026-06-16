"""
Celery background task: drives scoutCut.py for a web job.

Flow:
    1. Convert job payload → CSV in a temp directory
    2. Invoke scoutCut.py via subprocess, stream its output for progress
    3. Parse Google Drive share links from stdout
    4. Update the DB record, fire delivery notification
"""

import csv
import hashlib
import logging
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Jerusalem")
from pathlib import Path
from typing import List, Optional

# veo_scraper.py and pixellot_scraper.py live in the project root, not in the
# web package. Ensure the root is on sys.path so lazy imports inside
# _resolve_url() work when the Celery worker starts from a different cwd.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_ready

from web.celery_app import celery_app
from web.database import update_job
from web.delivery import send_delivery_notification, send_failure_notification

log = logging.getLogger(__name__)


_ORPHAN_GRACE_SECS = 60  # jobs updated within this window may still be live (rolling deploy)


@worker_ready.connect
def _mark_orphaned_jobs_failed(sender, **kwargs):
    """
    On worker boot, any job left in 'pending' or 'processing' was interrupted
    by a container restart or crash. Mark them failed so they don't hang forever.

    A 60-second grace window is applied so that a rolling-update scenario
    (new worker starts before old one stops) doesn't incorrectly kill a live job.
    """
    from datetime import timedelta
    from web.database import SessionLocal
    from web.models import JobRecord
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=_ORPHAN_GRACE_SECS)
        orphans = (
            db.query(JobRecord)
            .filter(
                JobRecord.status.in_(["pending", "processing"]),
                JobRecord.updated_at < cutoff,
            )
            .all()
        )
        for job in orphans:
            job.status   = "failed"
            job.error    = "Job interrupted — worker was restarted or container was removed."
            job.progress = None
        if orphans:
            db.commit()
            log.warning(
                "Marked %d orphaned job(s) as failed on worker startup: %s",
                len(orphans),
                [j.id for j in orphans],
            )
    finally:
        db.close()

SCOUTCUT  = Path(__file__).parent.parent / "scoutCut.py"
PYTHON    = sys.executable
RUNS_DIR  = SCOUTCUT.parent / "runs"

# Matches Google Drive share links written by upload_to_gdrive()
_GDRIVE_RE = re.compile(
    r"https://drive\.google\.com/file/d/[A-Za-z0-9_-]+/view\?usp=sharing"
)

# Also capture local file paths as fallback (when --upload-gdrive is omitted)
_LOCAL_PATH_RE = re.compile(r"Output saved[:\s]+(.+\.mp4)", re.IGNORECASE)

_TC_RANGE_RE = re.compile(r"([\d:.]+)\s*-\s*([\d:.]+)")


def _tc_to_secs(tc: str) -> float:
    parts = tc.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _clip_secs(tc: str, pad_before: float, pad_after: float) -> float:
    """Return total clip duration in seconds including padding."""
    m = _TC_RANGE_RE.fullmatch(tc.strip())
    if m:
        return (_tc_to_secs(m.group(2)) - _tc_to_secs(m.group(1))) + pad_before + pad_after
    return pad_before + pad_after  # single-point timecode


def _fmt_duration(secs: float) -> str:
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── Job report ────────────────────────────────────────────────────────────────

def _build_report(
    job_id: str,
    job_title: str,
    video_rows: list,
    skipped_rows: list,
    output_links: list,
    resolved_urls: list | None = None,
    pad_before: float = 0.0,
    pad_after: float = 0.0,
    quality: str = "balanced",
    timing: dict | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> str:
    """
    Build a human-readable completion report covering:
      - all processed URLs with captions and timecode ranges
      - all skipped URLs with skip reason
      - output links
    """
    SEP  = "═" * 54
    DASH = "─" * 54
    lines: list[str] = [SEP, "  ScoutCut Job Report"]
    if job_title:
        lines.append(f"  Job:    {job_title}")
    lines.append(f"  Job ID: {job_id}")
    lines.append(f"  Quality : {quality}  ·  Pad before: {pad_before}s  ·  Pad after: {pad_after}s")
    lines.append(SEP)
    lines.append("")

    # Processed
    total_clips = sum(len(r.get("timecodes", [])) for r in video_rows)
    grand_total_secs = sum(
        _clip_secs(tc, pad_before, pad_after)
        for r in video_rows
        for tc in r.get("timecodes", [])
    )
    lines.append(
        f"✓  PROCESSED  —  {len(video_rows)} video(s)  ·  {total_clips} clip(s)"
        f"  ·  total {_fmt_duration(grand_total_secs)}"
    )
    lines.append(DASH)
    for i, row in enumerate(video_rows, 1):
        original = row["url"]
        resolved = resolved_urls[i - 1] if resolved_urls and i - 1 < len(resolved_urls) else None
        lines.append(f"  {i}. {original}")
        if resolved and resolved != original:
            lines.append(f"     Resolved  : {resolved}")
        if row.get("title"):
            lines.append(f"     Caption   : {row['title']}")
        if row.get("offset"):
            lines.append(f"     Offset    : {row['offset']}")
        tcs = row.get("timecodes", [])
        if tcs:
            url_secs = sum(_clip_secs(tc, pad_before, pad_after) for tc in tcs)
            lines.append(
                f"     Timecodes ({len(tcs)}): {' · '.join(tcs)}"
                f"  [{_fmt_duration(url_secs)}]"
            )
        lines.append("")

    # Skipped
    if skipped_rows:
        lines.append(f"✗  SKIPPED  —  {len(skipped_rows)} video(s)  (invalid URL, not processed)")
        lines.append(DASH)
        for i, row in enumerate(skipped_rows, 1):
            lines.append(f"  {i}. {row.get('url', '')}")
            if row.get("title"):
                lines.append(f"     Caption : {row['title']}")
            tcs = row.get("timecodes", [])
            if tcs:
                lines.append(f"     Timecodes ({len(tcs)}): {' · '.join(tcs)}")
            if row.get("skip_reason"):
                lines.append(f"     Reason  : {row['skip_reason']}")
        lines.append("")

    # Output links
    lines.append("⬇  OUTPUT LINKS")
    lines.append(DASH)
    for i, link in enumerate(output_links, 1):
        lines.append(f"  {i}. {link}")
    lines.append("")

    # Timing
    if timing or started_at:
        lines.append("⏱  TIMING")
        lines.append(DASH)
        _fmt_ts = lambda dt: dt.strftime("%d %b %Y  %H:%M:%S") if dt else ""
        if started_at:
            lines.append(f"  Started   : {_fmt_ts(started_at)}")
        if completed_at:
            lines.append(f"  Completed : {_fmt_ts(completed_at)}")
        if timing:
            lines.append(f"  Download  : {_fmt_duration(timing['download'])}")
            lines.append(f"  Clipping  : {_fmt_duration(timing['clipping'])}")
            lines.append(f"  Job total : {_fmt_duration(timing['total'])}")
        lines.append("")

    lines.append(SEP)
    return "\n".join(lines)


# ── URL resolution ────────────────────────────────────────────────────────────

_PLATFORM_MARKERS = ("pixellot.link", "live.veo.co", "app.veo.co")


def _resolve_url(url: str) -> str:
    """
    Resolve a platform URL (Veo, Pixellot) to its direct CDN/stream URL.
    Returns the original URL unchanged if resolution fails or is not applicable.
    Cache keys are computed from the resolved URL so that re-submitting the same
    platform link after a code fix doesn't return a stale cached result.
    """
    if not any(m in url for m in _PLATFORM_MARKERS):
        return url
    if "pixellot.link" in url:
        try:
            from pixellot_scraper import extract_stream_url as _p  # type: ignore[import]
            resolved = _p(url)
            return resolved or url
        except Exception as exc:
            log.warning("pixellot_scraper failed for %s: %s", url, exc)
    if "live.veo.co" in url or "app.veo.co" in url:
        try:
            from veo_scraper import extract_stream_url as _v  # type: ignore[import]
            resolved = _v(url)
            return resolved or url
        except Exception as exc:
            log.warning("veo_scraper failed for %s: %s", url, exc)
    return url


def _resolved_cache_key(url: str) -> str:
    """sha256 of the resolved URL — stable download-cache key that survives platform URL changes."""
    return hashlib.sha256(url.strip().encode()).hexdigest()


def _parse_timing(output: str) -> dict[str, float] | None:
    """
    Parse [TIMING] line emitted by scoutCut.py at the end of a run.
    Returns dict with keys: download, clipping, total (all in seconds), or None.
    """
    m = re.search(
        r'\[TIMING\]\s+download=([\d.]+)\s+clipping=([\d.]+)\s+total=([\d.]+)',
        output,
    )
    if not m:
        return None
    return {
        "download": float(m.group(1)),
        "clipping": float(m.group(2)),
        "total":    float(m.group(3)),
    }


def _parse_resolution_map(output: str) -> dict[str, str]:
    """
    Extract {original_url: resolved_url} pairs from scoutCut.py log output.

    scoutCut logs resolution as two adjacent lines:
        [INFO]   https://app.veo.co/matches/...
        [INFO]   → https://cdn.veo.co/...
    """
    result: dict[str, str] = {}
    url_re    = re.compile(r'https?://\S+')
    arrow_re  = re.compile(r'→\s+(https?://\S+)')
    prev_url: str | None = None
    for line in output.splitlines():
        arrow_m = arrow_re.search(line)
        if arrow_m and prev_url:
            result[prev_url] = arrow_m.group(1)
            prev_url = None
        elif url_re.search(line) and '→' not in line:
            prev_url = url_re.search(line).group(0)  # type: ignore[union-attr]
        else:
            prev_url = None
    return result


# ── CSV generation ─────────────────────────────────────────────────────────────

def _write_csv(video_rows: list, dest: Path) -> Path:
    """
    Serialise the job's video_rows into a columnar CSV that scoutCut.py expects.

    Columns: url, offset, caption, timecode1, timecode2, …
    scoutCut.build_clip_specs reads every column whose name starts with 'timecode'
    and reads 'offset' to shift all timecodes for that row.
    """
    max_tcs = max((len(r.get("timecodes", [])) for r in video_rows), default=1)
    tc_cols = [f"timecode{i + 1}" for i in range(max_tcs)]
    fieldnames = ["url", "offset", "caption"] + tc_cols

    csv_path = dest / "job_input.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in video_rows:
            record: dict = {
                "url":     row["url"],
                "offset":  (row.get("offset") or "").strip(),
                "caption": (row.get("title")  or "").strip(),
            }
            for i, tc in enumerate(row.get("timecodes", [])):
                record[f"timecode{i + 1}"] = tc.strip()
            writer.writerow(record)
    return csv_path


# ── Output link extraction ─────────────────────────────────────────────────────

def _extract_links(output: str) -> List[str]:
    links = list(dict.fromkeys(_GDRIVE_RE.findall(output)))  # dedup, preserve order
    if not links:
        links = list(dict.fromkeys(_LOCAL_PATH_RE.findall(output)))
    return links


# ── Celery task ────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="tasks.process_job", max_retries=0)
def process_job(self, job_id: str, payload: dict) -> dict:
    """
    Payload keys:
        video_rows:  [{url, title, timecodes: [str, …]}, …]
        config:      {pad_before, pad_after, output_strategy}
        delivery:    {method, contact}

    Cache keys are computed from the *resolved* CDN URL so that resubmitting
    the same platform URL (e.g. app.veo.co) after a code fix doesn't return a
    stale result cached under the old original-URL key.
    """
    config          = payload["config"]
    delivery        = payload["delivery"]
    output_strategy = config.get("output_strategy", "single")
    all_rows        = payload["video_rows"]

    job_started_at = datetime.now(_TZ)

    # ── 1. Create run dir immediately so run.log exists from the start ─────────
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS_DIR / f"job_{job_id.split('-')[0]}_{datetime.now(_TZ).strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    update_job(job_id, status="processing", progress="Resolving video URLs…",
               worker=self.request.hostname)

    # ── 2. Resolve every URL ───────────────────────────────────────────────────
    resolved_urls = []
    for row in all_rows:
        original = row["url"]
        resolved = _resolve_url(original)
        log.info("[job %s] original=%s → resolved=%s", job_id, original, resolved)
        resolved_urls.append(resolved)

    try:
        proc: Optional[subprocess.Popen] = None
        proc_start: float = time.time()

        # ── 3. Build rows for scoutCut with pre-resolved URLs ───────────────
        rows_to_process = []
        for i, row in enumerate(all_rows):
            r = dict(row)
            r["url"] = resolved_urls[i]
            rows_to_process.append(r)

        # ── 4. Write CSV into run dir ────────────────────────────────────────
        csv_path = _write_csv(rows_to_process, run_dir)
        update_job(job_id, progress="Input CSV ready, launching scoutCut…")

        # ── 5. Build command ────────────────────────────────────────────────
        cmd: list[str] = [
            PYTHON, str(SCOUTCUT),
            str(csv_path),
            "--pad-before", str(config["pad_before"]),
            "--pad-after",  str(config["pad_after"]),
            "--quality",    config.get("quality", "balanced"),
            "--upload-gdrive",
            "--run-dir",    str(run_dir),
            "--job-id",     job_id,
        ]
        if output_strategy == "multiple":
            cmd.append("--split")

        log.info("[job %s] cmd: %s", job_id, " ".join(cmd))

        # ── 6. Stream subprocess output ─────────────────────────────────
        lines: list[str] = []
        _progress_re = re.compile(r"\[Progress:\s*\d+/\d+\s+clips\s+\(([\d.]+)%\)\]")
        proc_start = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=SCOUTCUT.parent,
        )
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip()
            lines.append(line)
            if any(kw in line for kw in ("[INFO]", "Clip", "Downloading", "Normaliz", "Encoding", "Progress", "Concat", "Upload")):
                progress_text = line[:200]
                m = _progress_re.search(line)
                if m:
                    pct = float(m.group(1))
                    if pct > 0:
                        elapsed = time.time() - proc_start
                        eta_secs = int(elapsed * (100 - pct) / pct)
                        h, rem = divmod(eta_secs, 3600)
                        mins, secs = divmod(rem, 60)
                        eta_str = (f"{h}h {mins}m" if h else f"{mins}m {secs:02d}s") if eta_secs >= 60 else f"{eta_secs}s"
                        progress_text += f"  |  ETA {eta_str}"
                update_job(job_id, progress=progress_text)

        proc.wait()
        full_output = "\n".join(lines)

        if proc.returncode != 0:
            raise RuntimeError(
                f"scoutCut.py exited {proc.returncode}.\n" + full_output[-2000:]
            )

        # ── 7. Back-fill resolved_urls from scoutCut log output ────────
        # scoutCut.py resolves platform URLs itself when tasks.py resolution
        # failed; pick up those CDN URLs so the report shows what was used.
        resolution_map = _parse_resolution_map(full_output)
        if resolution_map:
            resolved_urls = [
                resolution_map.get(orig, resolved_urls[i])
                for i, orig in enumerate(r["url"] for r in all_rows)
            ]

        # ── 8. Extract new links ────────────────────────────────────────
        new_links = _extract_links(full_output)
        if not new_links:
            raise RuntimeError(
                "No output links found in scoutCut.py output.\n" + full_output[-1000:]
            )

        # ── 9. Collect output links ─────────────────────────────────────
        all_links = new_links

        # ── 10. Build report ────────────────────────────────────────────
        timing = _parse_timing(full_output)
        report = _build_report(
            job_id=job_id,
            job_title=payload.get("job_title", ""),
            video_rows=all_rows,
            skipped_rows=payload.get("skipped_rows", []),
            output_links=all_links,
            resolved_urls=resolved_urls,
            pad_before=float(config.get("pad_before", 0)),
            pad_after=float(config.get("pad_after", 0)),
            quality=config.get("quality", "balanced"),
            timing=timing,
            started_at=job_started_at,
            completed_at=datetime.now(_TZ),
        )

        # ── 11. Persist + notify ───────────────────────────────────────
        update_job(job_id, status="completed", output_links=all_links,
                   progress=f"Done — {len(all_links)} file(s) ready.",
                   report=report)
        send_delivery_notification(
            contact_method=delivery["method"],
            contact=delivery["contact"],
            links=all_links,
            job_id=job_id,
            report=report,
        )
        log.info("[job %s] completed: %d link(s)", job_id, len(all_links))
        return {"status": "completed", "links": all_links}

    except SoftTimeLimitExceeded:
        if proc is not None and proc.poll() is None:
            proc.kill()
        elapsed_min = int((time.time() - proc_start) / 60)
        msg = f"Job timed out after {elapsed_min} minutes (limit: {celery_app.conf.task_soft_time_limit // 60} min)"
        log.error("[job %s] %s", job_id, msg)
        update_job(job_id, status="failed", error=msg)
        send_failure_notification(
            contact_method=delivery["method"],
            contact=delivery["contact"],
            job_id=job_id,
            status="timeout",
            reason=msg,
        )
        raise

    except Exception as exc:
        msg = str(exc)[:500]
        log.exception("[job %s] failed: %s", job_id, msg)
        update_job(job_id, status="failed", error=msg)
        send_failure_notification(
            contact_method=delivery["method"],
            contact=delivery["contact"],
            job_id=job_id,
            status="failed",
            reason=msg,
        )
        raise
