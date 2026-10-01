"""Application service for loading safe risk data."""

from __future__ import annotations

from typing import Any

from src.exceptions import AppError
from src.repositories.risk_repository import RiskRepository
from src.schemas.risk import RiskDocument


class RiskService:
    """Load active risks without coupling card rendering to MongoDB."""

    def __init__(self, repository: RiskRepository) -> None:
        self.repository = repository

    async def list(self) -> list[dict[str, Any]]:
        """Normalize and return active risk documents."""
        documents = await self.repository.list_active()
        return [
            RiskDocument.model_validate(document).as_mapping()
            for document in documents
        ]

    async def get(self, risk_id: str) -> dict[str, Any]:
        """Normalize, validate, and return one active risk document."""
        normalized_risk_id = risk_id.strip() if isinstance(risk_id, str) else ""
        if not normalized_risk_id:
            raise AppError("RISK_ID_INVALID", "risk_id must be a non-empty string.", 422)

        document = await self.repository.get_by_risk_id(normalized_risk_id)
        if document is None or document.get("is_active") is not True:
            raise AppError("RISK_NOT_FOUND", "The active risk was not found.", 404)

        safe_document = dict(document)
        safe_document.pop("_id", None)
        return RiskDocument.model_validate(safe_document).as_mapping()
