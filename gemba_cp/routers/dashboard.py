from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from gemba_cp.db import get_db
from gemba_cp.schemas.dashboard import MetaResponse, OverviewResponse, RecordsResponse
from gemba_cp.services.dashboard import get_meta, get_overview, get_records


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/meta", response_model=MetaResponse)
def dashboard_meta(db: Session = Depends(get_db)) -> MetaResponse:
    return get_meta(db)


@router.get("/overview", response_model=OverviewResponse)
def dashboard_overview(
    dimension: str = Query(default="unit", pattern="^(month|unit)$"),
    scope: str = Query(default="recent", pattern="^(recent|all)$"),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    unit: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OverviewResponse:
    return get_overview(db, dimension=dimension, scope=scope, year=year, month=month, unit=unit)


@router.get("/records", response_model=RecordsResponse)
def dashboard_records(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    unit: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> RecordsResponse:
    return get_records(db, year=year, month=month, unit=unit, limit=limit)
