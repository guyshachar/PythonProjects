"""
Job pricing logic.

Pricing model:
  • $0.50  per clip extracted
  • $0.20  per estimated minute of output video
  • $0.50  per-URL surcharge when output_strategy == "multiple" (beyond the first URL)

All values are USD. Replace constants with live config / DB lookup as needed.
"""

from web.models import JobQuoteRequest

PRICE_PER_CLIP       = 0.50   # USD per timecode entry
PRICE_PER_MINUTE     = 0.20   # USD per estimated output minute
SPLIT_SURCHARGE_URL  = 0.50   # extra per URL when generating separate files
AVG_CLIP_SECS_BASE   = 30     # assumed clip duration before padding


def calculate_job_price(req: JobQuoteRequest) -> dict:
    """Return a price breakdown dict compatible with JobQuoteResponse."""
    total_clips = sum(len(row.timecodes) for row in req.video_rows)
    unique_urls = len({row.url for row in req.video_rows})

    avg_secs = req.config.pad_before + AVG_CLIP_SECS_BASE + req.config.pad_after
    estimated_minutes = round((total_clips * avg_secs) / 60, 1)

    clip_price     = round(total_clips * PRICE_PER_CLIP, 2)
    duration_price = round(estimated_minutes * PRICE_PER_MINUTE, 2)

    split_surcharge = 0.0
    if req.config.output_strategy == "multiple" and unique_urls > 1:
        split_surcharge = round((unique_urls - 1) * SPLIT_SURCHARGE_URL, 2)

    total = round(clip_price + duration_price + split_surcharge, 2)

    return {
        "total_clips":             total_clips,
        "unique_urls":             unique_urls,
        "estimated_duration_mins": estimated_minutes,
        "price":                   total,
        "breakdown": {
            "clips":          clip_price,
            "duration":       duration_price,
            "split_surcharge": split_surcharge,
        },
    }
