"""
A multi-layered authentication system to test SMP's blast radius detection.
"""

# ==========================================
# LAYER 4: DATABASE (The deepest layer)
# ==========================================
def fetch_user_record(email: str, tenant_id: str) -> dict:
    """Hits the database to get the raw user dictionary."""
    # Imagine if someone changes this to fetch_user_record(email: str, tenant_id: str)...
    # It would break everything above it!
    return {"email": email, "hash": "password_123", "role": "admin", "tenant_id": tenant_id}


# ==========================================
# LAYER 3: DOMAIN MODELS & UTILS
# ==========================================
def verify_hash(plain_text: str, hashed: str) -> bool:
    """Validates a password against a stored hash."""
    return f"{plain_text}_123" == hashed

def get_user_model(email: str, tenant_id: str) -> dict:
    """Transforms raw DB record into a business domain model."""
    raw_record = fetch_user_record(email, tenant_id)  # <--- DEPENDS ON LAYER 4
    if not raw_record:
        raise ValueError("User not found")
    return raw_record


# ==========================================
# LAYER 2: BUSINESS SERVICE
# ==========================================
def authenticate_user(email: str, password: str, tenant_id: str) -> str:
    """Core business logic for logging a user in."""
    user = get_user_model(email, tenant_id)  # <--- DEPENDS ON LAYER 3
    
    if verify_hash(password, user["hash"]):  # <--- DEPENDS ON LAYER 3
        return f"jwt_token_for_{user['email']}"
        
    raise PermissionError("Invalid credentials bro 😭")


# ==========================================
# LAYER 1: API CONTROLLER (The top layer)
# ==========================================
def handle_login_request(request_body: dict) -> dict:
    """API handler for the POST /login route."""
    email = request_body.get("email")
    password = request_body.get("password")
    tenant_id = request_body.get("tenant_id") # New required field
    
    if not email or not password or not tenant_id:
        return {"status": 400, "error": "Missing email, password, or tenant_id"}

    try:
        # <--- DEPENDS ON LAYER 2
        token = authenticate_user(email, password, tenant_id)
        return {"status": 200, "token": token}
    except Exception as e:
        return {"status": 401, "error": str(e)}