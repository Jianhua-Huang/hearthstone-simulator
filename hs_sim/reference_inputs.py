"""Resolve retained source evidence without depending on local build outputs."""
from pathlib import Path


def reference_path(recorded_path, *, root=None):
    root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    path = Path(recorded_path)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Reference input must be a repository-relative path')
    if path.parts and path.parts[0] == 'outputs':
        path = Path('data/reference').joinpath(*path.parts[1:])
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Reference input escaped the repository')
    return result
