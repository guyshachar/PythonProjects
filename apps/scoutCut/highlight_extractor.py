#!/usr/bin/env python3
"""
highlight_extractor.py

Extracts video clips from public URLs, prepends 2-second title cards,
concatenates everything into a single unified video, and optionally
uploads to Google Drive.

Usage:
    python highlight_extractor.py clips.csv
    python highlight_extractor.py clips.csv --pad-before 3 --pad-after 8
    python highlight_extractor.py clips.csv --upload-gdrive --verbose

CSV format (header row required, column names case-insensitive):
    Single timecode per row:
        url,timecode
        https://www.youtube.com/watch?v=dQw4w9WgXcQ,3:25

    Multiple timecodes per row (any number of timecodeN columns):
        url,timecode1,timecode2,timecode3
        https://www.youtube.com/watch?v=dQw4w9WgXcQ,3:25,10:00-11:30,25:00

    Timecodes may be a single point ("MM:SS") or a range ("MM:SS-MM:SS").
    Empty timecode cells are silently ignored.
"""

import argparse
import csv
import hashlib
import logging
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

import yt_dlp

log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

RUNS_DIR    = Path("runs")
TITLE_SECS  = 2        # title card duration in seconds
VWIDTH      = 1920
VHEIGHT     = 1080
VFPS        = 30
VCRF        = 18       # visually-lossless H.264
AUDIO_SR    = 44100    # Hz
AUDIO_BR    = "192k"

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4v"}


# ─── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class ClipSpec:
    url: str
    raw_timecode: str  # original CSV value — used for display on title card
    start_secs: float  # padded extraction start
    end_secs: float    # padded extraction end
    clip_num: int      # sequential 1-based clip number across all rows
    row_num: int       # 1-based source CSV row number


# ─── Timecode Helpers ─────────────────────────────────────────────────────────

def _tc_to_secs(tc: str) -> float:
    """Parse HH:MM:SS, MM:SS, or SS[.ss] into float seconds."""
    parts = tc.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 1:
            return float(parts[0])
    except ValueError:
        pass
    raise ValueError(f"Unrecognised timecode format: {tc!r}")


def parse_timecode(raw: str, pad_before: float, pad_after: float) -> tuple[float, float]:
    """
    Parse a raw timecode string and apply padding.
    Accepts "MM:SS", "HH:MM:SS", or "START-END" range forms.
    Returns (start_secs, end_secs) with start clamped to >= 0.
    """
    raw = raw.strip()
    m = re.fullmatch(r"([\d:.]+)\s*-\s*([\d:.]+)", raw)
    if m:
        start = _tc_to_secs(m.group(1))
        end   = _tc_to_secs(m.group(2))
    else:
        point = _tc_to_secs(raw)
        start = point
        end   = point

    return max(0.0, start - pad_before), end + pad_after


# ─── Title Card (Pillow) ──────────────────────────────────────────────────────

