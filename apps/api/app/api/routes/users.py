from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas import UserRead

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(db: DbSession, current_user: CurrentUser) -> Sequence[User]:
    del db
    # A teacher directory would disclose other teachers' names and email
    # addresses across tenants.  The product has no separately authorized
    # administrative directory, so the authenticated caller can only read
    # their own account through this legacy collection endpoint.
    return [current_user]


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: DbSession, current_user: CurrentUser) -> User:
    del db
    if user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return current_user
