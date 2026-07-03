"""Flat per-image cost estimate. Decoupled from any registry/project structure."""

_PER_IMAGE_USD = {
    "nano": 0.04,       # Nitro/Gemini image, from old fallback table
    "comfyui": 0.0,     # local GPU, no marginal cost
}


def estimate(backend: str, n: int = 1) -> float:
    """USD estimate for generating `n` images on `backend`. Unknown → free."""
    per = _PER_IMAGE_USD.get(backend, 0.0)
    return round(per * max(0, n), 4)
