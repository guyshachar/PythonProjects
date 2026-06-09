#!/usr/bin/env python3
"""
scoutCut.py

Extracts video clips from public URLs, prepends 2-second title cards,
concatenates everything into a single unified video, and optionally
uploads to Google Drive.

Usage:
    python scoutCut.py clips.csv
    python scoutCut.py clips.csv --pad-before 3 --pad-after 8
    python scoutCut.py clips.csv --upload-gdrive --verbose

CSV format (header row required, column names case-insensitive):
    Single timecode per row:
        url,timecode
        https://www.youtube.com/watch?v=dQw4w9WgXcQ,3:25

    Multiple timecodes per row (any number of timecodeN columns):
        url,timecode1,timecode2,timecode3
        https://www.youtube.com/watch?v=dQw4w9WgXcQ,3:25,10:00-11:30,25:00

    Timecodes may be a single point ("MM:SS") or a range ("MM:SS-MM:SS").
    Empty timecode cells are silently ignored.

    Caption rows (stacked format only) — a plain-text line before a URL becomes
    a 2-second section title card inserted before the first clip of that URL:
        url,...
        Player highlights
        https://…
        3:25

    Alternatively use a 'caption' column in the header for the same effect.
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

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4v", ".m4s"}


# ─── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class ClipSpec:
    url: str
    raw_timecode: str  # original CSV value — used for display on title card
    start_secs: float  # padded extraction start
    end_secs: float    # padded extraction end
    clip_num: int      # sequential 1-based clip number across all rows
    row_num: int       # 1-based source CSV row number
    caption: str = "" # optional section title shown before the first clip of this URL


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

def generate_caption_card(caption: str, output_path: Path) -> bool:
    """Render a 2-second black card with large centred caption text."""
    img  = Image.new("RGB", (VWIDTH, VHEIGHT), color="black")
    draw = ImageDraw.Draw(img)
    font = _load_font(72)

    lines   = textwrap.wrap(caption, width=40) or [caption]
    line_h  = draw.textbbox((0, 0), "Ag", font=font)[3]
    total_h = line_h * len(lines) + 8 * (len(lines) - 1)
    y = (VHEIGHT - total_h) // 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((VWIDTH - w) // 2, y), line, fill="white", font=font)
        y += line_h + 8

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
    log.debug("Caption card encode cmd: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    png_path.unlink(missing_ok=True)
    if r.returncode != 0:
        log.error("Caption card encoding failed:\n%s", r.stderr[-2000:])
        return False
    return True


def generate_title_card(
    url: str, timecodes: list[str], output_path: Path, caption: str = ""
) -> bool:
    """
    Render a 2-second black title card (one per URL) showing, from top to bottom:
      - Caption / section name (large, if provided)
      - URL (small)
      - All timecodes joined with " | "
    """
    img  = Image.new("RGB", (VWIDTH, VHEIGHT), color="black")
    draw = ImageDraw.Draw(img)

    font_caption = _load_font(64)
    font_url     = _load_font(28)
    font_tc      = _load_font(40)

    def _centre_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, y: int) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((VWIDTH - w) // 2, y), text, fill="white", font=font)

    gap = 28

    # Caption — large heading, optional
    cap_lines = (textwrap.wrap(caption, width=40) or [caption]) if caption else []
    cap_line_h = draw.textbbox((0, 0), "Ag", font=font_caption)[3] + 6
    cap_total_h = cap_line_h * len(cap_lines)

    # URL — wrap to at most 2 lines
    url_lines  = textwrap.wrap(url, width=80) or [url]
    url_line_h = draw.textbbox((0, 0), "Ag", font=font_url)[3] + 4
    url_total_h = url_line_h * min(len(url_lines), 2)

    # Timecodes
    tc_str    = "  |  ".join(timecodes)
    tc_lines  = textwrap.wrap(tc_str, width=60) or [tc_str]
    tc_line_h = draw.textbbox((0, 0), "Ag", font=font_tc)[3] + 8
    tc_total_h = tc_line_h * len(tc_lines)

    sections = [s for s in [cap_total_h, url_total_h, tc_total_h] if s]
    total_h  = sum(sections) + gap * (len(sections) - 1)
    y = (VHEIGHT - total_h) // 2

    for line in cap_lines:
        _centre_text(line, font_caption, y)
        y += cap_line_h
    if cap_lines:
        y += gap

    for line in url_lines[:2]:
        _centre_text(line, font_url, y)
        y += url_line_h
    y += gap

    for line in tc_lines:
        _centre_text(line, font_tc, y)
        y += tc_line_h

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


_PLATFORM_MARKERS = ("pixellot.link", "live.veo.co")


def _resolve_url(url: str) -> str:
    """Translate a platform share link into a direct stream URL."""
    if "pixellot.link" in url:
        try:
            from pixellot_scraper import extract_stream_url as _pixellot
            log.info("  Resolving Pixellot share link…")
            resolved = _pixellot(url)
            if resolved:
                log.info("  → %s", resolved)
                return resolved
            log.warning("  Pixellot scraper returned nothing — keeping original")
        except ImportError:
            log.warning("  pixellot_scraper.py not found — keeping original")
        except Exception as exc:
            log.warning("  Pixellot scraper error (%s) — keeping original", exc)

    if "live.veo.co" in url:
        try:
            from veo_scraper import extract_stream_url as _veo
            log.info("  Resolving live.veo.co URL…")
            resolved = _veo(url)
            if resolved:
                log.info("  → %s", resolved)
                return resolved
            log.warning("  Veo scraper returned nothing — keeping original")
        except ImportError:
            log.warning("  veo_scraper.py not found — keeping original")
        except Exception as exc:
            log.warning("  Veo scraper error (%s) — keeping original", exc)

    return url


def resolve_csv(input_path: Path, out_dir: Optional[Path] = None) -> Path:
    """
    Scan *input_path* for Pixellot share links and live.veo.co URLs, run the
    appropriate scraper for each, and write a *_resolved.csv with the direct
    stream URLs substituted in.  The resolved file is placed in *out_dir* when
    given, otherwise next to the original.  Returns the resolved file path (or
    the original path if nothing needed resolving).
    """
    text = input_path.read_text(encoding="utf-8-sig")

    # Quick check — skip the expensive scan if no platform markers present
    if not any(m in text for m in _PLATFORM_MARKERS):
        return input_path

    # Collect every unique platform URL appearing anywhere in the file
    platform_urls: list[str] = []
    for token in re.split(r'[\s,"]+', text):
        token = token.strip().rstrip("/")
        if _looks_like_url(token) and any(m in token for m in _PLATFORM_MARKERS):
            if token not in platform_urls:
                platform_urls.append(token)

    if not platform_urls:
        return input_path

    log.info("Found %d platform URL(s) to resolve:", len(platform_urls))
    replacements: dict[str, str] = {}
    for url in platform_urls:
        log.info("  %s", url)
        resolved = _resolve_url(url)
        if resolved != url:
            replacements[url] = resolved

    if not replacements:
        log.warning("No URLs could be resolved — using original CSV")
        return input_path

    new_text = text
    for orig, resolved in replacements.items():
        new_text = new_text.replace(orig, resolved)

    dest_dir = out_dir if out_dir is not None else input_path.parent
    out_path = dest_dir / (input_path.stem + "_resolved" + input_path.suffix)
    out_path.write_text(new_text, encoding="utf-8")
    log.info("Resolved CSV written: %s", out_path)
    return out_path


def download_full_video(url: str, stem: Path, browser: Optional[str] = None) -> Optional[Path]:
    """
    Download the complete video at highest quality via yt-dlp.
    stem is the output path without extension (e.g. temp_clips/full_abc123).
    browser, if set, is passed as cookiesfrombrowser (e.g. "safari", "chrome").
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
    if browser:
        ydl_opts["cookiesfrombrowser"] = (browser,)
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


