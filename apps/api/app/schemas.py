from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    role: str = "teacher"


class UserRead(ORMBase):
    id: int
    name: str
    email: str = Field(min_length=3, max_length=320)
    role: str
    created_at: datetime
    updated_at: datetime


class CourseCreate(BaseModel):
    teacher_id: int
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    semester: str | None = Field(default=None, max_length=64)


class CourseUpdate(BaseModel):
    teacher_id: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    semester: str | None = Field(default=None, max_length=64)


class CourseRead(ORMBase):
    id: int
    teacher_id: int
    code: str
    title: str
    department: str | None
    semester: str | None
    created_at: datetime
    updated_at: datetime


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    assessment_type: str = Field(min_length=1, max_length=64)
    total_marks: Decimal = Field(gt=Decimal("0"))
    status: str = "draft"


class AssessmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    assessment_type: str | None = Field(default=None, min_length=1, max_length=64)
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))
    status: str | None = None


class AssessmentRead(ORMBase):
    id: int
    course_id: int
    title: str
    assessment_type: str
    total_marks: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class QuestionCreate(BaseModel):
    question_no: str = Field(min_length=1, max_length=32)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    total_marks: Decimal = Field(gt=Decimal("0"))


class QuestionUpdate(BaseModel):
    question_no: str | None = Field(default=None, min_length=1, max_length=32)
    question_text: str | None = Field(default=None, min_length=1)
    model_answer: str | None = None
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))


class QuestionRead(ORMBase):
    id: int
    assessment_id: int
    question_no: str
    question_text: str
    model_answer: str | None
    total_marks: Decimal
    created_at: datetime
    updated_at: datetime


class RubricCreate(BaseModel):
    version: int = Field(ge=1)
    rubric_json: dict[str, Any]
    is_active: bool = True


class RubricUpdate(BaseModel):
    version: int | None = Field(default=None, ge=1)
    rubric_json: dict[str, Any] | None = None
    is_active: bool | None = None


class RubricRead(ORMBase):
    id: int
    question_id: int
    version: int
    rubric_json: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime
