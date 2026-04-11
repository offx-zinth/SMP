from smp.demo.user_logic import get_user_by_id


def web_get_profile(request: dict):
    """API endpoint to get user profile."""
    uid = request.get("user_id")
    user = get_user_by_id(uid)  # <--- CROSS-FILE CALL
    return {"code": 200, "user": user}
