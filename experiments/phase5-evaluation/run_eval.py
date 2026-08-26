"""Phase 5 manual-evaluation harness: inspect evidence-graph quality by hand.

Indexes one local PDF once, then runs a fixed query set through the full
AnswerPipeline so a human can judge passage selection, node roles,
relationship sanity and answer coherence per query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

API_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
HAS_API_KEY = any(os.environ.get(name) for name in API_KEY_ENVS)
if not HAS_API_KEY:
    # bfpc.api.app constructs IndexService(Embedder()) at import time; the
    # placeholder keeps that import alive for offline/mock runs where the
    # real Embedder is never instantiated.
    os.environ["GEMINI_API_KEY"] = "offline-mock-placeholder"

import numpy as np

from bfpc.api.service import IndexService
from bfpc.context import AnswerPipeline, ContextBuilder, LLMContext, create_generator
from bfpc.index.embedder import Embedder

QUERIES_PATH = HERE / "eval_queries.json"
DEFAULT_PDF = ROOT / "tests" / "fixtures" / "report.pdf"
OFFLINE_DIM = 512


class OfflineEmbedder:
    """Deterministic hashing embedder so ``--provider mock`` needs no network."""

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vector(text) for text in texts]).astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        return self._vector(query).astype(np.float32)

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(OFFLINE_DIM, dtype=np.float64)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % OFFLINE_DIM] += 1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector


class RecordingRetriever:
    """Wraps IndexService, keeping the hits of the most recent search."""

    def __init__(self, service: IndexService) -> None:
        self._service = service
        self.last_hits: list[dict] = []

    def search(self, query: str, top_k: int) -> dict:
        results = self._service.search(query, top_k=top_k)
        self.last_hits = results.get("hits", [])
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual evidence-graph evaluation over one local PDF."
    )
    parser.add_argument("--pdf", default=str(DEFAULT_PDF), help="corpus PDF path")
    parser.add_argument(
        "--provider", choices=("gemini", "mock"), default="gemini",
        help="generator backend; mock runs fully offline",
    )
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name")
    parser.add_argument("--out", default=None, help="optional path for results JSON")
    return parser.parse_args()


def source_rows(context: LLMContext) -> list[dict]:
    rows = []
    for source in context.sources:
        original = context.original(source.source_id) or {}
        rows.append(
            {
                "source_id": source.source_id,
                "chunk_id": source.chunk_id,
                "page": source.page,
                "kind": source.kind,
                "score": round(float(original.get("score", 0.0)), 4),
            }
        )
    return rows


def print_run(record: dict) -> None:
    print("-" * 78)
    print(f"[{record['id']}] {record['query']}")
    if "error" in record:
        print(f"  ERROR  : {record['error']}")
        return
    status = record.get("status") or "(no status field in current EvidenceResult)"
    print(f"  status : {status}")
    if record.get("missing"):
        print(f"  missing: {record['missing']}")
    print(f"  answer : {record['answer']}")
    by_sid = {row["source_id"]: row for row in record["sources"]}
    print("  nodes  :")
    if record["nodes"]:
        for node in record["nodes"]:
            row = by_sid.get(node["source_id"])
            where = f"p{row['page']} {row['kind']}" if row else "?"
            print(f"    {node['source_id']:<9} {node['role']:<12} ({where})")
    else:
        print("    (none)")
    print("  rels   :")
    if record["relationships"]:
        for rel in record["relationships"]:
            print(f"    {rel['from']} -[{rel['type']}]-> {rel['to']}")
    else:
        print("    (none)")
    print("  context:")
    for row in record["sources"]:
        print(
            f"    {row['source_id']:<9} p{row['page']:<3} {row['kind']:<8} "
            f"chunk={row['chunk_id']:<8} score={row['score']}"
        )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        return 2
    if not QUERIES_PATH.is_file():
        print(f"error: query set not found: {QUERIES_PATH}", file=sys.stderr)
        return 2
    if args.provider == "gemini" and not HAS_API_KEY:
        print(
            "error: --provider gemini requires GEMINI_API_KEY (or GOOGLE_API_KEY) "
            "in the environment; use --provider mock for an offline run.",
            file=sys.stderr,
        )
        return 2

    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    embedder = Embedder() if args.provider == "gemini" else OfflineEmbedder()
    service = IndexService(embedder)
    index_summary = service.index(pdf_path.read_bytes(), pdf_path.name)
    print(
        f"indexed {pdf_path.name}: {index_summary['pages']} pages, "
        f"{index_summary['chunks']} chunks"
    )

    generator = create_generator(provider=args.provider, model=args.model)
    retriever = RecordingRetriever(service)
    builder = ContextBuilder()
    pipeline = AnswerPipeline(retriever=retriever, generator=generator, builder=builder)

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pdf": str(pdf_path),
        "provider": args.provider,
        "model": args.model if args.provider == "gemini" else "(mock)",
        "index": index_summary,
        "runs": [],
    }

    for entry in queries:
        record: dict = {
            "id": entry["id"],
            "query": entry["query"],
            "expectation": entry["expectation"],
        }
        try:
            result = pipeline.answer(entry["query"])
            context = builder.build(retriever.last_hits)
            record.update(
                {
                    "sources": source_rows(context),
                    "answer": result.answer,
                    "status": getattr(result, "status", None),
                    "missing": getattr(result, "missing", None),
                    "nodes": [node.model_dump() for node in result.nodes],
                    "relationships": [
                        {"from": rel.from_id, "to": rel.to, "type": rel.type}
                        for rel in result.relationships
                    ],
                }
            )
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        results["runs"].append(record)
        print_run(record)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {out_path}")

    errors = sum(1 for run in results["runs"] if "error" in run)
    print(f"\n{len(results['runs'])} queries, {errors} errors, provider={args.provider}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
