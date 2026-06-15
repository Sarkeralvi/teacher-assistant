#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz

API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")


def sanitize(text: str) -> str:
    return API_KEY_PATTERN.sub("[REDACTED]", text)


def load_source_text(path: Path, content_type: str) -> str:
    if content_type == "text/plain" or path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if content_type == "application/pdf" or path.suffix.lower() == ".pdf":
        chunks: list[str] = []
        with fitz.open(path) as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                text = str(page.get_text("text")).strip()
                if text:
                    chunks.append(f"[PAGE {page_index + 1}]\n{text}")
        return "\n\n".join(chunks)
    return ""


def build_prompt(extraction_type: str, file_path: Path, content_type: str, source_text: str) -> str:
    if extraction_type == "question_paper":
        schema = """{
  \"question_nodes\": [
    {
      \"question_number\": \"Q1\",
      \"parent_question_number\": null,
      \"label\": \"Q1\",
      \"text\": \"Answer the following.\",
      \"marks\": 10,
      \"node_type\": \"question\",
      \"source_page\": 1,
      \"source_reference\": {\"source_text_excerpt\": \"Q1. Answer the following. [10 marks]\"},
      \"confidence\": 0.9,
      \"teacher_confirmed\": false
    }
  ],
  \"blockers\": []
}"""
        instructions = (
            "Extract the full question structure: question numbers, subquestions, instructions, and marks. "
            "Keep teacher_confirmed=false. If unsure, return a blocker instead of inventing content."
        )
    else:
        schema = """{
  \"criteria\": [
    {
      \"question_number\": \"Q1(a)\",
      \"criterion_label\": \"Correct answer\",
      \"description\": \"Correct answer\",
      \"max_marks\": 4,
      \"confidence\": 0.9,
      \"blocker\": null,
      \"teacher_confirmed\": false
    }
  ],
  \"blockers\": []
}"""
        instructions = (
            "Extract rubric criteria, marks, and clear question linkage when visible. "
            "If linkage is uncertain, keep question_number null and add a blocker. Keep teacher_confirmed=false."
        )
    return f"""Return ONLY valid JSON. No markdown. No prose outside JSON.
Do not run commands. Do not modify files.
This is an experimental Teacher Assistant extraction run using synthetic-safe data only.
Uploaded file path: {file_path}
Uploaded content type: {content_type}
{instructions}

If the file is not directly readable, rely on the extracted text below when present.
If the content is unreadable, return an empty object is forbidden; instead return the schema with blockers.

Source text excerpt:
{source_text if source_text.strip() else '[NO_TEXT_LAYER_AVAILABLE]'}

Required JSON schema:
{schema}
"""


def run_codex(model: str, prompt: str, output_file: Path, repo_root: Path) -> str:
    codex_path = shutil.which("codex") or "/usr/local/bin/codex"
    command = [
        codex_path,
        "exec",
        "--cd",
        str(repo_root),
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_file),
        "--json",
        "--model",
        model,
    ]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )
    if completed.returncode != 0:
        detail = sanitize((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(f"codex exec failed with status {completed.returncode}: {detail}")
    if not output_file.is_file():
        raise RuntimeError("codex exec did not produce --output-last-message output")
    return output_file.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--content-type", required=True)
    parser.add_argument("--extraction-type", choices=["question_paper", "rubric"], required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    input_path = Path(args.input_file).resolve()
    output_path = Path(args.output_file).resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if not input_path.is_file():
        print("input file not found", file=sys.stderr)
        return 2

    source_text = load_source_text(input_path, args.content_type)
    prompt = build_prompt(args.extraction_type, input_path, args.content_type, source_text)
    try:
        with tempfile.TemporaryDirectory(prefix="ta-codex-bridge-"):
            raw_output = run_codex(args.model, prompt, output_path, repo_root)
        payload = json.loads(raw_output)
    except Exception as exc:
        print(sanitize(str(exc)), file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("codex output must be a JSON object", file=sys.stderr)
        return 1
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