# macOS and common Linux font paths, tried in order
_FONT_CANDIDATES = [
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def has_audio(path: Path) -> bool:
    """Return True if the media file contains at least one audio stream."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


# ─── Pipeline Steps ───────────────────────────────────────────────────────────

def generate_title_card(url: str, timecode: str, output_path: Path) -> bool:
    """
    Render a 2-second black title card using Pillow (avoids ffmpeg drawtext /
    libfreetype dependency). Saves a PNG, then encodes it to video with ffmpeg.
    """
    img  = Image.new("RGB", (VWIDTH, VHEIGHT), color="black")
    draw = ImageDraw.Draw(img)

    font_url = _load_font(32)
    font_tc  = _load_font(52)

    # Wrap URL to at most 2 lines of ~70 chars each
    url_lines = textwrap.wrap(url, width=70) or [url]
    url_block = "\n".join(url_lines[:2])

    # Measure and centre each text block
    def _centre_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, y: int) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((VWIDTH - w) // 2, y), text, fill="white", font=font)

    # URL block (one or two lines, ~55 % up the frame)
    url_bbox  = draw.textbbox((0, 0), url_block, font=font_url)
    url_h     = url_bbox[3] - url_bbox[1]
    url_y     = VHEIGHT // 2 - url_h - 30
    for line in url_lines[:2]:
        _centre_text(line, font_url, url_y)
        url_y += url_bbox[3] - url_bbox[1] + 4

    # Timecode below the URL block
    _centre_text(timecode, font_tc, VHEIGHT // 2 + 10)

    # Write PNG to temp, then encode to video
    png_path = output_path.with_suffix(".png")
    img.save(str(png_path))

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(VFPS), "-i", str(png_path),
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SR}",
        "-t", str(TITLE_SECS),
        "-c:v", "libx264", "-crf", str(VCRF), "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BR, "-ar", str(AUDIO_SR),
        "-pix_fmt", "yuv420p", "-shortest",
        str(output_path),
    ]
    log.debug("Title card encode cmd: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    png_path.unlink(missing_ok=True)
    if r.returncode != 0:
        log.error("Title card encoding failed:\n%s", r.stderr[-2000:])
        return False
    return True


def _ydl_progress_hook(d: dict) -> None:
    """Forward yt-dlp download progress to the logger."""
    status = d.get("status")
    if status == "downloading":
        pct   = d.get("_percent_str", "?%").strip()
        speed = d.get("_speed_str", "?").strip()
        eta   = d.get("_eta_str", "?").strip()
        log.debug("  Downloading: %s  speed=%s  eta=%s", pct, speed, eta)
    elif status == "finished":
        log.info("  Download finished: %s", Path(d.get("filename", "")).name)


def _url_hash(url: str) -> str:
    """Short stable identifier for a URL, used in cache filenames."""
    return hashlib.md5(url.encode()).hexdigest()[:10]


def download_full_video(url: str, stem: Path) -> Optional[Path]:
    """
    Download the complete video at highest quality via yt-dlp.
    stem is the output path without extension (e.g. temp_clips/full_abc123).
    Returns the actual output file path, or None on failure.
    """
    template = str(stem) + ".%(ext)s"
    ydl_opts: dict = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "outtmpl": template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_ydl_progress_hook],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret = ydl.download([url])
        if ret != 0:
            log.error("yt-dlp returned non-zero exit code for %s", url)
            return None

        candidates = [
            p for p in stem.parent.glob(stem.name + ".*")
            if p.suffix.lower() in VIDEO_EXTS
        ]
        if not candidates:
            log.error("No video file found after download of %s", url)
            return None
        return max(candidates, key=lambda p: p.stat().st_size)

    except Exception:
        log.exception("Download failed for %s", url)
        return None


def extract_clip(source: Path, start: float, end: float, output: Path) -> bool:
    """
    Cut a time window from a local video file using ffmpeg stream-copy (fast).
    Uses input-side -ss for keyframe seek, -t for duration.
    """
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(source),
        "-t", str(duration),
        "-c", "copy",
        str(output),
    ]
    log.debug("Extract clip cmd: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.error("Clip extraction failed:\n%s", r.stderr[-2000:])
        return False
    return True


def normalize_clip(input_path: Path, output_path: Path) -> bool:
    """
    Re-encode a clip to the uniform target spec:
      - 1920x1080 (letterboxed), 30 fps, H.264 CRF 18, yuv420p
      - AAC stereo 44.1 kHz 192 kbps
    Injects a silent stereo track if the source has no audio.
    """
    scale_chain = (
        f"scale={VWIDTH}:{VHEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VWIDTH}:{VHEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={VFPS},"
        f"format=yuv420p"
    )

    if has_audio(input_path):
        extra_inputs: list[str] = []
        audio_filter = f"[0:a]aresample={AUDIO_SR},aformat=channel_layouts=stereo[aout]"
    else:
        # Supply a silent stereo track as a second input
        extra_inputs = [
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SR}",
        ]
        audio_filter = f"[1:a]aresample={AUDIO_SR}[aout]"

    filter_complex = f"[0:v]{scale_chain}[vout];{audio_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        *extra_inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-crf", str(VCRF), "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BR, "-ar", str(AUDIO_SR),
        "-movflags", "+faststart",
        str(output_path),
    ]
    log.debug("Normalize cmd: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.error("Normalisation failed for %s:\n%s", input_path.name, r.stderr[-2000:])
        return False
    return True


def concatenate_clips(segments: list[Path], output_path: Path) -> bool:
    """
    Concatenate all segments (title cards + normalised clips) into one video
    using ffmpeg's concat filter. Each input is fully decoded and re-encoded
    at CRF 18, guaranteeing seamless timestamps regardless of per-file headers.
    """
    n = len(segments)
    inputs = []
    for p in segments:
        inputs += ["-i", str(p)]

    stream_chains = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filter_complex = f"{stream_chains}concat=n={n}:v=1:a=1[vout][aout]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-crf", str(VCRF), "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BR, "-ar", str(AUDIO_SR),
        "-movflags", "+faststart",
        str(output_path),
    ]
    log.debug("Concat cmd: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.error("Concatenation failed:\n%s", r.stderr[-2000:])
        return False
    return True


# ─── Google Drive ─────────────────────────────────────────────────────────────

def upload_to_gdrive(file_path: Path) -> Optional[str]:
    """
    Upload *file_path* to Google Drive, grant public viewer access, and
    return a shareable link. Requires credentials.json in the working directory.
    On first run an OAuth browser window will open; subsequent runs use token.json.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        log.error(
            "Google API libraries missing. "
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )
        return None

    SCOPES      = ["https://www.googleapis.com/auth/drive.file"]
    token_path  = Path("token.json")
    creds_path  = Path("credentials.json")

    creds: Optional[Credentials] = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                log.error(
                    "credentials.json not found. "
                    "Download it from Google Cloud Console (see setup instructions) "
                    "and place it in the current directory."
                )
                return None
            flow  = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        with token_path.open("w") as fh:
            fh.write(creds.to_json())

    service = build("drive", "v3", credentials=creds)

    log.info("Uploading %s (%.1f MB)...", file_path.name, file_path.stat().st_size / 1e6)
    media    = MediaFileUpload(str(file_path), mimetype="video/mp4", resumable=True)
    uploaded = (
        service.files()
        .create(body={"name": file_path.name}, media_body=media, fields="id")
        .execute()
    )
    file_id = uploaded["id"]

    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    log.info("Upload complete: %s", link)
    return link


# ─── Startup Validation ───────────────────────────────────────────────────────

def check_dependencies() -> bool:
    """Verify required system binaries are on PATH before doing any work."""
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            log.error("Required binary not found on PATH: %s  (install FFmpeg)", tool)
            ok = False
    return ok


# ─── I/O Helpers ──────────────────────────────────────────────────────────────

def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("clip_extractor.log", encoding="utf-8"),
        ],
    )


