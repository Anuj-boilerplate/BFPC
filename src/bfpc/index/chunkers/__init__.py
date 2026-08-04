"""Chunking strategies for the experiment sweep.

Modules in this package register a strategy with ``@register`` at import
time and are auto-discovered, so a new strategy is just a new file:
no package edits needed.
"""

from __future__ import annotations

import importlib
import pkgutil

_discovered = False


def _discover() -> None:
    """Import every module in this package so strategies register themselves."""
    global _discovered
    if _discovered:
        return
    for module_info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module_info.name}")
    _discovered = True


_discover()
