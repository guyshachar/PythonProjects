"""
Celery background task: drives scoutCut.py for a web job.

Flow:
    1. Convert job payload → CSV in a temp directory
    2. Invoke scoutCut.py via subprocess, stream its output for progress
    3. Parse Google Drive share links from stdout
    4. Update the DB record, fire delivery notification
"""

import csv
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

from web.celery_app import celery_app
from web.database import update_job
from web.delivery import send_delivery_notification

log = logging.getLogger(__name__)

SCOUTCUT  = Path(__file__).parent.parent / "scoutCut.py"
PYTHON    = sys.executable

# Matches Google Drive share links written by upload_to_gdrive()
_GDRIVE_RE = re.compile(
    r"https://drive\.google\.com/file/d/[A-Za-z0-9_-]+/view\?usp=sharing"
)

# Also capture local file paths as fallback (when --upload-gdrive is omitted)
_LOCAL_PATH_RE = re.compile(r"Output saved[:\s]+(.+\.mp4)", re.IGNORECASE)


# ── Job report ────────────────────────────────────────────────────────────────

def _build_report(
    job_id: str,
    job_title: str,
    video_rows: list,
    skipped_rows: list,
    output_links: list,
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
    lines.append(SEP)
    lines.append("")

    # Processed
    total_clips = sum(len(r.get("timecodes", [])) for r in video_rows)
    lines.append(f"✓  PROCESSED  —  {len(video_rows)} video(s)  ·  {total_clips} clip(s)")
    lines.append(DASH)
    for i, row in enumerate(video_rows, 1):
        lines.append(f"  {i}. {row['url']}")
        if row.get("title"):
            lines.append(f"     Caption   : {row['title']}")
        tcs = row.get("timecodes", [])
        if tcs:
            lines.append(f"     Timecodes ({len(tcs)}): {' · '.join(tcs)}")
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
    lines.append(SEP)
    return "\n".join(lines)


# ── CSV generation ─────────────────────────────────────────────────────────────

def _write_csv(video_rows: list, dest: Path) -> Path:
    """
    Serialise the job's video_rows into the CSV format that scoutCut.py expects.

    Format (no fixed columns — one value per row):
        Title:          ← optional caption line (ends with colon)
        https://…       ← URL line
        47:29           ← timecode lines (one per row)
        48:31-48:42
        …
    """
    csv_path = dest / "job_input.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["url"])          # header row (scoutCut ignores it)
        for row in video_rows:
            if row.get("title"):
                writer.writerow([f"{row['title']}:"])
            writer.writerow([row["url"]])
            for tc in row.get("timecodes", []):
                tc = tc.strip()
                if tc:
                    writer.writerow([tc])
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
    """
    config   = payload["config"]
    delivery = payload["delivery"]

    update_job(job_id, status="processing", progress="Preparing job…")

    with tempfile.TemporaryDirectory(prefix=f"scoutcut_{job_id[:8]}_") as tmp:
        tmp_dir = Path(tmp)
        try:
            # ── 1. Write CSV ────────────────────────────────────────────────
            csv_path = _write_csv(payload["video_rows"], tmp_dir)
            update_job(job_id, progress="Input CSV ready, launching scoutCut…")

            # ── 2. Build command ────────────────────────────────────────────
            cmd: list[str] = [
                PYTHON, str(SCOUTCUT),
                str(csv_path),
                "--pad-before", str(config["pad_before"]),
                "--pad-after",  str(config["pad_after"]),
                "--upload-gdrive",
            ]
            if config.get("output_strategy") == "multiple":
                cmd.append("--split")

            log.info("[job %s] cmd: %s", job_id, " ".join(cmd))

            # ── 3. Stream subprocess output ─────────────────────────────────
            lines: list[str] = []
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=SCOUTCUT.parent,
            )
            assert proc.stdout is not None  # narrowing for type checker
            for raw in iter(proc.stdout.readline, ""):
                line = raw.rstrip()
                lines.append(line)
                # Surface meaningful progress lines to the DB
                if any(kw in line for kw in ("[INFO]", "Clip", "Downloading", "Normaliz", "Concat", "Upload")):
                    update_job(job_id, progress=line[:200])

            proc.wait()
            full_output = "\n".join(lines)

            if proc.returncode != 0:
                raise RuntimeError(
                    f"scoutCut.py exited {proc.returncode}.\n"
                    + full_output[-2000:]
                )

            # ── 4. Extract links ────────────────────────────────────────────
            links = _extract_links(full_output)
            if not links:
                raise RuntimeError(
                    "No output links found in scoutCut.py output.\n" + full_output[-1000:]
                )

            # ── 5. Build report ─────────────────────────────────────────────
            report = _build_report(
                job_id=job_id,
                job_title=payload.get("job_title", ""),
                video_rows=payload["video_rows"],
                skipped_rows=payload.get("skipped_rows", []),
                output_links=links,
            )

            # ── 6. Persist + notify ─────────────────────────────────────────
            update_job(job_id, status="completed", output_links=links,
                       progress=f"Done — {len(links)} file(s) ready.",
                       report=report)
            send_delivery_notification(
                contact_method=delivery["method"],
                contact=delivery["contact"],
                links=links,
                job_id=job_id,
                report=report,
            )
            log.info("[job %s] completed: %d link(s)", job_id, len(links))
            return {"status": "completed", "links": links}

        except Exception as exc:
            msg = str(exc)[:500]
            log.exception("[job %s] failed: %s", job_id, msg)
            update_job(job_id, status="failed", error=msg)
            raise
