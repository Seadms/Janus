
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth import get_current_username
from backend.permissions import require_device_role, set_device_role

router = APIRouter(prefix="/api", tags=["Device Permissions"])


class RoleAssignment(BaseModel):
    username: str = Field(min_length=1)
    role: str


@router.put("/devices/{device_id}/permissions")
def assign_device_role(
    device_id: str,
    assignment: RoleAssignment,
    current_username: str = Depends(get_current_username),
):
    require_device_role(current_username, device_id, "admin")

    return set_device_role(
        device_id,
        assignment.username,
        assignment.role,
    )
