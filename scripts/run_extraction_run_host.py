#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import ExtractionRun  # noqa: E402
from app.services.document_extraction import (  # noqa: E402
    DocumentExtractionError,
    apply_extraction_result,
    mark_extraction_run_failed,
    resolve_host_artifact_path,
)
from app.services.document_extraction import validate_normalized_output  # noqa: E402
from app.services.document_extraction import ExtractionProviderResult  # noqa: E402


# Reuse the host-side codex bridge directly.
from codex_extract_document import build_prompt, load_source_text, run_codex  # noqa: E402


def run_host_extraction(run_id: int, model: str) -> int:
    db = SessionLocal()
    try:
        run = db.get(ExtractionRun, run_id)
        if run is None:
            print(f"ExtractionRun {run_id} not found", file=sys.stderr)
            return 2
        host_file = resolve_host_artifact_path(run.artifact_file_path, settings=get_settings())
        source_text = load_source_text(host_file, run.content_type)
        prompt = build_prompt(run.extraction_type, host_file, run.content_type, source_text)
        output_path = REPO_ROOT / ".tmp" / f"extraction_run_{run_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if host_file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} or (
            run.content_type == "application/pdf" and not source_text.strip()
        ):
            raw_output = run_codex(model, prompt, output_path, REPO_ROOT, image_paths=[host_file])
        else:
            raw_output = run_codex(model, prompt, output_path, REPO_ROOT)
        normalized_output = validate_normalized_output(run.extraction_type, json.loads(raw_output))
        result = ExtractionProviderResult(
            raw_output=raw_output,
            normalized_output=normalized_output,
            blockers=normalized_output.get("blockers", []),
        )
        run.provider = "host_bridge_codex"
        apply_extraction_result(db, run, result)
        db.commit()
        print(f"ExtractionRun {run_id} succeeded")
        return 0
    except Exception as exc:
        run = db.get(ExtractionRun, run_id)
        if run is not None:
            message = str(exc)
            if isinstance(exc, DocumentExtractionError):
                mark_extraction_run_failed(run, message)
            else:
                mark_extraction_run_failed(run, message)
            db.commit()
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()
    return run_host_extraction(args.run_id, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