def concatenate_clips(segments: list[Path], output_path: Path) -> bool:
    """
    Normalise and concatenate segments in a single ffmpeg pass.

    Each input is scaled/padded to 1920×1080, converted to 30 fps and yuv420p,
    and resampled to stereo 44.1 kHz — eliminating the need for a separate
    per-clip normalise step.  Inputs without an audio stream automatically
    receive a silent stereo track.
    """
    n = len(segments)

    # Pre-check which segments have audio so we can inject silence where needed
    audio_present = [has_audio(p) for p in segments]

    # Append one anullsrc input per silent segment
    silent_inputs: list[str] = []
    silent_idx: dict[int, int] = {}   # segment index → its silent-audio input index
    next_idx = n
    for i, has_aud in enumerate(audio_present):
        if not has_aud:
            silent_inputs += [
                "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SR}",
            ]
            silent_idx[i] = next_idx
            next_idx += 1

    scale_chain = (
        f"scale={VWIDTH}:{VHEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VWIDTH}:{VHEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={VFPS},"
        f"format=yuv420p"
    )

    v_filters = [f"[{i}:v]{scale_chain}[v{i}]" for i in range(n)]
    a_filters = [
        f"[{i}:a]aresample={AUDIO_SR},aformat=channel_layouts=stereo[a{i}]"
        if audio_present[i]
        else f"[{silent_idx[i]}:a]aresample={AUDIO_SR}[a{i}]"
        for i in range(n)
    ]
    concat_in  = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_complex = ";".join(v_filters + a_filters) + f";{concat_in}concat=n={n}:v=1:a=1[vout][aout]"

    inputs: list[str] = []
    for p in segments:
        inputs += ["-i", str(p)]

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        *silent_inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
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
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def add_file_logging(log_file: Path) -> None:
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(handler)


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


