from smp.demo.chaos2.auth_utils import require_admin

@require_admin
def view_reports():
    """Access admin reports."""
    return {"reports": []}
