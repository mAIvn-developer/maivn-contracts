"""Locate bundled schema data or the verified canonical source checkout."""

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_PACKAGED = _PACKAGE_ROOT / '_schemas'
_CHECKOUT = _PACKAGE_ROOT.parents[1]


def _is_contracts_checkout() -> bool:
    manifest = _CHECKOUT / 'pyproject.toml'
    return (
        _PACKAGE_ROOT.parent.name == 'src'
        and manifest.is_file()
        and 'name = "maivn-contracts"' in manifest.read_text(encoding='utf-8').splitlines()
    )


# Missing installed data must fail in the package, never read application files.
SCHEMA_ROOT = _CHECKOUT if not _PACKAGED.is_dir() and _is_contracts_checkout() else _PACKAGED
