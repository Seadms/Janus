
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from backend.alerts.history import list_user_alerts
from backend.auth import get_current_username
from backend.permissions import require_device_role
from backend.alerts.rules import (
    create_alert_rule,
    list_alert_rules,
    get_alert_rule,
    update_alert_rule,
    delete_alert_rule,
)

router = APIRouter(prefix="/api", tags=["Alert Rules"])


class AlertRuleCreate(BaseModel):
    metric: str = Field(min_length=1)
    operator: Literal[">", ">=", "<", "<="]
    threshold: float


class AlertRuleUpdate(AlertRuleCreate):
    enabled: bool = True


@router.post("/devices/{device_id}/alerts", status_code=201)
def create_rule(
    device_id: str,
    data: AlertRuleCreate,
    username: str = Depends(get_current_username),
):
    require_device_role(username, device_id, "admin")
    rule_id = create_alert_rule(
        device_id, data.metric, data.operator,
        data.threshold, username
    )
    return get_alert_rule(rule_id)


@router.get("/devices/{device_id}/alerts")
def list_rules(
    device_id: str,
    username: str = Depends(get_current_username),
):
    require_device_role(username, device_id, "viewer")
    return {"rules": list_alert_rules(device_id)}


@router.put("/devices/{device_id}/alerts/{rule_id}")
def update_rule(
    device_id: str,
    rule_id: int,
    data: AlertRuleUpdate,
    username: str = Depends(get_current_username),
):
    require_device_role(username, device_id, "admin")
    existing = get_alert_rule(rule_id)
    if existing is None or existing["device_id"] != device_id:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    update_alert_rule(
        rule_id, data.metric, data.operator,
        data.threshold, data.enabled
    )
    return get_alert_rule(rule_id)


@router.delete("/devices/{device_id}/alerts/{rule_id}")
def remove_rule(
    device_id: str,
    rule_id: int,
    username: str = Depends(get_current_username),
):
    require_device_role(username, device_id, "admin")
    existing = get_alert_rule(rule_id)
    if existing is None or existing["device_id"] != device_id:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    delete_alert_rule(rule_id)
    return {"deleted": True, "id": rule_id}


@router.get("/alerts/history")
def get_alert_history(
    username: str = Depends(get_current_username),
):
    return {"alerts": list_user_alerts(username)}
