from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Agent:
    name: str = "Agent"


@dataclass(slots=True)
class Reviewer:
    name: str = "Reviewer"
