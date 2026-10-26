"""Package resources win; only the owning source checkout may use root schemas."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest


def _load_root(tmp_path: Path, manifest: str, *, packaged: bool) -> tuple[Path, Path]:
    source = Path(__file__).resolve().parents[2] / 'src/maivn_contracts/_schema_root.py'
    package = tmp_path / 'src/maivn_contracts'
    package.mkdir(parents=True)
    module = package / '_schema_root.py'
    module.write_bytes(source.read_bytes())
    (tmp_path / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    if packaged:
        (package / '_schemas').mkdir()
    result = runpy.run_path(str(module))['SCHEMA_ROOT']
    assert isinstance(result, Path)
    return result, package


def test_verified_checkout_reads_canonical_root(tmp_path: Path) -> None:
    """Source development keeps root JSON as the single maintained authority."""
    root, package = _load_root(tmp_path, '[project]\nname = "maivn-contracts"\n', packaged=False)
    assert root == tmp_path
    assert not (package / '_schemas').exists()


def test_packaged_data_wins_over_source_marker(tmp_path: Path) -> None:
    """Even a matching source marker cannot shadow bundled installed data."""
    root, package = _load_root(tmp_path, '[project]\nname = "maivn-contracts"\n', packaged=True)
    assert root == package / '_schemas'


@pytest.mark.parametrize('manifest', ['', '[project]\nname = "foreign-app"\n'])
def test_foreign_target_named_src_does_not_read_parent_data(tmp_path: Path, manifest: str) -> None:
    """A missing package resource stays missing instead of reading application data."""
    root, package = _load_root(tmp_path, manifest, packaged=False)
    (tmp_path / 'events').mkdir()
    (tmp_path / 'events/taxonomy.json').write_text('{"foreign": true}', encoding='utf-8')
    assert root == package / '_schemas'
    with pytest.raises(FileNotFoundError):
        (root / 'events/taxonomy.json').read_text(encoding='utf-8')
