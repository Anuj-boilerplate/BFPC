"""Indexing layer: chunking, embedding, and vector search.

This package is the foundation for BFPC's retrieval pipeline. Chunking
strategies live in :mod:`bfpc.index.chunkers` and register themselves in
the :data:`bfpc.index.chunker.REGISTRY`; the embedder wraps
nomic-embed-text-v1.5; the index is an exact-cosine FAISS index.
"""
