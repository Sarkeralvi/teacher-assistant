"""Shared tenant-ownership lookups.

Every teacher-scoped resource in this system traces back to
Course.teacher_id. These helpers are the single place that join, so a
resource type gets ownership enforcement once instead of once per router.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    ExtractionRun,
    Question,
    QuestionImportJob,
    QuestionNode,
    Rubric,
    RubricExtractionCriterion,
    Submission,
    User,
)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def get_owned_course_or_404(course_id: int, db: Session, teacher: User) -> Course:
    course = db.scalars(
        select(Course).where(Course.id == course_id, Course.teacher_id == teacher.id)
    ).first()
    if course is None:
        raise _not_found("Course not found")
    return course


def get_owned_assessment_or_404(assessment_id: int, db: Session, teacher: User) -> Assessment:
    assessment = db.scalars(
        select(Assessment)
        .join(Course, Assessment.course_id == Course.id)
        .where(Assessment.id == assessment_id, Course.teacher_id == teacher.id)
    ).first()
    if assessment is None:
        raise _not_found("Assessment not found")
    return assessment


def get_owned_question_or_404(question_id: int, db: Session, teacher: User) -> Question:
    question = db.scalars(
        select(Question)
        .join(Assessment, Assessment.id == Question.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(Question.id == question_id, Course.teacher_id == teacher.id)
    ).first()
    if question is None:
        raise _not_found("Question not found")
    return question


def get_owned_rubric_or_404(rubric_id: int, db: Session, teacher: User) -> Rubric:
    rubric = db.scalars(
        select(Rubric)
        .join(Question, Question.id == Rubric.question_id)
        .join(Assessment, Assessment.id == Question.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(Rubric.id == rubric_id, Course.teacher_id == teacher.id)
    ).first()
    if rubric is None:
        raise _not_found("Rubric not found")
    return rubric


def get_owned_extraction_run_or_404(run_id: int, db: Session, teacher: User) -> ExtractionRun:
    run = db.scalars(
        select(ExtractionRun)
        .join(Assessment, Assessment.id == ExtractionRun.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(ExtractionRun.id == run_id, Course.teacher_id == teacher.id)
    ).first()
    if run is None:
        raise _not_found("Extraction run not found")
    return run


def get_owned_question_node_or_404(node_id: int, db: Session, teacher: User) -> QuestionNode:
    node = db.scalars(
        select(QuestionNode)
        .join(Assessment, Assessment.id == QuestionNode.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(QuestionNode.id == node_id, Course.teacher_id == teacher.id)
    ).first()
    if node is None:
        raise _not_found("Question node not found")
    return node


def get_owned_rubric_criterion_or_404(
    criterion_id: int, db: Session, teacher: User
) -> RubricExtractionCriterion:
    criterion = db.scalars(
        select(RubricExtractionCriterion)
        .join(Assessment, Assessment.id == RubricExtractionCriterion.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(RubricExtractionCriterion.id == criterion_id, Course.teacher_id == teacher.id)
    ).first()
    if criterion is None:
        raise _not_found("Rubric extraction criterion not found")
    return criterion


def get_owned_question_import_job_or_404(
    job_id: int, db: Session, teacher: User
) -> QuestionImportJob:
    job = db.scalars(
        select(QuestionImportJob)
        .join(Assessment, Assessment.id == QuestionImportJob.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(QuestionImportJob.id == job_id, Course.teacher_id == teacher.id)
    ).first()
    if job is None:
        raise _not_found("Question import job not found")
    return job


def get_owned_answer_region_or_404(
    answer_region_id: int, db: Session, teacher: User
) -> AnswerRegion:
    region = db.scalars(
        select(AnswerRegion)
        .join(Submission, Submission.id == AnswerRegion.submission_id)
        .join(Assessment, Assessment.id == Submission.assessment_id)
        .join(Course, Course.id == Assessment.course_id)
        .where(AnswerRegion.id == answer_region_id, Course.teacher_id == teacher.id)
    ).first()
    if region is None:
        raise _not_found("Answer region not found")
    return region
