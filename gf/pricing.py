"""Flat per-image cost estimate. Decoupled from any registry/project structure."""

_PER_IMAGE_USD = {
    "nano": 0.04,       # Nitro/Gemini image, from old fallback table
    "comfyui": 0.0,     # local GPU, no marginal cost
}


def estimate(backend: str, n: int = 1) -> float:
    """USD estimate for generating `n` images on `backend`. Unknown → free."""
    per = _PER_IMAGE_USD.get(backend, 0.0)
    return round(per * max(0, n), 4)


_TOKEN_USD_PER_MTOK = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
}
_DEFAULT_TOKEN_USD = (5.0, 25.0)


def estimate_llm(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD за один LLM-вызов по usage-токенам. Неизвестная модель -> консервативный дефолт."""
    inp, out = _TOKEN_USD_PER_MTOK.get(model, _DEFAULT_TOKEN_USD)
    return round((max(0, input_tokens) * inp + max(0, output_tokens) * out) / 1_000_000, 4)
