"""Core: Base Engine — Grandfather Ripple layer."""


class BaseProcessor:
    """Base processor that everything builds on."""

    def execute_logic(self, data: dict):
        """Core logic execution — the deepest function in the chain."""
        return {"processed": True, "data": data}
