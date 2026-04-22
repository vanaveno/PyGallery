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

# Setup static files and templates
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

# Include routers
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
    movies = db.query(Movie).order_by(func.random()).all() #desc(Movie.id)
    
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

# Video detail page
# Video detail API - vrací pouze URL pro přehrávač v galerii
@app.get("/api/video-data/{video_id}")
async def get_video_data(video_id: int, db: Session = Depends(get_db)):
    movie = db.query(Movie).filter(Movie.id == video_id).first()
    if not movie:
        return JSONResponse({"error": "Video nenalezeno"}, status_code=404)
    
    return JSONResponse({
        "title": movie.title,
        "video_url": f"/media/{movie.filepath}" # Musí odpovídat tvému mountu app.mount("/media", ...)
    })

@app.get("/gallery/pics")
async def pics_gallery_page(request: Request, db: Session = Depends(get_db)):
    albums = db.query(Pic.album).distinct().all()
    album_data = []

    # Spočítat celkovou velikost alb
    total_size_bytes = 0
    for album in albums:
        album_name = album[0]
        album_dir = PICS_DIR / album_name
        if album_dir.exists():
            for file_path in album_dir.iterdir():
                if file_path.is_file():
                    total_size_bytes += file_path.stat().st_size
    
    total_size_gb = total_size_bytes / (1024 ** 3)
    
    # Zjistit volné místo na disku
    total, used, free = shutil.disk_usage(PICS_DIR)
    free_space_gb = free / (1024 ** 3)
    
    for album in albums:
        album_name = album[0]
        photos = db.query(Pic).filter(Pic.album == album_name).all()
        count = len(photos)
        
        # Získání data vytvoření složky na disku (pro řazení)
        album_dir = PICS_DIR / album_name
        mtime = album_dir.stat().st_mtime if album_dir.exists() else 0
        
        # Najít náhodný náhled
        thumb_url = None
        thumbs_dir = album_dir / "thumbs"
        if thumbs_dir.exists():
            webp_files = list(thumbs_dir.glob("*.webp"))
            if webp_files:
                random_thumb = random.choice(webp_files)
                thumb_url = f"/media/pics/{album_name}/thumbs/{random_thumb.name}"
        
        album_data.append({
            "name": album_name,
            "preview": thumb_url,
            "count": count,
            "mtime": mtime  # Přidáno pro logiku řazení
        })

    # --- LOGIKA ŘAZENÍ: NOVÉ NAHOŘE, ZBYTEK RANDOM ---
    # 1. Seřadíme vše od nejnovějšího
    album_data.sort(key=lambda x: x['mtime'], reverse=True)

    # 2. Oddělíme nejnovější alba (např. první 4)
    top_count = 4 
    newest_albums = album_data[:top_count]
    rest_of_albums = album_data[top_count:]

    # 3. Zbytek promícháme
    random.shuffle(rest_of_albums)

    # 4. Spojíme dohromady
    final_album_list = newest_albums + rest_of_albums
        
    return templates.TemplateResponse(
        request=request, 
        name="pics_gallery.html",
        context={
            "albums": final_album_list,
            "total_size_gb": total_size_gb,
            "free_space_gb": free_space_gb
        }
    )

@app.get("/gallery/embeds")
async def embeds_gallery_page(request: Request, db: Session = Depends(get_db)):
    embeds = db.query(Embed).all()
    return templates.TemplateResponse(
        "embed_gallery.html",
        {"request": request, "embeds": embeds}
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
        "embed_detail.html",
        {
            "request": request,
            "embed": embed
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)