from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.config import Settings, get_settings
from app.models import User
from app.schemas import BrainProfileRead, LocalAiStatusRead
from app.services.local_ai_status_service import LocalAiStatusService

CurrentUser = Annotated[User, Depends(get_current_user)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]

router = APIRouter(tags=["local-ai"])


@router.get("/brain/status", response_model=LocalAiStatusRead)
@router.get("/local-ai/status", response_model=LocalAiStatusRead)
def read_local_ai_status(current_user: CurrentUser) -> dict[str, object]:
    del current_user
    return LocalAiStatusService().read()


@router.get("/brain/profiles", response_model=list[BrainProfileRead])
def read_brain_profiles(
    current_user: CurrentUser,
    settings: SettingsDependency,
) -> list[dict[str, object]]:
    del current_user
    return LocalAiStatusService(settings).profiles()
