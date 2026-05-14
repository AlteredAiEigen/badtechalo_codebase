"""Map ``GET /books/{id}/index-status`` JSON to a coarse 0–1 fraction for progress UIs."""

from __future__ import annotations


def estimate_index_fraction(data: dict) -> tuple[float, str]:
    """
    Return (fraction, short_label). Fraction is in [0, 1] for display only
    (not exact wall-time share; chunk/embedding times vary per page).
    """
    status = (data.get("index_status") or "idle").lower()
    if status == "completed":
        return 1.0, "completed"
    if status == "failed":
        return 0.0, "failed"

    p = data.get("index_progress") or {}
    phase = (p.get("phase") or "").lower()
    try:
        tp = max(int(p.get("total_pages") or 0), 0)
    except (TypeError, ValueError):
        tp = 0
    try:
        pi = int(p.get("page_index") or 0)
    except (TypeError, ValueError):
        pi = 0

    if tp <= 0:
        return (0.05 if status == "running" else 0.0), phase or status

    if phase in ("queued",):
        return 0.02, "queued"
    if phase == "starting":
        return 0.05, "starting"

    if phase == "chunking":
        done = max(pi - 1, 0)
        frac = (done + 0.35) / tp
        return max(0.0, min(1.0, frac)), f"p.{pi}/{tp} segment"
    if phase == "embedding":
        done = max(pi - 1, 0)
        frac = (done + 0.72) / tp
        return max(0.0, min(1.0, frac)), f"p.{pi}/{tp} embed"
    if phase == "page_done":
        return max(0.0, min(1.0, pi / tp)), f"p.{pi}/{tp} done"

    if pi > 0:
        return max(0.0, min(1.0, pi / tp)), phase or "running"
    return 0.08, phase or status
