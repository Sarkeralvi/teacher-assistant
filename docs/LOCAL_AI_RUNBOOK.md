# Windows Local AI Runbook

This runbook operates the local model integration for the Custom Controlled workflow. Every model is disabled by default, binds only to loopback, and must be started explicitly. Normal API startup and page loads never load a model.

## Which models exist

| Phase | Model | Port | Role |
|---|---|---|---|
| `Qwen38` | Qwen3.8-27B (vision) | 8085 | Reads pages OCR could not read confidently; transcribes handwriting; grades |
| `Qwen` | Qwen3.6-35B-A3B (text) | 8086 | Correlates question, solution and rubric text into draft references |

Only one fits in this card's VRAM, so selecting a phase unloads the other. Qwen3.6 deliberately does **not** use port 8080: a separate coding-assistant bridge commonly runs there with the same `llama-server.exe`, and sharing the port makes the two contend for one single-slot server.

Tier-1 OCR (RapidOCR, PP-OCRv6 ONNX) runs on the **CPU** in the worker process. It needs no VRAM, so it costs no phase switch and can read while a model is resident.

## Safety contract

- Qwen3.6 receives text only. Answer-image bytes and local image paths are never sent to it.
- OCR output is draft evidence until a teacher confirms it.
- OCR confirmation updates `manual_answer_text`; it does not confirm a complete answer or make evidence grading-ready.
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

Preflight verifies the binary, the GGUF and that the phase's port is free. It does not load a model. Startup verifies the model hash where one is pinned, asserts the listener is loopback-only and owned by the process it started, and reports VRAM headroom.

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
2. Confirm the answer-region mapping.
3. Create a verbatim visual transcription and confirm it only when it faithfully matches the image.
4. Confirm separately that the displayed image contains the **full** answer. Text confirmation alone never makes a region grading-ready.
5. If no reading is faithful, reject and upload a clearer complete page rather than accepting the closest match.

## Known limitations

- Tier-1 OCR drops decimal points on some handwriting (`03` for `0.3`). In a probability question that is a 10x error in the value a mark depends on, so handwriting escalates often and teacher review remains mandatory.
- Escalation thresholds are **provisional** until the bake-off in `packages/evaluation/ocr_engine_bakeoff.py` is run against teacher-verified fixtures.
- The 20-case curated evaluation gate cannot currently run: its OCR stage is not wired to the replacement pipeline. No result from that gate may be cited as pilot-authorization evidence until it is.
