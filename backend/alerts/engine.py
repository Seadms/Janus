
from backend.alerts.rules import list_alert_rules
from backend.alerts.history import save_alert

# Tracks whether a rule is currently triggered for each device.
active_alerts = {}

OPERATORS = {
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
}


def evaluate_telemetry(device_id: str, telemetry: dict):
    alerts = []

    for rule in list_alert_rules(device_id):
        if not rule["enabled"]:
            continue

        metric = rule["metric"]
        value = telemetry.get(metric)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue

        operator = OPERATORS.get(rule["operator"])
        if operator is None:
            continue

        triggered = operator(value, rule["threshold"])
        key = (device_id, rule["id"])
        was_triggered = active_alerts.get(key, False)

        if triggered and not was_triggered:
            alerts.append({
                "type": "alert",
                "device_id": device_id,
                "rule_id": rule["id"],
                "metric": metric,
                "value": value,
                "operator": rule["operator"],
                "threshold": rule["threshold"],
                "message": f"{metric} crossed alert threshold",
            })

        active_alerts[key] = triggered

    for alert in alerts:
        save_alert(alert)

    return alerts
