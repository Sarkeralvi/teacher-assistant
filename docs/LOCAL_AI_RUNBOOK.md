# Windows Local AI Runbook

This runbook is the canonical operator guide for the supervised Custom Controlled workflow. Local AI is disabled by default, binds only to loopback, and starts only after an explicit teacher/operator action. Application startup and page loads never load a model.

## Active hybrid architecture

| Phase | Service | Port | Normal role |
|---|---|---:|---|
| `PaddleOcr` | PaddleOCR-VL-1.6 + PP-DocLayoutV3 | 8090 | Page OCR, block geometry, and direct draft transcription |
| `Qwen` | Qwen3.6-35B-A3B via llama.cpp | 8086 | Reference correlation, block-to-question mapping, and text-only draft grading |
| `Qwen38` | Qwen3.8-27B vision via llama.cpp | 8085 | Explicit non-thinking transcription rescue only |

The RTX 5070 has one model slot. A durable database lease plus a process-local call guard is mandatory for every Paddle/Qwen request. Switching phases unloads the other two services before loading the requested one. Missing, expired, busy, or wrong-phase leases fail before inference HTTP is sent.

Normal workflows are deliberately ordered:

1. PaddleOCR reads all source pages or script pages.
2. PaddleOCR is stopped.
3. Qwen3.6 correlates or maps the OCR output.
4. A teacher confirms region geometry and exact evidence separately.
5. Qwen3.8 may run only after the teacher rejects a Paddle transcript and explicitly requests rescue.
6. Qwen3.6 grades only teacher-confirmed text; it receives no student image.

There is no cloud, Codex, mock, provider fallback, automatic retry, or automatic final-grade path in this workflow. Cohort grading remains disabled for the supervised rehearsal.

## Local assets and configuration

Machine paths and keys belong only in ignored `.env.local-ai`. Never commit model files, keys, uploads, or evaluation artifacts.

Create the file once from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\local-ai\Initialize-LocalAiConfig.ps1 `
  -QwenBinaryPath '<llama-server.exe>' `
  -QwenModelPath '<Qwen3.6 GGUF>' `
  -Qwen38BinaryPath '<llama-server.exe>' `
  -Qwen38ModelPath '<Qwen3.8 GGUF>' `
  -PaddlePythonPath '<paddle venv python.exe>' `
  -PaddleVlModelPath '<native PaddleOCR-VL-1.6 directory>' `
  -PaddleLayoutModelPath '<native PP-DocLayoutV3 directory>'
```

The native PaddleOCR-VL directory must contain `model.safetensors`; the native layout directory must contain `inference.pdiparams`. A llama.cpp GGUF named PaddleOCR-VL is not interchangeable with these PaddleX assets.

The initializer creates three different random API keys and enables the supervised hybrid flags. It keeps these false:

- `LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED`
- `LOCAL_QWEN38_GRADING_ENABLED`
- `COHORT_MODEL_GRADING_ENABLED`

## Preflight and phase operation

Preflight does not load a model:

```powershell
.\scripts\local-ai\Test-LocalAiPreflight.ps1 -Mode PaddleOcr
.\scripts\local-ai\Test-LocalAiPreflight.ps1 -Mode Qwen
.\scripts\local-ai\Test-LocalAiPreflight.ps1 -Mode Qwen38
```

Start or switch one phase explicitly:

```powershell
.\scripts\local-ai\Start-LocalAi.ps1 -Mode PaddleOcr
.\scripts\local-ai\Switch-LocalAiPhase.ps1 -Phase Qwen
.\scripts\local-ai\Switch-LocalAiPhase.ps1 -Phase Qwen38
```

Stop only a repository-managed process:

```powershell
.\scripts\local-ai\Stop-LocalAi.ps1 -Mode PaddleOcr
```

The scripts verify loopback binding, PID/executable ownership, authenticated health, exact model aliases, offline Paddle mode, concurrency one, and safe port ownership. Do not use `-ForcePortSweep` unless intentionally recovering a known stale listener; it can stop another llama.cpp process.

Qwen3.6 uses `LOCAL_QWEN_CPU_MOE_LAYERS=28` by default for safer VRAM headroom. Qwen3.8 uses 34 GPU layers for the same reason. Performance is secondary to stable sequential operation during a teacher rehearsal.

For an explicitly authorized engineering smoke, use the bounded launcher below. It makes one synthetic Paddle call, one synthetic text-only Qwen3.6 draft-grading call, and—only when the final switch is supplied—one synthetic Qwen3.8 rescue call. It uses production leases/phase switching, creates no assessment or grade row, and stops all three services in a `finally` block.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\local-ai\Test-RescuedHybridSmoke.ps1 `
  -AllowLocalPaddle -AllowLocalQwen36 -AllowLocalQwen38Rescue
```

## Teacher workflow

### References

The teacher uploads the question, solution/model answer, and rubric once and authorizes draft-only extraction. PaddleOCR processes rendered pages in page order. Qwen3.6 receives only normalized OCR text and immutable page/block references, then drafts questions, answers, marks, and rubric criteria. The teacher must review and confirm these drafts before they become canonical.

No Qwen3.8 call is part of normal reference extraction. The run stops on Paddle or Qwen failure; it does not retry or fall back.

### Script mapping and evidence

1. Upload a complete script; the teacher does not crop or enter coordinates.
2. PaddleOCR locates ordered blocks on each page.
3. Qwen3.6 selects block identifiers for each finalized question. Coordinates remain Paddle-derived.
4. The teacher confirms each mapped image region and continuation.
5. PaddleOCR creates one direct transcript from the confirmed region segments.
6. If faithful, the teacher confirms its exact SHA-256. This copies the unedited draft into `manual_answer_text` with partial evidence status.
7. If unfaithful, the teacher rejects it with a reason and explicitly requests Qwen3.8 rescue. Qwen3.8 runs non-thinking forensic transcription only; it may not calculate, correct, reconcile, map, or grade.
8. The teacher separately confirms that displayed images contain the complete answer. Text confirmation alone never makes evidence grading-ready.

If neither transcript is faithful, grading stays blocked and the teacher uploads a clearer complete page. There is no manual-crop or replacement-transcription box.

### Grading

Qwen3.6 receives only the canonical question, canonical model answer, pinned active rubric, marking policy, and teacher-confirmed transcript. Every output is a pending suggestion with `teacher_review_required`, `image_input_disabled`, and `local_provider`. A `FinalGrade` can exist only after explicit teacher review/approval. Approved-only export excludes pending/rejected suggestions.

## Hard-stop conditions

Stop and record the diagnostic reference if any of these occurs:

- service/model mismatch, non-loopback listener, or unknown PID ownership;
- model phase changes while another holder owns the lease;
- retry, fallback, cloud call, or hidden provider call;
- incomplete mapping, unresolved continuation, or unassigned answer ink;
- non-faithful transcript or hallucinated blank content;
- changed image/evidence/rubric/reference hash after confirmation;
- any grade created from unconfirmed text or any automatic `FinalGrade`.

## Pilot status

Engineering checks and synthetic smokes establish that the system runs; they do not establish grading quality. A teacher pilot still requires a signed curated-evaluation `PASS`, signed model-selection result, and one signed end-to-end supervised rehearsal. Keep cohort grading disabled until all three exist.
