import json
import runpy
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def synthetic_candles():
    root = Path(__file__).parents[1]
    target = root / "fixtures" / "candles_synthetic.json"
    if not target.exists():
        build = runpy.run_path(str(root / "scripts" / "make_fixtures.py"))["build"]
        target.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
