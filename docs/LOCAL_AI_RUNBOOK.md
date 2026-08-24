# Windows Local AI Runbook

This runbook operates the local model integration for the Custom Controlled workflow. Every model is disabled by default, binds only to loopback, and must be started explicitly. Normal API startup and page loads never load a model.

## Which models exist

| Phase | Model | Port | Role |
|---|---|---|---|
| `Qwen38` | Qwen3.8-27B (vision) | 8085 | Reads escalated pages; maps/transcribes handwriting without thinking; text-grading bake-off candidate |
| `Qwen` | Qwen3.6-35B-A3B (text) | 8086 | Correlates question, solution and rubric text; text-grading bake-off candidate |

Only one fits in this card's VRAM, so selecting a phase unloads the other. Qwen3.6 deliberately does **not** use port 8080: a separate coding-assistant bridge commonly runs there with the same `llama-server.exe`, and sharing the port makes the two contend for one single-slot server.

Tier-1 OCR (RapidOCR, PP-OCRv6 ONNX) runs on the **CPU** in the worker process. It needs no VRAM, so it costs no phase switch and can read while a model is resident.

## Safety contract

- Qwen3.6 receives text only. Answer-image bytes and local image paths are never sent to it.
- Every Qwen3.6/Qwen3.8 inference request has a second fail-closed guard for the matching active database lease. A missing, busy, expired, or wrong-phase lease prevents the request before `/chat/completions` is sent.
- Qwen3.8 visual output is draft evidence until a teacher confirms its exact displayed hash.
- Visual-transcription confirmation copies the unedited model draft into `manual_answer_text`; it does not confirm a complete answer or make evidence grading-ready.
- Question-to-answer mapping remains manual or teacher-confirmed.
- Escalation to the vision model is a **pre-authorized budget**, not a hidden fallback. Exceeding `LOCAL_REFERENCE_MAX_ESCALATIONS` stops the run rather than silently reading fewer pages.
- Cohort grading is sequential, draft-only, stop-on-first-provider-failure, capped at 25 calls, and has zero automatic retries.
- There is no cloud, Codex, mock, or alternate-provider fallback.
- No model action creates a `FinalGrade`; review and approval remain mandatory.
- Docker stays mock-only for this milestone. Run local models and the API on the Windows host.

## One-time local configuration

Do not put machine paths or keys in committed files. Create the ignored `.env.local-ai` with paths for the current machine:

```powershell
.\scripts\local-ai\Initialize-LocalAiConfig.ps1 `
  -QwenBinaryPath '<llama-server.exe>' `
  -QwenModelPath '<qwen3.6-gguf>'
```

The initializer creates separate random API keys and leaves `COHORT_MODEL_GRADING_ENABLED=false`. It refuses to overwrite an existing file.

