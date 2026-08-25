"""Indexing layer: chunking, embedding, and vector search.

This package is the foundation for BFPC's retrieval pipeline. Chunking
strategies live in :mod:`bfpc.index.chunkers` and register themselves in
the :data:`bfpc.index.chunker.REGISTRY`; the embedder calls the Gemini
embedding API (gemini-embedding-001, 3072-dim); the index is an
exact-cosine FAISS index.
"""
