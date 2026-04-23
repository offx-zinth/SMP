"""
E-Commerce Platform - Backend Services
Real-world codebase with 50+ functions across Python/Rust/Java/TypeScript
Tests circular dependencies, deep nesting, diamond patterns, etc.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import json
import asyncio


# ============================================================================
# CORE DATA MODELS
# ============================================================================


class User:
    """User model with fields."""

    def __init__(self, user_id: str, email: str):
        self.user_id = user_id
        self.email = email


class Order:
    """Order model."""

    def __init__(self, order_id: str, user_id: str, items: List[str]):
        self.order_id = order_id
        self.user_id = user_id
        self.items = items


# ============================================================================
# SERVICE LAYER (LEVEL 1 - Core business logic)
# ============================================================================


def validate_email(email: str) -> bool:
    """Validate email format."""
    return "@" in email and "." in email


def validate_user_id(user_id: str) -> bool:
    """Validate user ID format."""
    return len(user_id) > 0 and user_id.isalnum()


def hash_password(password: str) -> str:
    """Hash password with salt."""
    return f"hashed_{password}"


def generate_token(user_id: str) -> str:
    """Generate auth token."""
    return f"token_{user_id}_{int(datetime.now().timestamp())}"


def sanitize_input(input_str: str) -> str:
    """Remove dangerous characters from input."""
    return input_str.replace("<", "").replace(">", "").replace(";", "")


def calculate_discount(customer_tier: str, amount: float) -> float:
    """Calculate discount based on customer tier."""
    tiers = {"gold": 0.15, "silver": 0.10, "bronze": 0.05}
    discount_rate = tiers.get(customer_tier, 0.0)
    return amount * discount_rate


def calculate_tax(amount: float, region: str) -> float:
    """Calculate tax based on region."""
    tax_rates = {"US": 0.08, "EU": 0.20, "ASIA": 0.05}
    rate = tax_rates.get(region, 0.0)
    return amount * rate


def calculate_shipping(weight: float, distance: float) -> float:
    """Calculate shipping cost."""
    base_rate = 5.0
    weight_factor = weight * 0.5
    distance_factor = distance * 0.01
    return base_rate + weight_factor + distance_factor


def format_currency(amount: float, currency: str = "USD") -> str:
    """Format amount as currency string."""
    return f"{currency} {amount:.2f}"


def log_user_action(user_id: str, action: str, details: str) -> None:
    """Log user action for audit trail."""
    timestamp = datetime.now().isoformat()
    # In real system: write to audit log
    pass


# ============================================================================
# AUTHENTICATION LAYER (LEVEL 2 - Uses Level 1)
# ============================================================================


def create_user(user_id: str, email: str, password: str) -> Optional[User]:
    """Create new user with validation."""
    # Validates
    if not validate_user_id(user_id):
        return None
    if not validate_email(email):
        return None
    # Hashes
    hashed = hash_password(password)
    # Creates
    user = User(user_id, email)
    # Logs
    log_user_action(user_id, "CREATE", f"User created with email {email}")
    return user


def authenticate_user(user_id: str, password: str) -> Optional[str]:
    """Authenticate user and return token."""
    if not validate_user_id(user_id):
        return None
    # Hash provided password
    hashed = hash_password(password)
    # Verify (would check against DB)
    # Generate token
    token = generate_token(user_id)
    # Log
    log_user_action(user_id, "LOGIN", "User authenticated")
    return token


def register_user(user_id: str, email: str, password: str) -> bool:
    """Register new user (high-level wrapper)."""
    # Sanitize inputs
    email = sanitize_input(email)
    user_id = sanitize_input(user_id)
    # Create user
    user = create_user(user_id, email, password)
    if user is None:
        return False
    # Log registration
    log_user_action(user_id, "REGISTER", f"Registered with email {email}")
    return True


def verify_token(token: str) -> Optional[str]:
    """Verify token and extract user_id."""
    if not token.startswith("token_"):
        return None
    parts = token.split("_")
    if len(parts) < 3:
        return None
    # Would verify token signature in real system
    return parts[1]


# ============================================================================
# ORDER PROCESSING LAYER (LEVEL 3 - Complex business logic)
# ============================================================================


def get_product_price(product_id: str) -> float:
    """Fetch product price."""
    # Would query database
    prices = {"P001": 29.99, "P002": 49.99, "P003": 99.99}
    return prices.get(product_id, 0.0)


def get_product_weight(product_id: str) -> float:
    """Fetch product weight in kg."""
    weights = {"P001": 0.5, "P002": 1.0, "P003": 2.0}
    return weights.get(product_id, 0.0)


def calculate_order_subtotal(items: List[str]) -> float:
    """Calculate subtotal from list of product IDs."""
    total = 0.0
    for item in items:
        price = get_product_price(item)
        total += price
    return total


def calculate_order_weight(items: List[str]) -> float:
    """Calculate total weight of order."""
    total_weight = 0.0
    for item in items:
        weight = get_product_weight(item)
        total_weight += weight
    return total_weight


def apply_discount_to_order(
    order_id: str, user_id: str, items: List[str], tier: str
) -> float:
    """Apply discount tier to order."""
    subtotal = calculate_order_subtotal(items)
    discount = calculate_discount(tier, subtotal)
    return subtotal - discount


def calculate_order_total(
    order_id: str, user_id: str, items: List[str], region: str, distance: float, tier: str
) -> Dict[str, float]:
    """Calculate complete order total (DIAMOND PATTERN - calls multiple)."""
    # Level 1 calls (core calculations)
    subtotal = calculate_order_subtotal(items)
    weight = calculate_order_weight(items)

    # Apply discount (Level 2 dependency)
    discounted = apply_discount_to_order(order_id, user_id, items, tier)

    # Calculate additional fees
    tax = calculate_tax(discounted, region)
    shipping = calculate_shipping(weight, distance)

    total = discounted + tax + shipping

    return {
        "subtotal": subtotal,
        "discount": subtotal - discounted,
        "tax": tax,
        "shipping": shipping,
        "total": total,
    }


def process_order(order_id: str, user_id: str, items: List[str], region: str) -> Optional[
    Dict[str, Any]
]:
    """Process order (high-level orchestration)."""
    # Validate user
    if not validate_user_id(user_id):
        return None

    # Validate items
    if not items:
        return None

    # Calculate totals (calls diamond pattern)
    totals = calculate_order_total(order_id, user_id, items, region, distance=100.0, tier="silver")

    # Create order
    order = Order(order_id, user_id, items)

    # Log
    log_user_action(user_id, "ORDER_PLACED", f"Order {order_id} created with {len(items)} items")

    return {"order": {"order_id": order.order_id, "user_id": order.user_id}, "totals": totals}


# ============================================================================
# PAYMENT PROCESSING LAYER (LEVEL 4 - Handles transactions)
# ============================================================================


def validate_payment_method(payment_method: str) -> bool:
    """Validate payment method."""
    valid_methods = ["credit_card", "debit_card", "paypal", "bank_transfer"]
    return payment_method in valid_methods


def encrypt_payment_data(card_number: str) -> str:
    """Encrypt payment card data."""
    # Simplified encryption
    return f"encrypted_{card_number[-4:]}"


def tokenize_payment(card_number: str, card_holder: str) -> str:
    """Tokenize payment card."""
    encrypted = encrypt_payment_data(card_number)
    token = f"pay_token_{encrypted}"
    return token


def process_payment(
    order_id: str, user_id: str, amount: float, payment_method: str, token: str
) -> bool:
    """Process payment transaction."""
    # Validate payment method
    if not validate_payment_method(payment_method):
        return False

    # Verify token
    if not token.startswith("pay_token_"):
        return False

    # Log payment (calls Level 1)
    log_user_action(user_id, "PAYMENT", f"Payment processed for order {order_id}: {format_currency(amount)}")

    return True


def refund_payment(order_id: str, user_id: str, amount: float) -> bool:
    """Refund a payment."""
    # Log refund
    log_user_action(user_id, "REFUND", f"Refund processed for order {order_id}: {format_currency(amount)}")
    return True


# ============================================================================
# INVENTORY LAYER (LEVEL 5 - Complex state management)
# ============================================================================


def get_stock_level(product_id: str) -> int:
    """Get current stock level."""
    stock = {"P001": 100, "P002": 50, "P003": 25}
    return stock.get(product_id, 0)


def reserve_stock(product_id: str, quantity: int) -> bool:
    """Reserve stock for order."""
    current = get_stock_level(product_id)
    if current < quantity:
        return False
    # In real system: update database
    return True


def release_stock(product_id: str, quantity: int) -> bool:
    """Release reserved stock (for cancelled orders)."""
    # In real system: update database
    return True


def check_inventory_availability(items: List[str]) -> bool:
    """Check if all items in list are available (calls get_stock_level)."""
    for item in items:
        stock = get_stock_level(item)
        if stock <= 0:
            return False
    return True


def reserve_order_inventory(order_id: str, items: List[str]) -> bool:
    """Reserve inventory for entire order."""
    # Check availability first
    if not check_inventory_availability(items):
        return False

    # Reserve each item
    for item in items:
        if not reserve_stock(item, 1):
            return False

    return True


# ============================================================================
# FULFILLMENT LAYER (LEVEL 6 - Orchestrates multiple systems)
# ============================================================================


def create_shipment(order_id: str, items: List[str]) -> Optional[str]:
    """Create shipment from order."""
    shipment_id = f"SHIP_{order_id}_{int(datetime.now().timestamp())}"
    return shipment_id


def notify_warehouse(order_id: str, shipment_id: str) -> None:
    """Notify warehouse of new shipment."""
    # In real system: send message to warehouse
    pass


def track_shipment(shipment_id: str) -> Optional[Dict[str, Any]]:
    """Track shipment status."""
    # In real system: query shipping provider
    return {"shipment_id": shipment_id, "status": "pending", "location": "warehouse"}


def cancel_order(order_id: str, user_id: str, items: List[str], amount: float) -> bool:
    """Cancel order and release inventory."""
    # Release stock
    for item in items:
        release_stock(item, 1)

    # Refund payment
    refund_payment(order_id, user_id, amount)

    # Log cancellation
    log_user_action(user_id, "ORDER_CANCELLED", f"Order {order_id} cancelled")

    return True


def complete_order_fulfillment(
    order_id: str, user_id: str, items: List[str], payment_method: str, payment_token: str, region: str
) -> Optional[Dict[str, Any]]:
    """
    Complete order fulfillment (MAXIMUM NESTING - calls 6+ levels)
    Demonstrates deeply nested call chain.
    """
    # Level 1: Process order (calls Level 3 and 2)
    order_result = process_order(order_id, user_id, items, region)
    if not order_result:
        return None

    amount = order_result["totals"]["total"]

    # Level 2: Process payment (calls Level 1)
    payment_success = process_payment(order_id, user_id, amount, payment_method, payment_token)
    if not payment_success:
        return None

    # Level 3: Reserve inventory (calls Level 5)
    inventory_reserved = reserve_order_inventory(order_id, items)
    if not inventory_reserved:
        refund_payment(order_id, user_id, amount)
        return None

    # Level 4: Create shipment
    shipment_id = create_shipment(order_id, items)
    if not shipment_id:
        release_stock(items[0], 1)  # Simplified
        refund_payment(order_id, user_id, amount)
        return None

    # Level 5: Notify warehouse
    notify_warehouse(order_id, shipment_id)

    # Level 6: Log final action
    log_user_action(user_id, "ORDER_FULFILLED", f"Order {order_id} fulfilled with shipment {shipment_id}")

    return {
        "order_id": order_id,
        "shipment_id": shipment_id,
        "amount": amount,
        "status": "fulfilled",
    }


# ============================================================================
# ANALYTICS LAYER (LEVEL 7 - Aggregation and reporting)
# ============================================================================


def get_user_order_history(user_id: str) -> List[Dict[str, Any]]:
    """Get all orders for a user."""
    # In real system: query database
    return []


def calculate_user_spending(user_id: str) -> float:
    """Calculate total spending by user."""
    orders = get_user_order_history(user_id)
    total = sum(order.get("total", 0.0) for order in orders)
    return total


def get_user_tier(user_id: str) -> str:
    """Get customer tier based on spending."""
    spending = calculate_user_spending(user_id)
    if spending > 1000:
        return "gold"
    elif spending > 500:
        return "silver"
    return "bronze"


def generate_order_report(order_id: str) -> Dict[str, Any]:
    """Generate detailed report for order."""
    # In real system: compile from multiple sources
    return {"order_id": order_id, "status": "pending"}


def generate_user_analytics(user_id: str) -> Dict[str, Any]:
    """Generate analytics for user (calls Level 7)."""
    spending = calculate_user_spending(user_id)
    tier = get_user_tier(user_id)
    return {"user_id": user_id, "spending": spending, "tier": tier}


# ============================================================================
# CIRCULAR DEPENDENCY TEST (intentional for testing)
# ============================================================================


def circular_function_a(value: str) -> str:
    """Function A - calls B."""
    if len(value) > 10:
        return circular_function_b(value)
    return value


def circular_function_b(value: str) -> str:
    """Function B - calls A."""
    if value.startswith("x"):
        return circular_function_a(value[1:])
    return value


# ============================================================================
# SELF-REFERENCE TEST
# ============================================================================


def recursive_tree_traversal(depth: int, current: int = 0) -> int:
    """Recursively traverse tree structure."""
    if current >= depth:
        return current
    # Calls itself
    return recursive_tree_traversal(depth, current + 1)


def recursive_factorial(n: int) -> int:
    """Calculate factorial recursively."""
    if n <= 1:
        return 1
    # Calls itself
    return n * recursive_factorial(n - 1)


# ============================================================================
# UTILITY FUNCTIONS (ORPHAN FUNCTIONS - not called by others)
# ============================================================================


def utility_convert_to_json(data: Dict[str, Any]) -> str:
    """Convert data to JSON."""
    return json.dumps(data)


def utility_parse_json(json_str: str) -> Dict[str, Any]:
    """Parse JSON string."""
    return json.loads(json_str)


def utility_get_timestamp() -> str:
    """Get current timestamp."""
    return datetime.now().isoformat()


# ============================================================================
# INTEGRATION TESTS (if main)
# ============================================================================


if __name__ == "__main__":
    print("E-Commerce Platform - Python Services Module")
    print("=" * 60)

    # Test basic flow
    user_id = "user123"
    email = "user@example.com"
    password = "secure_password"

    print("\n1. Register user...")
    registered = register_user(user_id, email, password)
    print(f"   Registered: {registered}")

    print("\n2. Authenticate...")
    token = authenticate_user(user_id, password)
    print(f"   Token: {token}")

    print("\n3. Process order...")
    order_id = "ORD001"
    items = ["P001", "P002"]
    order_result = process_order(order_id, user_id, items, "US")
    print(f"   Order total: ${order_result['totals']['total']:.2f}")

    print("\n4. Complete fulfillment...")
    payment_token = tokenize_payment("4111111111111111", "John Doe")
    fulfillment = complete_order_fulfillment(
        order_id, user_id, items, "credit_card", payment_token, "US"
    )
    print(f"   Fulfillment status: {fulfillment['status'] if fulfillment else 'Failed'}")

    print("\n5. Generate analytics...")
    analytics = generate_user_analytics(user_id)
    print(f"   User tier: {analytics['tier']}")

    print("\n" + "=" * 60)
    print("Module test complete!")
