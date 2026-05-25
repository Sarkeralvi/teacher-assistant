from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas import UserCreate, UserRead

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/users", tags=["users"])

_PLACEHOLDER_PASSWORD_HASH = "placeholder:not-authenticated"
_ALLOWED_ROLES = {"teacher", "admin"}


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession) -> User:
    if payload.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid role")

    user = User(
        name=payload.name,
        email=str(payload.email),
        role=payload.role,
        password_hash=_PLACEHOLDER_PASSWORD_HASH,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        ) from exc
    db.refresh(user)
    return user


@router.get("", response_model=list[UserRead])
def list_users(db: DbSession) -> Sequence[User]:
    return db.scalars(select(User).order_by(User.id)).all()


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: DbSession) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
