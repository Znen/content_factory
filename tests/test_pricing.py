import pytest
from gf.pricing import estimate, estimate_dreamina_credits, estimate_magnific


def test_nano_per_image():
    assert estimate("nano", 1) == pytest.approx(0.04)
    assert estimate("nano", 3) == pytest.approx(0.12)


def test_comfyui_is_free():
    assert estimate("comfyui", 4) == 0.0


def test_unknown_backend_is_free():
    assert estimate("something", 2) == 0.0


def test_dreamina_credits_known_pairs_5s():
    # из DREAMINA_CLI.md (multimodal, 5с): fast_vip 720p=55, _vip 720p=70, _vip 1080p=165
    assert estimate_dreamina_credits("seedance2.0fast_vip", "720p", 5) == 55
    assert estimate_dreamina_credits("seedance2.0_vip", "720p", 5) == 70
    assert estimate_dreamina_credits("seedance2.0_vip", "1080p", 5) == 165


def test_dreamina_credits_scale_with_duration():
    # таблица — на ~5с; 10с ≈ ×2
    assert estimate_dreamina_credits("seedance2.0_vip", "720p", 10) == 140


def test_dreamina_credits_unknown_pair_conservative_max():
    # неизвестная (model, resolution) → консервативный максимум (§5.4)
    assert estimate_dreamina_credits("seedance2.0", "720p", 5) == 165


def test_magnific_known_models():
    assert estimate_magnific("mystic", 1) == pytest.approx(0.10)
    assert estimate_magnific("seedream-v4-5-edit", 1) == pytest.approx(0.06)
    assert estimate_magnific("flux-kontext-pro", 2) == pytest.approx(0.10)


def test_magnific_unknown_model_conservative_default():
    assert estimate_magnific("whatever", 1) == pytest.approx(0.10)
