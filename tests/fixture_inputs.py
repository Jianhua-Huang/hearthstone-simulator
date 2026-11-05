"""Explicit relocation of unchanged historical regression inputs."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def fixture_input_map():
    data = json.loads((ROOT / 'tests/fixtures/input-manifest.json').read_text(encoding='utf8'))
    return {old: row['path'] for old, row in data.items()}


def fixture_path(recorded_path):
    return ROOT / fixture_input_map().get(recorded_path, recorded_path)


def fixture_manifest(manifest):
    paths = fixture_input_map()
    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return paths.get(value, value) if isinstance(value, str) else value
    return relocate(deepcopy(manifest))
