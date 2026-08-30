from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.answer_regions import router as answer_regions_router
from app.api.routes.assessments import router as assessments_router
from app.api.routes.auth import router as auth_router
from app.api.routes.bulk_evaluations import router as bulk_evaluations_router
from app.api.routes.courses import router as courses_router
from app.api.routes.evidence_prep import router as evidence_prep_router
from app.api.routes.extraction_runs import router as extraction_runs_router
from app.api.routes.final_grades import router as final_grades_router
from app.api.routes.grading import router as grading_router
from app.api.routes.grading_queue import router as grading_queue_router
from app.api.routes.grading_runs import router as grading_runs_router
from app.api.routes.health import router as health_router
from app.api.routes.local_ai import router as local_ai_router
from app.api.routes.ocr import router as ocr_router
from app.api.routes.question_imports import router as question_imports_router
from app.api.routes.questions import router as questions_router
from app.api.routes.rubrics import router as rubrics_router
from app.api.routes.submissions import router as submissions_router
from app.api.routes.users import router as users_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)

if settings.cors_allowed_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(local_ai_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(courses_router)
app.include_router(assessments_router)
app.include_router(questions_router)
app.include_router(question_imports_router)
app.include_router(extraction_runs_router)
app.include_router(rubrics_router)
app.include_router(submissions_router)
app.include_router(answer_regions_router)
app.include_router(bulk_evaluations_router)
app.include_router(ocr_router)
app.include_router(evidence_prep_router)
app.include_router(grading_router)
app.include_router(grading_queue_router)
app.include_router(grading_runs_router)
app.include_router(final_grades_router)
