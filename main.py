# main.py
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func
import shutil
import random
from sqlalchemy import desc

# Import modulů
from models import Base, Movie, Pic, Embed, Tag, ItemTag, SessionLocal, engine
from movie_routes import movie_routes, generate_thumbnail
from pics_routes import pics_routes
from embed_routes import embed_routes

# Initialize FastAPI application
app = FastAPI()

# Configure paths
BASE_DIR = Path(__file__).parent
MOVIE_DIR = BASE_DIR / "movie"
PICS_DIR = BASE_DIR / "pics"
THUMBNAIL_DIR = MOVIE_DIR / "thumbnails"
TEMPLATES_DIR = BASE_DIR / "templates"

# Create directories
MOVIE_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR.mkdir(exist_ok=True)
PICS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

# Mount static files correctly
# Vše pod BASE_DIR je dostupné přes /media
app.mount("/media", StaticFiles(directory=BASE_DIR), name="media")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create database tables on startup
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

# Include routers - PREFIX /api/pics ZDE URČUJE ZAČÁTEK CESTY
app.include_router(movie_routes, prefix="/api/movies", tags=["movies"])
app.include_router(pics_routes, prefix="/api/pics", tags=["pics"])
app.include_router(embed_routes, prefix="/api/embeds", tags=["embeds"])

# Main pages
@app.get("/")
async def welcome_page(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="welcome.html", 
        context={}
    )

@app.get("/gallery/videos")
async def movie_gallery_page(request: Request, db: Session = Depends(get_db)):
    movies = db.query(Movie).order_by(func.random()).all()
    
    total_size_bytes = 0
    for movie in movies:
        try:
            video_path = MOVIE_DIR / movie.filename
            if video_path.exists():
                total_size_bytes += video_path.stat().st_size
        except:
            continue
    
    total_size_gb = total_size_bytes / (1024 ** 3)
    
    items = []
    for movie in movies:
        items.append({
            "id": movie.id,
            "name": movie.title,
            "video_url": f"/media/{movie.filepath}",
            "thumb_url": f"/media/{movie.thumbnail}",
            "filename": movie.filename
        })

    return templates.TemplateResponse(
        request=request,
        name="video_gallery.html",
        context={
            "gallery_type": "movies",
            "items": items,
            "total_size_gb": total_size_gb,
            "media_path": "/media"
        }
    )

@app.get("/api/video-data/{video_id}")
async def get_video_data(video_id: int, db: Session = Depends(get_db)):
    movie = db.query(Movie).filter(Movie.id == video_id).first()
    if not movie:
        return JSONResponse({"error": "Video nenalezeno"}, status_code=404)
    
    return JSONResponse({
        "title": movie.title,
        "video_url": f"/media/{movie.filepath}"
    })

@app.get("/gallery/pics")
async def pics_gallery_page(request: Request, db: Session = Depends(get_db)):
    total_albums_count = db.query(func.count(func.distinct(Pic.album))).scalar() or 0

    total_size_bytes = 0
    if PICS_DIR.exists():
        for file_path in PICS_DIR.rglob("*"):
            if file_path.is_file():
                total_size_bytes += file_path.stat().st_size

    total_size_gb = total_size_bytes / (1024 ** 3)

    total, used, free = shutil.disk_usage(PICS_DIR if PICS_DIR.exists() else BASE_DIR)
    free_space_gb = free / (1024 ** 3)

    return templates.TemplateResponse(
        request=request, 
        name="pics_gallery.html",
        context={
            "total_albums_count": total_albums_count,
            "total_size_gb": total_size_gb,
            "free_space_gb": free_space_gb
        }
    )

@app.get("/gallery/embeds")
async def embeds_gallery_page(request: Request, db: Session = Depends(get_db)):
    embeds = db.query(Embed).all()
    return templates.TemplateResponse(
        request=request,
        name="embed_gallery.html",
        context={"embeds": embeds}
    )

# Album detail page
@app.get("/album/{album_name}")
async def album_detail(request: Request, album_name: str, db: Session = Depends(get_db)):
    album_exists = db.query(Pic).filter(Pic.album == album_name).first()
    if not album_exists:
        raise HTTPException(404, detail="Album not found")
    
    photos = db.query(Pic).filter(Pic.album == album_name).all()
    
    photos_data = []
    for photo in photos:
        photos_data.append({
            "id": photo.id,
            "filename": photo.filename,
            "original_url": f"/media/pics/{album_name}/{photo.filename}",
            "thumb_url": f"/media/pics/{album_name}/thumbs/{photo.filename}",
            "filepath": photo.filepath
        })
    
    return templates.TemplateResponse(
        request=request,
        name="album_detail.html",
        context={
            "album_name": album_name, 
            "photos": photos_data
        }
    )

# Embed detail page
@app.get("/embed/{embed_id}")
async def embed_detail(request: Request, embed_id: int, db: Session = Depends(get_db)):
    embed = db.query(Embed).filter(Embed.id == embed_id).first()
    if not embed:
        raise HTTPException(404, detail="Embed not found")
    
    return templates.TemplateResponse(
        request=request,
        name="embed_detail.html",
        context={"embed": embed}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)