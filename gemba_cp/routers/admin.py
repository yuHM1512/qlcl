from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from gemba_cp.db import get_db
from gemba_cp.services.sync import sync_sheet_to_database


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync-sheet")
def sync_sheet(db: Session = Depends(get_db)) -> dict[str, object]:
    result = sync_sheet_to_database(db)
    return {
        "ok": True,
        "inserted": result.inserted_gemba_cp + result.inserted_plan,
        "inserted_gemba_cp": result.inserted_gemba_cp,
        "inserted_plan": result.inserted_plan,
        "synced_at": result.synced_at.isoformat(),
    }