def read_csv(path: Path) -> list[dict]:
    """Read CSV; normalise column names to lowercase and strip whitespace throughout."""
    with path.open(newline="", encoding="utf-8-sig") as fh:  # utf-8-sig handles Excel BOM
        reader = csv.DictReader(fh)
        return [
            {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def _looks_like_timecode(s: str) -> bool:
    return bool(re.fullmatch(r"[\d:.]+(\s*-\s*[\d:.]+)?", s.strip()))


def preprocess_rows(rows: list[dict]) -> list[dict]:
    """
    Normalize mixed-format rows into standard {url, timecode1, timecode2, ...} dicts.

    Handles two layouts — they may be mixed in the same file:

      Standard (timecodes in columns):
        url,timecode1,timecode2
        https://…,3:25,0:05

      Stacked (timecodes on their own lines below the URL):
        url,...
        https://…
        2:10-2:45
        2:58
    """
    result: list[dict] = []
    for row in rows:
        url_field = row.get("url", "")
        if _looks_like_url(url_field):
            result.append(dict(row))
        elif _looks_like_timecode(url_field) and result:
            # Stacked timecode row — attach to the most recent URL row
            prev = result[-1]
            i = 1
            while prev.get(f"timecode{i}", ""):
                i += 1
            prev[f"timecode{i}"] = url_field
        # else: unrecognised row (e.g. blank) — silently skip
    return result


def build_clip_specs(
    rows: list[dict],
    pad_before: float,
    pad_after: float,
) -> list[ClipSpec]:
    """
    Parse CSV rows into validated ClipSpec objects; bad entries are logged and skipped.

    Each row must have a 'url' column plus one or more timecode columns whose names
    start with 'timecode' (e.g. 'timecode', 'timecode1', 'timecode2', …).
    Empty timecode cells are ignored, so sparse rows are fine.
    """
    specs: list[ClipSpec] = []
    clip_num = 0
    for row_num, row in enumerate(rows, start=1):
        url = row.get("url", "")
        if not url:
            log.warning("Row %d: missing 'url' — skipped", row_num)
            continue

        # Collect values from every column whose name starts with 'timecode'
        timecodes = [v for k, v in row.items() if k.startswith("timecode") and v]
        if not timecodes:
            log.warning("Row %d: no timecode columns found — skipped", row_num)
            continue

        for tc in timecodes:
            try:
                start, end = parse_timecode(tc, pad_before, pad_after)
            except ValueError as exc:
                log.warning("Row %d: bad timecode %r (%s) — skipped", row_num, tc, exc)
                continue
            clip_num += 1
            specs.append(
                ClipSpec(
                    url=url,
                    raw_timecode=tc,
                    start_secs=start,
                    end_secs=end,
                    clip_num=clip_num,
                    row_num=row_num,
                )
            )
    return specs


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "csv_file", type=Path,
        help="Input CSV file with 'url' and 'timecode' columns",
    )
    p.add_argument(
        "--pad-before", type=float, default=5.0, metavar="SECS",
        help="Seconds to prepend before the timecode point/start (default: 5)",
    )
    p.add_argument(
        "--pad-after", type=float, default=5.0, metavar="SECS",
        help="Seconds to append after the timecode point/end (default: 5)",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="Override output file path (default: runs/<csv>_<run_id>/highlights_<csv>_<run_id>.mp4)",
    )
    p.add_argument(
        "--upload-gdrive", action="store_true",
        help="Upload the finished video to Google Drive and print the shareable link",
    )
    p.add_argument(
        "--keep-temp", action="store_true",
        help="Keep the temp_clips working directory after completion",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging",
    )
    return p


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = build_parser().parse_args()
    setup_logging(args.verbose)

    if not check_dependencies():
        sys.exit(1)

    if not args.csv_file.exists():
        log.error("CSV file not found: %s", args.csv_file)
        sys.exit(1)

    rows = read_csv(args.csv_file)
    if not rows:
        log.error("CSV is empty or has no data rows.")
        sys.exit(1)

    rows = preprocess_rows(rows)
    specs = build_clip_specs(rows, args.pad_before, args.pad_after)
    if not specs:
        log.error("No valid clip specs parsed from CSV.")
        sys.exit(1)

    log.info(
        "Starting: %d clip(s), pad_before=%.1fs, pad_after=%.1fs",
        len(specs), args.pad_before, args.pad_after,
    )
    run_id   = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_stem = re.sub(r"[^\w]+", "_", args.csv_file.stem).strip("_").lower()
    run_dir  = RUNS_DIR / f"{csv_stem}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Copy input CSV into the run folder for reproducibility
    shutil.copy2(args.csv_file, run_dir / args.csv_file.name)

    temp_dir = run_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    output = args.output or run_dir / f"highlights_{csv_stem}_{run_id}.mp4"

    segments: list[Path] = []
    # Cache: url -> downloaded full-video Path (or None if download failed)
    url_cache: dict[str, Optional[Path]] = {}

    unique_urls = list(dict.fromkeys(s.url for s in specs))
    log.info(
        "%d unique URL(s) across %d clip(s) — each video downloaded once.",
        len(unique_urls), len(specs),
    )

    try:
        for spec in specs:
            log.info(
                "── Clip %d/%d  (row %d)  timecode=%s  window=[%.1fs, %.1fs]  url=%s",
                spec.clip_num, len(specs), spec.row_num,
                spec.raw_timecode, spec.start_secs, spec.end_secs,
                spec.url,
            )

            # 1. Title card
            title_path = temp_dir / f"title_{spec.clip_num:03d}.mp4"
            log.info("  [1/3] Generating title card...")
            if not generate_title_card(spec.url, spec.raw_timecode, title_path):
                log.error("  Title card failed — skipping clip %d", spec.clip_num)
                continue

            # 2. Download full video once per URL, then extract the needed window
            if spec.url not in url_cache:
                full_stem = temp_dir / f"full_{_url_hash(spec.url)}"
                log.info("  [2/3] Downloading full video (first use of this URL)...")
                url_cache[spec.url] = download_full_video(spec.url, full_stem)
            else:
                log.info("  [2/3] Using cached video for this URL.")

            full_video = url_cache[spec.url]
            if full_video is None:
                log.error("  Video unavailable — skipping clip %d", spec.clip_num)
                continue

            raw_path = temp_dir / f"raw_{spec.clip_num:03d}.mp4"
            log.info(
                "  Extracting window  %.1fs – %.1fs...",
                spec.start_secs, spec.end_secs,
            )
            if not extract_clip(full_video, spec.start_secs, spec.end_secs, raw_path):
                log.error("  Extraction failed — skipping clip %d", spec.clip_num)
                continue

            # 3. Normalise
            norm_path = temp_dir / f"norm_{spec.clip_num:03d}.mp4"
            log.info("  [3/3] Normalising to %dx%d @ %dfps...", VWIDTH, VHEIGHT, VFPS)
            if not normalize_clip(raw_path, norm_path):
                log.error("  Normalisation failed — skipping clip %d", spec.clip_num)
                continue

            segments += [title_path, norm_path]
            log.info("  Clip %d done.", spec.clip_num)

        if not segments:
            log.error("No clips processed successfully — nothing to concatenate.")
            sys.exit(1)

        log.info("Concatenating %d segment(s)...", len(segments))
        if not concatenate_clips(segments, output):
            log.error("Concatenation failed.")
            sys.exit(1)

        size_mb = output.stat().st_size / 1e6
        log.info("Output: %s  (%.1f MB)", output, size_mb)

        if args.upload_gdrive:
            link = upload_to_gdrive(output)
            if link:
                print(f"\nShareable Google Drive link:\n  {link}\n")
            else:
                log.error("Google Drive upload failed.")

    finally:
        if not args.keep_temp:
            log.info("Removing temp dir %s", temp_dir)
            shutil.rmtree(temp_dir, ignore_errors=True)
        log.info("Run folder: %s", run_dir)

    log.info("Done.")


if __name__ == "__main__":
    main()
