# Windows Local AI Runbook

This runbook is the canonical operator guide for the supervised Custom Controlled workflow. Local AI is disabled by default, binds only to loopback, and starts only after an explicit teacher/operator action. Application startup and page loads never load a model.

## Active Qwen3.8 standalone architecture

| Phase | Service | Port | Normal role |
|---|---|---:|---|
| `Qwen38` | Qwen3.8-27B vision via llama.cpp | 8085 | Reference drafts, answer-region mapping, final-intent transcription, and text-only draft grading |

The RTX 5070 has one model slot. A durable database lease plus a process-local call guard is mandatory for every Qwen3.8 request. Missing, expired, busy, or wrong-phase leases fail before inference HTTP is sent. PaddleOCR and Qwen3.6 remain installed only as rollback assets and are disabled in `.env.local-ai`.

Normal workflows are deliberately ordered:

1. Qwen3.8 vision drafts references from the three teacher-uploaded files with thinking disabled.
2. A fresh Qwen3.8 vision task maps complete answer regions from full script pages.
3. A teacher confirms region geometry and every continuation segment.
4. A fresh thinking-disabled Qwen3.8 task first classifies cancellation/replacement marks, then transcribes only the student's surviving final work.
5. The teacher confirms transcript fidelity and full-answer coverage separately.
6. A fresh text-only Qwen3.8 task grades only the teacher-confirmed transcript.

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

The older rescued-hybrid smoke remains only for rollback diagnostics. It is not part of the active teacher workflow and must not be used as pilot evidence while PaddleOCR and Qwen3.6 are disabled.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\local-ai\Test-RescuedHybridSmoke.ps1 `
  -AllowLocalPaddle -AllowLocalQwen36 -AllowLocalQwen38Rescue
```

## Teacher workflow

### References

The teacher uploads the question, solution/model answer, and rubric once and authorizes one draft-only Qwen3.8 visual extraction. The task runs with thinking disabled and drafts questions, answers, marks, and rubric criteria. The teacher must review and confirm these drafts before they become canonical. Failure stops the run; there is no retry or fallback.

### Script mapping and evidence

1. Upload a complete script; the teacher does not crop or enter coordinates.
2. Qwen3.8 maps ordered regions and continuation segments from full pages.
3. The teacher confirms each mapped image region and continuation.
4. A fresh Qwen3.8 task performs structured editing interpretation and final-intent transcription from all confirmed segments in one authorized provider call.
5. If faithful, the teacher confirms its exact SHA-256. This copies the unedited draft into `manual_answer_text` with partial evidence status.
6. If unfaithful, the teacher rejects it and uploads a clearer complete page; no inferred correction is substituted.
7. The teacher separately confirms that displayed images contain the complete answer. Text confirmation alone never makes evidence grading-ready.

Cancelled writing is excluded even when readable. A visible replacement is retained. An
ambiguous overwrite must remain `[unclear correction]`; the model must never select a symbol
from arithmetic consistency or the expected answer. Minus signs, fraction/root bars, the
variable `x`, ordinary underlining, and diagram lines are not cancellation by themselves.

If neither transcript is faithful, grading stays blocked and the teacher uploads a clearer complete page. There is no manual-crop or replacement-transcription box.

### Grading

Qwen3.8 receives only the canonical question, canonical model answer, pinned active rubric, marking policy, and teacher-confirmed transcript in a fresh text-only context. Every output is a pending suggestion with `teacher_review_required`, `image_input_disabled`, and `local_provider`. A `FinalGrade` can exist only after explicit teacher review/approval. Approved-only export excludes pending/rejected suggestions.

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
