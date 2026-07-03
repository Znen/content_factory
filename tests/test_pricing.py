import pytest
from gf.pricing import estimate


def test_nano_per_image():
    assert estimate("nano", 1) == pytest.approx(0.04)
    assert estimate("nano", 3) == pytest.approx(0.12)


def test_comfyui_is_free():
    assert estimate("comfyui", 4) == 0.0


def test_unknown_backend_is_free():
    assert estimate("something", 2) == 0.0
