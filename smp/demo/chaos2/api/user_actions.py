from smp.demo.chaos2.auth_utils import require_admin


@require_admin
def delete_user(user_id: int):
    """Delete a user account."""
    return {"deleted": user_id}
