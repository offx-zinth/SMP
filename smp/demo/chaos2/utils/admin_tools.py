from smp.demo.chaos2.auth_utils import require_admin


@require_admin
def modify_settings(key: str, value: str):
    """Change system settings."""
    return {"key": key, "value": value}
