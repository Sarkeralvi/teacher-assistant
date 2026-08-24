"""Run GOT-OCR2.0 on one image via transformers on GPU and print the result.

Standalone, reusable version of the logic validated during the OCR bake-off
(2026-08-24): plain mode by default, since --format/formula mode is
out-of-distribution for ordinary handwritten prose and was shown to degenerate
into repeating unrelated glyphs -- see docs/LOCAL_AI_RUNBOOK.md, "OCR engine
bake-off - final result". Pass --formula only for genuine math/formula images.

Not part of the application; used only by Test-GotOcr2.ps1 for direct manual
verification of this OCR bake-off candidate. Needs torch (CUDA build),
transformers, torchvision -- already installed in this project's venv for the
bake-off; not runtime dependencies of the app itself.
"""

from __future__ import annotations

import argparse
import sys
import time

MODEL_ID = "stepfun-ai/GOT-OCR-2.0-hf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_path")
    parser.add_argument(
        "--formula",
        action="store_true",
        help="Use structured LaTeX/formula mode instead of plain text. Only for "
        "genuine math/formula images -- degrades on ordinary handwriting.",
    )
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    print(f"loading {MODEL_ID} on GPU...", file=sys.stderr)
    start = time.time()
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_ID, device_map="cuda", dtype=torch.bfloat16
    )
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    print(f"loaded in {time.time() - start:.1f}s", file=sys.stderr)

    inputs = processor(args.image_path, return_tensors="pt", format=args.formula).to(
        model.device
    )
    start = time.time()
    generate_ids = model.generate(
        **inputs,
        do_sample=False,
        tokenizer=processor.tokenizer,
        stop_strings="<|im_end|>",
        max_new_tokens=4096,
        no_repeat_ngram_size=20,
    )
    elapsed = time.time() - start
    text = processor.decode(
        generate_ids[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True
    )
    print(f"inference took {elapsed:.1f}s", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