def _looks_like_caption(s: str) -> bool:
    """Non-empty text that is neither a URL nor a timecode — treated as a section caption."""
    s = s.strip()
    return bool(s) and not _looks_like_url(s) and not _looks_like_timecode(s)


def preprocess_rows(rows: list[dict]) -> list[dict]:
    """
    Normalize mixed-format rows into standard {url, caption, timecode1, timecode2, ...} dicts.

    Handles these layouts (may be mixed in the same file):

      Standard (timecodes in columns):
        url,timecode1,timecode2
        https://…,3:25,0:05

      Stacked (timecodes on their own lines below the URL):
        url,...
        https://…
        2:10-2:45
        2:58

      Caption (plain text line before a URL becomes a section title card):
        url,...
        Player highlights
        https://…
        3:25
    """
    result: list[dict] = []
    pending_caption: str = ""
    for row in rows:
        url_field = row.get("url", "")
        if _looks_like_url(url_field):
            new_row = dict(row)
            # Attach stacked caption if the row doesn't already have a caption column
            if pending_caption and not new_row.get("caption", ""):
                new_row["caption"] = pending_caption
            pending_caption = ""
            result.append(new_row)
        elif _looks_like_timecode(url_field) and result:
            # Stacked timecode row — attach to the most recent URL row
            prev = result[-1]
            i = 1
            while prev.get(f"timecode{i}", ""):
                i += 1
            prev[f"timecode{i}"] = url_field
        elif _looks_like_caption(url_field):
            pending_caption = url_field
        # else: blank row — silently skip
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
                    caption=row.get("caption", ""),
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
        "--browser", default=None, metavar="BROWSER",
        help="Pass cookies from this browser to yt-dlp for authenticated sites "
             "(e.g. safari, chrome, firefox). Required for Veo, Pixellot, etc.",
    )
    p.add_argument(
        "--split", action="store_true",
        help="Produce one output video per URL instead of a single combined file",
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

    # Create run dir early so resolved CSV and logs land inside it
    run_id   = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_stem = re.sub(r"[^\w]+", "_", args.csv_file.stem).strip("_").lower()
    run_dir  = RUNS_DIR / f"{csv_stem}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    add_file_logging(run_dir / "run.log")

    # Copy original CSV into run folder, then resolve platform URLs
    shutil.copy2(args.csv_file, run_dir / args.csv_file.name)
    csv_path = resolve_csv(args.csv_file, out_dir=run_dir)

    rows = read_csv(csv_path)
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

    temp_dir = run_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    output = args.output or run_dir / f"highlights_{csv_stem}_{run_id}.mp4"

    # Cache: url -> downloaded full-video Path (or None if download failed)
    url_cache: dict[str, Optional[Path]] = {}
    title_emitted: set[str] = set()

    unique_urls = list(dict.fromkeys(s.url for s in specs))
    log.info(
        "%d unique URL(s) across %d clip(s) — each video downloaded once.",
        len(unique_urls), len(specs),
    )

    # Pre-build per-URL metadata needed for title cards and split naming
    url_timecodes: dict[str, list[str]] = {}
    url_captions:  dict[str, str]       = {}
    for s in specs:
        url_timecodes.setdefault(s.url, []).append(s.raw_timecode)
        url_captions.setdefault(s.url, s.caption)

    # segments_per_url preserves URL order and collects title card + raw clips
    segments_per_url: dict[str, list[Path]] = {url: [] for url in unique_urls}

    try:
        for spec in specs:
            log.info(
                "── Clip %d/%d  (row %d)  timecode=%s  window=[%.1fs, %.1fs]  url=%s",
                spec.clip_num, len(specs), spec.row_num,
                spec.raw_timecode, spec.start_secs, spec.end_secs,
                spec.url,
            )

            # Once per URL: title card with caption + URL + all timecodes
            if spec.url not in title_emitted:
                all_tcs    = url_timecodes[spec.url]
                title_path = temp_dir / f"title_{_url_hash(spec.url)}.mp4"
                log.info(
                    "  Generating title card (caption=%r, %d timecode(s))...",
                    spec.caption, len(all_tcs),
                )
                if not generate_title_card(spec.url, all_tcs, title_path, caption=spec.caption):
                    log.error("  Title card failed for URL — skipping clip %d", spec.clip_num)
                    title_emitted.add(spec.url)
                    continue
                segments_per_url[spec.url].append(title_path)
                title_emitted.add(spec.url)

            # Download full video once per URL, then extract the needed window
            if spec.url not in url_cache:
                full_stem = temp_dir / f"full_{_url_hash(spec.url)}"
                log.info("  [1/2] Downloading full video (first use of this URL)...")
                url_cache[spec.url] = download_full_video(spec.url, full_stem, args.browser)
            else:
                log.info("  [1/2] Using cached video for this URL.")

            full_video = url_cache[spec.url]
            if full_video is None:
                log.error("  Video unavailable — skipping clip %d", spec.clip_num)
                continue

            raw_path = temp_dir / f"raw_{spec.clip_num:03d}.mp4"
            log.info(
                "  [2/2] Extracting window  %.1fs – %.1fs...",
                spec.start_secs, spec.end_secs,
            )
            if not extract_clip(full_video, spec.start_secs, spec.end_secs, raw_path):
                log.error("  Extraction failed — skipping clip %d", spec.clip_num)
                continue

            segments_per_url[spec.url].append(raw_path)
            log.info("  Clip %d done.", spec.clip_num)

        any_success = any(segs for segs in segments_per_url.values())
        if not any_success:
            log.error("No clips processed successfully — nothing to concatenate.")
            sys.exit(1)

        outputs: list[Path] = []

        if args.split:
            # One output file per URL
            for idx, url in enumerate(unique_urls, start=1):
                segs = segments_per_url[url]
                if not segs:
                    log.warning("No segments for URL %s — skipping.", url)
                    continue
                caption = url_captions.get(url, "")
                slug = re.sub(r"\s+", "_", re.sub(r"[^\w\s]", "", caption)).strip("_")
                name = f"{idx:02d}_{slug}.mp4" if slug else f"{idx:02d}_{_url_hash(url)}.mp4"
                url_output = run_dir / name
                log.info("Concatenating %d segment(s) → %s...", len(segs), name)
                if concatenate_clips(segs, url_output):
                    log.info("Output: %s  (%.1f MB)", url_output, url_output.stat().st_size / 1e6)
                    outputs.append(url_output)
                else:
                    log.error("Concatenation failed for %s", url)
        else:
            all_segments = [seg for url in unique_urls for seg in segments_per_url[url]]
            log.info("Concatenating %d segment(s)...", len(all_segments))
            if not concatenate_clips(all_segments, output):
                log.error("Concatenation failed.")
                sys.exit(1)
            log.info("Output: %s  (%.1f MB)", output, output.stat().st_size / 1e6)
            outputs.append(output)

        if args.upload_gdrive:
            for out_file in outputs:
                link = upload_to_gdrive(out_file)
                if link:
                    print(f"\nShareable Google Drive link ({out_file.name}):\n  {link}\n")
                else:
                    log.error("Google Drive upload failed for %s", out_file.name)

    finally:
        if not args.keep_temp:
            log.info("Removing temp dir %s", temp_dir)
            shutil.rmtree(temp_dir, ignore_errors=True)
        log.info("Run folder: %s", run_dir)

    log.info("Done.")


if __name__ == "__main__":
    main()
