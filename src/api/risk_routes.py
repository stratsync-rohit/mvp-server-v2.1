"""Public read-only risk APIs."""

from fastapi import APIRouter, Request

from src.schemas.risk import RiskDocument

router = APIRouter(tags=["risks"])


@router.get("/api/risks", response_model=list[RiskDocument])
async def list_risks(request: Request) -> list[RiskDocument]:
    """Return active risks from the database."""
    return await request.app.state.container.risk_service.list()


@router.get("/api/risks/{risk_id}", response_model=RiskDocument)
async def get_risk(risk_id: str, request: Request) -> RiskDocument:
    """Return one active risk by its logical risk ID."""
    return await request.app.state.container.risk_service.get(risk_id)
