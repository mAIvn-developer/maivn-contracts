"""Import every installed contracts module and read every canonical schema family."""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import pkgutil
import sys

DOMAINS = (
    'agents',
    'artifacts',
    'events',
    'flows',
    'messages',
    'resources',
    'runtime',
    'scenarios',
    'tools',
    'workers',
)
PROJECTIONS = ('audit', 'billing', 'canvas', 'replay', 'trace', 'webhook')


def _import_tree(name: str, imported: list[str]) -> None:
    """Import all children without swallowing missing modules or optional dependencies."""
    module = importlib.import_module(name)
    imported.append(name)
    for child in pkgutil.iter_modules(getattr(module, '__path__', ()), name + '.'):
        _import_tree(child.name, imported)


def main() -> None:
    """Exercise data reads as well as imports so missing wheel resources fail early."""
    imported: list[str] = []
    _import_tree('maivn_contracts', imported)
    loaded: list[str] = []
    for domain in DOMAINS:
        module = importlib.import_module(f'maivn_contracts.{domain}.loaders')
        for name, loader in inspect.getmembers(module, inspect.isfunction):
            if (
                name.startswith('load_')
                and loader.__module__ == module.__name__
                and not inspect.signature(loader).parameters
            ):
                loader()
                loaded.append(f'{module.__name__}.{name}')
    events = importlib.import_module('maivn_contracts.events')
    for projection in PROJECTIONS:
        events.load_projection(projection)
        loaded.append(f'maivn_contracts.events.load_projection({projection})')
    sys.stdout.write(
        json.dumps(
            {
                'contracts_version': importlib.metadata.version('maivn-contracts'),
                'imported_count': len(imported),
                'imported': imported,
                'loader_count': len(loaded),
                'loader_calls': loaded,
            },
            indent=2,
        )
        + '\n'
    )


if __name__ == '__main__':
    main()
