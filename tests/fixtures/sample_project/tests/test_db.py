"""Tests for database models."""

from __future__ import annotations

import pytest
from src.db.models import User, Order, DatabaseConnection, UserModel, OrderModel


def test_user_dataclass() -> None:
    """Test User dataclass creation."""
    user = User(id="1", username="alice", email="alice@example.com", created_at="2024-01-01")
    assert user.id == "1"
    assert user.username == "alice"


def test_order_dataclass() -> None:
    """Test Order dataclass creation."""
    order = Order(id="1", user_id="1", product="Widget", quantity=5, status="pending")
    assert order.product == "Widget"
    assert order.quantity == 5


def test_database_connection_connect() -> None:
    """Test DatabaseConnection.connect()."""
    db = DatabaseConnection()
    assert db.connect() is True
    assert db._connected is True


def test_database_connection_disconnect() -> None:
    """Test DatabaseConnection.disconnect()."""
    db = DatabaseConnection()
    db.connect()
    db.disconnect()
    assert db._connected is False


def test_database_connection_execute_returns_list() -> None:
    """Test DatabaseConnection.execute() returns a list."""
    db = DatabaseConnection()
    db.connect()
    result = db.execute("SELECT * FROM users", {})
    assert isinstance(result, list)


def test_user_model_find_by_username_no_results() -> None:
    """Test UserModel.find_by_username returns None when not found."""
    db = DatabaseConnection()
    db.connect()
    model = UserModel(db)
    result = model.find_by_username("nonexistent")
    assert result is None
