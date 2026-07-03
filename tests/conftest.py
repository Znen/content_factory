import os
import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("GF_RUN_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live service test; set GF_RUN_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
