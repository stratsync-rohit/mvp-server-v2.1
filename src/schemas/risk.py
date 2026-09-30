"""Flexible domain contract for evolving risk documents."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class RiskDocument(BaseModel):
    """Require only identity while preserving unknown risk fields."""

    model_config = ConfigDict(extra="allow")

    risk_id: str

    def as_mapping(self) -> dict[str, Any]:
        """Return the safe, schema-evolution-friendly risk mapping."""
        return self.model_dump()