If Windows blocks repository scripts under the machine execution policy, invoke them with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> ...`. That applies only to the child process.

## Preflight and startup

```powershell
.\scripts\local-ai\Test-LocalAiPreflight.ps1 -Mode Qwen38
.\scripts\local-ai\Start-LocalAi.ps1 -Mode Qwen38
```

Preflight verifies the binary, the GGUF and that the phase's port is free. It does not load a model. Startup verifies the model hash where one is pinned, asserts the listener is loopback-only and owned by the process it started, and reports VRAM headroom. The launcher passes an ignored short-lived API-key file to llama.cpp rather than exposing the key in its command line. `/v1/models` may be publicly discoverable in llama.cpp, but unauthenticated `/v1/chat/completions` must return `401` before a rehearsal begins.

Switch phases with the managed script rather than starting servers by hand:

```powershell
.\scripts\local-ai\Switch-LocalAiPhase.ps1 -Phase Qwen
```

It refuses to adopt a healthy listener this repository did not start, so it cannot silently attach to somebody else's model server.

To stop only the recorded, executable-verified process:

```powershell
.\scripts\local-ai\Stop-LocalAi.ps1 -Mode Qwen38
```

By default this stops only the PID this repository recorded. If another process holds the port it reports which one and refuses. `-ForcePortSweep` overrides that and will kill any matching `llama-server` on the port -- including a coding-assistant bridge. Use it deliberately.

Logs and PID files are under ignored `.local-ai/`. Never commit that directory.

### Measured performance on the reference host (RTX 5070, 12 GB)

| Model | Config | Sustained decode |
|---|---|---|
| Qwen3.6-35B-A3B | `--n-cpu-moe 24`, 32K context | ~67 tok/s |
| Qwen3.8-27B | `-ngl 40`, 12K context | ~4.4 tok/s on a vision call |

Counter-intuitively, moving **more** MoE layers to the CPU is far faster: at `--n-cpu-moe 20` the card sits at 96.6% and the Windows NVIDIA driver spills to system RAM instead of failing, costing ~3.4x. If the machine becomes unstable under load, raise `LOCAL_QWEN_CPU_MOE_LAYERS` to 28 for ~2 GB more headroom at ~12% less throughput.

## Reference extraction

The teacher uploads question, solution and rubric PDFs once, then confirms them before any model runs.

With `LOCAL_OCR_ENABLED=false` (default), every rendered page goes to Qwen3.8 in a single call.

With `LOCAL_OCR_ENABLED=true`, the tiered path runs:

1. Render each page at `LOCAL_OCR_RENDER_DPI` (300 by default).
2. Read every page with CPU tier-1 OCR. No model is loaded.
3. Decide escalation per page from two independent triggers: low recognition confidence, and structural signals that never consult confidence (unusually tall boxes, split fraction boxes, sparse decode, uncovered ink). The second trigger exists because a line recognizer will confidently emit a short plausible string for a display equation.
4. Escalated pages are batched into **one** Qwen3.8 window, then the run switches **once** to Qwen3.6 for correlation. Escalations are skipped entirely when none are needed.
5. The teacher reviews the drafts. Pages read by the vision model are called out in the run warnings -- that is a "look closer" signal, not a claim the draft is wrong.

Every page records its engine, render DPI, image SHA-256, per-line confidence, decision and reason codes in `reference_page_ocr_runs`, so an escalation decision can be audited after the fact.

## Student evidence

1. Upload complete scripts.
2. Prepare draft answer mappings (see **Script mapping** below).
3. Confirm the answer-region mapping.
4. Create a fresh non-thinking verbatim visual transcription and confirm it only when its exact hash faithfully matches the image. Do not edit or mathematically repair it.
5. Confirm separately that the displayed image contains the **full** answer. Text confirmation alone never makes a region grading-ready.
6. If no reading is faithful, reject and upload a clearer complete page rather than accepting the closest match.

### Script mapping

Two paths exist. The UI uses the tiered one; the vision-only path stays selectable as a direct fallback.

| Provider | What runs |
|---|---|
| `llama_cpp_qwen` (default) | Tier-1 OCR locates the answers on the CPU, Qwen3.6 maps them in one text call, Qwen3.8 vision is called only for pages tier-1 could not read. |
| `llama_cpp_qwen38` | Qwen3.8 vision maps every page, one call each. |

### OCR engine bake-off — final result (2026-08-24)

Measured on all 10 teacher-verified fixtures (`data/evaluation/ocr_bakeoff_20260821`), mean CER by material and average latency per page. Two runs: the first four engines together, PaddleOCR-VL-1.6 and Qwen3.8 vision added in a second pass once VRAM allowed both to run.

| Engine | Printed | Typeset math | Handwriting | Overall | Avg latency |
|---|---:|---:|---:|---:|---:|
| **RapidOCR** | 0.000 | 0.215 | **0.628** | 0.482 | **0.6 s** |
| Tesseract | 0.011 | 0.181 | 0.832 | 0.619 | 0.5 s |
| Unlimited-OCR | 0.021 | 0.449 | 1.461 | 1.114 | 20.7 s |
| GOT-OCR2 (CPU) | 0.016 | 0.135 | 0.825 | 0.606 | 9.8 s |
| GOT-OCR2 (GPU) | 0.011 | **0.122** | 0.828 | 0.605 | 3.3 s |
| PaddleOCR-VL-1.6 | 0.084 | 0.585 | 0.939 | 0.783 | 0.4 s |
| Qwen3.8 vision | 0.009 | 0.235 | 0.657 | 0.508 | 87.0 s |

**Decision unchanged and now more decisive: RapidOCR stays the tier-1 engine.** It wins handwriting outright against every candidate measured, including the two added in this pass.

**PaddleOCR-VL-1.6 — genuinely strong content, an unresolved reliability problem.** Hand-tested on the rubric fixture before being wired in, it recovered 6 of 7 exact mark values in one attempt — the best single reading of any engine on that page. But across the full 7-fixture handwriting set it does not reliably know when to stop: greedy decode does not always reach its own `</s>` token on a hard page and runs on into a repeating tail (`"(ii) — (1)"` forever, or counting up integers once `repeat_penalty` forbids the exact repeat). 3 of 10 fixtures hit this in the scored run (`hit_token_budget_without_a_clean_stop`), and a long garbage tail inflates CER heavily via insertions — the same failure shape that put Unlimited-OCR's CER above 1.0. Net: 0.939 mean CER on handwriting, worse than RapidOCR, Tesseract, and GOT-OCR2. Not adopted. If revisited, the open question is a real stopping-condition fix (grammar-constrained decoding, or a stop-string on the model's actual repetition pattern) rather than more `repeat_penalty` tuning, which was tried at 1.1/1.15/1.2/1.3 and never closed the gap without trading it for noisier content.

**Qwen3.8 vision's raw number needs a caveat before it means anything.** Its worst-scoring fixture (CER 1.25, ground truth is 14 characters: `"= 28/67\n\nAns."`) turned out, on direct inspection of the actual output, to be `"n = \frac{28}{67}"` — the content is correct, it is LaTeX-formatted instead of plain-text and drops the "Ans." label. CER punishes that notation difference severely against such a short ground truth. **This is a metric artifact, not evidence that the current escalation model underperforms tier-1** — do not cite the 0.657 handwriting figure as "Qwen3.8 loses to RapidOCR" without this context. A fair comparison would need ground truth in matching notation, or a metric that treats `\frac{a}{b}` and `a/b` as equal. Not attempted here; flagging the confound is as far as this bake-off goes. Its 87 s/page latency is undisputed and unsurprising (4.35 tok/s, previously measured) and is exactly why it is the escalation target, not the default.

**Unlimited-OCR is not viable as any part of this pipeline.** Worst engine measured on every material, by a wide margin, and the only one whose CER exceeds 1.0 — on 4 of 7 handwriting fixtures it hallucinates content beyond the ground truth rather than just misreading it, consistent with its `document parsing.` prompt trying to structure the whole page (early manual testing saw it emit 17 `![](images/N.jpg)` placeholders for a single handwritten page instead of transcribing the ink). It is also by far the slowest (20.7 s/page average, CPU). Ruled out; not revisited unless the underlying model changes.

**GOT-OCR2 is a genuine specialist for typeset math**, beating both RapidOCR (0.215) and Tesseract (0.181) at 0.122–0.135 CER — plausible, since it is a structured-output OCR model rather than a line recognizer, so a correctly-read fraction survives as `\frac{...}{...}` instead of flattening into digits the way RapidOCR's failure mode is documented above. It does not beat RapidOCR on handwriting and is far slower per page even on GPU, so **it is not a tier-1 replacement**, but it is a candidate worth a future look as a targeted alternative to vision escalation specifically for typeset-math reference pages, which today escalate straight to Qwen3.8. That is a new, narrower proposal, not implemented.

**Formula mode is unsafe to apply blanket-wide.** `--task formula`/`format=True` is trained for genuine formula content; applied to ordinary handwritten prose it does not just score worse, it degenerates into repeating unrelated CJK glyphs. Confirmed independent of any hardware issue: isolated GPU numerics (bf16 matmul/attention) showed no NaN/Inf, and the same model produces its documented correct output on its own official reference test image. The `got_ocr2` arm therefore always runs in plain mode; a formula-mode arm would need its own per-fixture routing to be safe, which this harness does not currently do.

**CPU vs GPU, for GOT-OCR2 specifically:** GPU is ~3× faster (3.3 s vs 10.3 s/page) at statistically indistinguishable accuracy (0.605 vs 0.600 overall). This does not change the tier-1 decision, but it is the number to use if GOT-OCR2 is ever adopted for the typeset-math-escalation idea above — reuse `packages/evaluation/ocr_engine_bakeoff.py::_got_ocr2_gpu_adapter` rather than the CPU CLI arm.

Bake-off arms live in `packages/evaluation/ocr_engine_bakeoff.py`; run with `python -m packages.evaluation.ocr_engine_bakeoff --fixtures data/evaluation/ocr_bakeoff_20260821 --engines rapidocr,tesseract,unlimited_ocr,got_ocr2,got_ocr2_gpu --out <path>`. The GPU arms need `torch` (CUDA build), `transformers==4.57.1` pinned exactly (Baidu's Unlimited-OCR custom code targets that version and breaks on newer releases), `accelerate`, `torchvision`, and for Unlimited-OCR specifically `einops`, `addict`, `easydict`, `timm` — none of these are runtime dependencies of the application itself, only of this one-time measurement script; nothing in `apps/api` imports `torch` or `transformers`.

The tiered path runs in stages, deliberately batched — interleaving would cost a 60-90 s model reload per page:

1. Tier-1 OCR every page. No model resident, no VRAM, `LOCAL_OCR_ENABLED` must be true.
2. Escalate only pages whose **detection** failed: no boxes at all, or ink outside every box (`LOCAL_OCR_UNCOVERED_INK_ESCALATE_ABOVE`). Recognition quality is deliberately *not* a trigger here — see below.
3. Escalated pages go to Qwen3.8 `map_page_answer_regions`, bounded by `LOCAL_SCRIPT_MAX_ESCALATIONS` and the request's `maximum_visual_calls`. Exceeding either is a hard stop, never a quiet degrade.
4. The remaining pages go to Qwen3.6 in **one** text call. It selects OCR block identifiers and never produces coordinates.
5. The two mappers own disjoint pages, so segments concatenate in page order. A question the vision pass already placed is not re-placed by the text pass.
6. Any finalized question with no region becomes a visible blocker, and pages carrying unassigned ink are named on it.

**Why recognition quality is not an escalation trigger on scripts.** Tier-1 OCR supplies *geometry* here, not text: its boxes locate the answer and Qwen3.8 reads it later, per confirmed region. Since 94.7% of handwritten lines are misread, escalating on recognition quality would send every page to the vision model and the tiered path would save nothing. A page whose ink was found is usable even when badly read. This is `evaluate_page_detection_only` in `packages/ocr/escalation.py`, kept separate from the reference-phase policy, which does care about text and escalates handwriting wholesale.

The approximate OCR text is never presented as the answer. Mappings carry `text_source = "tier1_ocr_mapping_pending_transcription"`, and the verbatim reading remains a separate teacher confirmation on the vision path.

## Known limitations

- Tier-1 OCR drops decimal points on some handwriting (`03` for `0.3`). In a probability question that is a 10x error in the value a mark depends on, so handwriting escalates often and teacher review remains mandatory.
- RapidOCR escalation thresholds are calibrated only on the current small fixture set and remain unsuitable as a classroom-wide handwriting-quality claim. Handwriting is deliberately sent to Qwen3.8 visual review instead.
- The 20-case curated evaluation gate is wired to the production Qwen3.8 visual-transcription job and text-only dispatch path, but no completed signed real run exists yet. No result may be cited as pilot-authorization evidence until it completes with `PASS`.
- The Qwen3.6-versus-Qwen3.8 text-grading bake-off is implemented but has no live candidate result yet. Its evidence replay makes zero new visual calls and its result does not automatically change the normal grading configuration. Grading still dispatches to Qwen3.8 until that bake-off produces a result.
- The tiered script path has never been run end to end against a real script. Its stages are covered by tests with fake engines and providers, which is not evidence about a real page.
- **Resolved 2026-08-24:** Baidu Unlimited-OCR and GOT-OCR2.0 were measured against RapidOCR and Tesseract on all 10 teacher-verified fixtures. **RapidOCR remains the tier-1 engine.** See "OCR engine bake-off — final result" below.
