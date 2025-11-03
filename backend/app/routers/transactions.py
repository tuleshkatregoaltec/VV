from fastapi import APIRouter, HTTPException
from ..models import Project
from ..database import engine
from sqlmodel import Session, select

router = APIRouter()

@router.get("/transactions/")
async def get_transactions():
    with Session(engine) as session:
        statement = select(Project).limit(1)
        result = session.exec(statement).first()
        if result is None:
            raise HTTPException(status_code=404, detail="No transactions found in database")
        return result
    