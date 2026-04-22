# embed_routes.py
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from models import Embed, get_db

embed_routes = APIRouter()

@embed_routes.post("/upload")
async def add_embed(embed_code: str, title: str, db: Session = Depends(get_db)):
    db_embed = Embed(
        embed_code=embed_code,
        title=title
    )
    db.add(db_embed)
    db.commit()
    return {"status": "success", "embed_id": db_embed.id}

@embed_routes.get("/")
async def get_all_embeds(db: Session = Depends(get_db)):
    embeds = db.query(Embed).all()
    return {"embeds": embeds}

@embed_routes.get("/{embed_id}")
async def get_embed(embed_id: int, db: Session = Depends(get_db)):
    embed = db.query(Embed).filter(Embed.id == embed_id).first()
    if not embed:
        raise HTTPException(404, detail="Embed not found")
    return {"embed": embed}

@embed_routes.delete("/{embed_id}")
async def delete_embed(embed_id: int, db: Session = Depends(get_db)):
    embed = db.query(Embed).filter(Embed.id == embed_id).first()
    if not embed:
        raise HTTPException(404, detail="Embed not found")
    
    db.delete(embed)
    db.commit()
    return {"status": "success"}