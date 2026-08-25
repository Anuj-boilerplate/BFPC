"""Phase 10 — Graph → ordered reading trail."""

from __future__ import annotations

from collections import defaultdict, deque

from bfpc.context.builder import LLMContext
from bfpc.context.evidence import EvidenceResult
from bfpc.context.trail import BBox, ReadingTrail, TrailItem


_ROLE_LABELS: dict[str, str] = {
    "context": "Context",
    "supporting": "Evidence",
    "definition": "Definition",
    "example": "Example",
    "conclusion": "Conclusion",
}


def _role_label(role: str) -> str:
    return _ROLE_LABELS.get(role, role.capitalize())


def build_trail(
    result: EvidenceResult,
    context: LLMContext,
    pdf_bytes: bytes | None = None,
) -> ReadingTrail:
    """Build an ordered reading trail from an evidence graph.

    Ordering:
      1. Adjacency from ``result.relationships``
      2. BFS depth from roots (no incoming edges)
      3. Isolated nodes fallback to ``result.nodes`` order

    Explanation: top-ranked sentence via ``sentence_ranker.rank_sentences``.
    Rects: locate_words → locate_text fallback, [] on failure or non-PDF.
    """
    # Validate every node source_id exists in context
    for node in result.nodes:
        if context.original(node.source_id) is None and not any(s.source_id == node.source_id for s in context.sources):
            # Also check sources tuple for existence
            raise KeyError(f"unknown source_id '{node.source_id}' not in context")

    # Build maps
    nodes_by_id: dict[str, object] = {}
    order_index: dict[str, int] = {}
    for idx, node in enumerate(result.nodes):
        nodes_by_id[node.source_id] = node
        order_index[node.source_id] = idx

    # Adjacency and incoming count
    adj: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, int] = {n.source_id: 0 for n in result.nodes}
    for rel in result.relationships:
        # rel.from_id and rel.to are source_ids; ensure they exist in graph
        # EvidenceResult validation already ensures nodes exist, but be defensive
        if rel.from_id in incoming and rel.to in incoming:
            adj[rel.from_id].append(rel.to)
            incoming[rel.to] += 1

    # Roots: no incoming edges
    roots = [n.source_id for n in result.nodes if incoming.get(n.source_id, 0) == 0]

    # BFS depth
    depth: dict[str, int] = {}
    q: deque[str] = deque()
    # Enqueue roots in node order for determinism
    for sid in sorted(roots, key=lambda x: order_index.get(x, 0)):
        depth[sid] = 0
        q.append(sid)

    # If cyclic (no roots), treat all nodes as depth 0 in node order
    if not roots and result.nodes:
        for node in result.nodes:
            depth[node.source_id] = 0
    else:
        while q:
            cur = q.popleft()
            cur_depth = depth[cur]
            for nb in adj.get(cur, []):
                if nb not in depth:
                    depth[nb] = cur_depth + 1
                    q.append(nb)
                # If already visited via shorter path, keep earliest depth (BFS)
                # To handle longer path, we could update if larger, but keep first

    # For nodes not visited (disconnected component with cycle), assign depth as max+1 or preserve order
    # Fall back to node order for isolated (degree 0) – but our depth already handles.
    # Ensure all nodes have depth
    max_depth = max(depth.values(), default=0)
    for node in result.nodes:
        if node.source_id not in depth:
            # Assign after max depth, preserving node order
            depth[node.source_id] = max_depth + 1 + order_index[node.source_id] * 0.001  # ensure order

    # Sort nodes by (depth, order_index)
    # For isolated nodes (no edges), depth will be 0, so they intermix by order_index – matches fallback
    sorted_nodes = sorted(result.nodes, key=lambda n: (depth.get(n.source_id, 0), order_index[n.source_id]))

    # Build TrailItems in sorted order
    items: list[TrailItem] = []
    # Lazy imports for rank and locator
    try:
        from bfpc.index.sentence_ranker import rank_sentences
    except Exception:
        rank_sentences = None  # type: ignore

    for node in sorted_nodes:
        sid = node.source_id
        role = node.role  # type: ignore[attr-defined]
        label = _role_label(role)

        # Resolve source text and page via context
        # Prefer LLMContext.original for page, fallback to Source
        original = context.original(sid)
        if original is not None:
            source_text = str(original.get("text", ""))
            page = int(original.get("page", 1))
        else:
            # Fallback to sources tuple
            src = next((s for s in context.sources if s.source_id == sid), None)
            if src is None:
                raise KeyError(f"source_id '{sid}' not found in context")
            source_text = src.text
            page = src.page

        # Explanation: top-ranked sentence
        explanation: str
        if rank_sentences is not None:
            try:
                ranked = rank_sentences(result.answer, source_text, top_n=1)
                explanation = ranked[0] if ranked else source_text.strip()
            except Exception:
                explanation = source_text.strip().split(".")[0].strip() or source_text.strip()
        else:
            explanation = source_text.strip()

        # Ensure explanation is non-empty; fallback to source_text
        if not explanation:
            explanation = source_text.strip()

        # Locate rects
        rects: list[BBox] = []
        if pdf_bytes is not None:
            try:
                from bfpc.index.locator import locate_text, locate_words

                # Use explanation as snippet
                rects_raw = locate_words(pdf_bytes, page, explanation)
                if not rects_raw:
                    rects_raw = locate_text(pdf_bytes, page, explanation)
                rects = [list(r) for r in rects_raw] if rects_raw else []
            except Exception:
                rects = []

        items.append(
            TrailItem(
                source_id=sid,
                role=role,
                label=label,
                explanation=explanation,
                page=page,
                rects=rects,
            )
        )

    return ReadingTrail(items=items)
