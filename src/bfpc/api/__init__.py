"""BFPC local HTTP API.

Implements the contract in ``docs/api.md`` exactly: four endpoints over a
single active document, with the block chunker, nomic-embed-text-v1.5 and
an exact-cosine FAISS index.
"""

from __future__ import annotations

from bfpc.api.app import create_app, app

__all__ = ["create_app", "app"]
