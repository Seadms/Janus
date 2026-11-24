
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_username
from backend.permissions import (
    require_device_role,
    set_device_role,
    revoke_device_role,
)

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


@router.delete("/devices/{device_id}/permissions/{username}")
def revoke_device_access(
    device_id: str,
    username: str,
    current_username: str = Depends(get_current_username),
):
    require_device_role(current_username, device_id, "admin")

    removed = revoke_device_role(device_id, username)

    if not removed:
        raise HTTPException(
            status_code=404,
            detail="Device permission not found",
        )

    return {
        "deleted": True,
        "device_id": device_id,
        "username": username,
    }
