"""Generate the E2E test corpus: two topic-distinct PDFs (cookbook, deploy).

report.pdf is copied from tests/fixtures/ as the third corpus member. The
documents are deliberately topically disjoint so cross-document retrieval
contamination is detectable (a query about Python must not return
deployment-guide chunks, and vice versa).

Usage (system python has pymupdf):
    python ui/e2e/fixtures/generate_corpus.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

FONT_SIZE = 13
LINE_HEIGHT = 22
MARGIN = 56
WIDTH, HEIGHT = 595, 842  # A4 portrait, points


def _page(doc: pymupdf.Document, title: str, lines: list[str]) -> None:
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    page.insert_text((MARGIN, 60), title, fontsize=20)
    y = 110
    for line in lines:
        page.insert_text((MARGIN, y), line, fontsize=FONT_SIZE)
        y += LINE_HEIGHT


def cookbook() -> bytes:
    doc = pymupdf.open()
    _page(
        doc,
        "Python Cookbook",
        [
            "This cookbook collects small recipes for everyday Python work.",
            "Start by creating a virtualenv: python -m venv .venv",
            "Activate it and install dependencies with pip install -e .",
            "Pin exact versions in requirements.txt to keep builds reproducible.",
            "Use pyproject.toml for modern projects instead of setup.py.",
        ],
    )
    _page(
        doc,
        "Web Recipes",
        [
            "Flask is a good fit for small internal services.",
            "Expose routes with @app.route and return JSON with jsonify.",
            "The requests library handles HTTP clients; always set a timeout.",
            "Use a session object to reuse connection pools across calls.",
        ],
    )
    _page(
        doc,
        "Testing Recipes",
        [
            "Write unit tests with pytest and keep them deterministic.",
            "Mock slow boundaries like network calls with pytest-mock.",
            "A test should fail for exactly one reason; keep it focused.",
            "Run the suite locally before opening a pull request.",
        ],
    )
    buf = doc.tobytes()
    doc.close()
    return buf


def deploy() -> bytes:
    doc = pymupdf.open()
    _page(
        doc,
        "Deployment Guide",
        [
            "This guide describes shipping services to the cluster.",
            "Build images with docker and tag them with the commit sha.",
            "Push images to the private registry before deploying.",
            "Never run containers as root; drop privileges in the image.",
        ],
    )
    _page(
        doc,
        "Rollouts",
        [
            "Package applications as Helm charts with values per environment.",
            "Perform a canary rollout by shifting five percent of traffic.",
            "Roll back immediately when error rates cross the threshold.",
            "Monitor rollouts with kubectl rollout status.",
        ],
    )
    _page(
        doc,
        "Pipelines",
        [
            "A CI pipeline runs tests, builds images, and deploys to staging.",
            "Use the pipeline to gate production releases on green tests.",
            "Secrets live in the vault, never in the repository.",
            "On failure the pipeline reports the failing stage and logs.",
        ],
    )
    buf = doc.tobytes()
    doc.close()
    return buf


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    report_src = ROOT / "tests" / "fixtures" / "report.pdf"
    if not report_src.is_file():
        raise SystemExit(f"missing source PDF: {report_src}")
    shutil.copyfile(report_src, OUT / "report.pdf")

    (OUT / "cookbook.pdf").write_bytes(cookbook())
    (OUT / "deploy.pdf").write_bytes(deploy())

    for name in ("report.pdf", "cookbook.pdf", "deploy.pdf"):
        doc = pymupdf.open(OUT / name)
        print(f"{name}: {doc.page_count} pages")
        doc.close()


if __name__ == "__main__":
    main()
