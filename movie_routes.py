from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
import random
import re
import uuid
import subprocess
import os
from models import Movie, get_db

movie_routes = APIRouter()

# Konfigurace cest
BASE_DIR = Path(__file__).parent
MOVIE_DIR = BASE_DIR / "movie"
THUMBNAIL_DIR = MOVIE_DIR / "thumbnails"

def clean_filename(filename: str) -> str:
    """Vyčistí název souboru od neplechy."""
    cleaned = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    cleaned = re.sub(r'_{2,}', '_', cleaned)
    cleaned = cleaned.strip('_')
    if not cleaned:
        cleaned = f"video_{uuid.uuid4().hex[:8]}"
    return cleaned

def get_video_duration(video_path: Path) -> float:
    """Zjistí délku videa pro výpočet náhodného času."""
    try:
        command = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"FFprobe error: {e}")
        return 0.0

def generate_thumbnail(video_path: Path, thumbnail_path: Path) -> bool:
    """Vygeneruje náhodný WebP náhled z celého klipu."""
    try:
        duration = get_video_duration(video_path)
        # Výběr času: 5% až 95% délky, aby to nebylo jen černé plátno na začátku
        if duration > 2:
            random_time = random.uniform(duration * 0.05, duration * 0.95)
        else:
            random_time = duration / 2 if duration > 0 else 0

        time_str = f"{int(random_time // 3600):02d}:{int((random_time % 3600) // 60):02d}:{random_time % 60:05.2f}"

        # Parametry optimalizované pro WebP a výkon (vhodné pro N i Z)
        command = [
            'ffmpeg', '-ss', time_str, '-i', str(video_path),
            '-vframes', '1', 
            '-vf', 'scale=480:-1', # Zachová poměr stran, šířka 480px
            '-c:v', 'libwebp', 
            '-lossless', '0', 
            '-q:v', '75', 
            '-preset', 'default',
            '-y', str(thumbnail_path)
        ]
        
        result = subprocess.run(command, capture_output=True, timeout=15)
        return result.returncode == 0 and thumbnail_path.exists()
    except Exception as e:
        print(f"FFmpeg error: {e}")
        return False

def create_default_thumbnail(output_path: Path):
    """Vytvoří fallback obrázek, pokud FFmpeg selže."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (480, 270), color=(30, 30, 30))
        d = ImageDraw.Draw(img)
        d.text((240, 135), "NO PREVIEW", fill=(150, 150, 150), anchor="mm")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "WEBP", quality=80)
    except Exception as e:
        print(f"PIL error: {e}")

@movie_routes.post("/upload")
async def upload_movie(video: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        # 1. Vyčištění názvu a OKAMŽITÁ kontrola v databázi
        clean_name = clean_filename(video.filename)
        
        existing_movie = db.query(Movie).filter(Movie.filename == clean_name).first()
        if existing_movie:
            # Vyhodí chybu 400 Bad Request, upload se okamžitě přeruší
            raise HTTPException(
                status_code=400, 
                detail=f"Soubor '{clean_name}' už v databázi existuje!"
            )

        # 2. Pokud neexistuje, vytvoříme složky a začneme ukládat na disk
        MOVIE_DIR.mkdir(exist_ok=True)
        THUMBNAIL_DIR.mkdir(exist_ok=True)
        
        video_path = MOVIE_DIR / clean_name
        with video_path.open("wb") as buffer:
            shutil.copyfileobj(video.file, buffer)

        # 3. Generování WebP náhledu
        thumbnail_name = f"{Path(clean_name).stem}.webp"
        thumbnail_path = THUMBNAIL_DIR / thumbnail_name
        
        thumb_success = generate_thumbnail(video_path, thumbnail_path)
        
        if not thumb_success:
            thumbnail_name = "default.webp"
            default_path = THUMBNAIL_DIR / "default.webp"
            if not default_path.exists():
                create_default_thumbnail(default_path)
        
        thumb_db_path = f"movie/thumbnails/{thumbnail_name}"
        title = Path(clean_name).stem.replace("_", " ").title()
        
        # 4. Zápis nového videa do databáze
        db_movie = Movie(
            filename=clean_name, 
            filepath=f"movie/{clean_name}", 
            thumbnail=thumb_db_path, 
            title=title
        )
        db.add(db_movie)
        db.commit()
        db.refresh(db_movie)
        
        # Vše proběhlo OK -> na frontendu to teď výrazně cinkne!
        return {"status": "success", "movie_id": db_movie.id, "thumbnail": thumb_db_path}

    except HTTPException as http_err:
        # Pokud je to naše vyhozená výjimka o existujícím souboru, jen ji pošleme dál
        raise http_err
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@movie_routes.post("/regenerate/{video_name}")
async def regenerate_thumbnail(video_name: str, db: Session = Depends(get_db)):
    """Vynutí nové vygenerování náhodného WebP náhledu."""
    # 1. Najdeme film v DB
    movie = db.query(Movie).filter(Movie.filename == video_name).first()
    if not movie:
        return JSONResponse(status_code=404, content={"error": "Video nenalezeno v DB"})
    
    video_path = MOVIE_DIR / video_name
    # Vždy vynutíme příponu .webp pro náhled
    thumbnail_name = f"{Path(video_name).stem}.webp"
    thumbnail_path = THUMBNAIL_DIR / thumbnail_name
    
    if not video_path.exists():
        return JSONResponse(status_code=404, content={"error": "Soubor videa na disku chybí"})

    # 2. Smažeme starý náhled, aby FFmpeg mohl vytvořit nový (pro jistotu)
    if thumbnail_path.exists():
        try:
            thumbnail_path.unlink()
        except Exception as e:
            print(f"Nepodařilo se smazat starý náhled: {e}")

    # 3. Spustíme FFmpeg
    if generate_thumbnail(video_path, thumbnail_path):
        # Aktualizujeme cestu v DB (pokud by se náhodou lišila)
        new_thumb_path = f"movie/thumbnails/{thumbnail_name}"
        movie.thumbnail = new_thumb_path
        db.commit()
        
        # VRACÍME ÚSPĚCH - klíčové je pole "thumbnail" pro tvůj JS
        return {"status": "success", "thumbnail": new_thumb_path}
    else:
        # Pokud FFmpeg selže, musíme vrátit chybu, aby se kolečko přestalo točit
        return JSONResponse(status_code=500, content={"error": "Chyba při generování WebP přes FFmpeg"})
    
@movie_routes.post("/delete/{video_name}")
async def delete_video(video_name: str, db: Session = Depends(get_db)):
    movie = db.query(Movie).filter(Movie.filename == video_name).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Video nenalezeno")
    
    # Smazání souborů
    (MOVIE_DIR / video_name).unlink(missing_ok=True)
    # Mažeme WebP verzi
    (THUMBNAIL_DIR / f"{Path(video_name).stem}.webp").unlink(missing_ok=True)
    
    db.delete(movie)
    db.commit()
    return {"status": "success"}

@movie_routes.get("/check-exists")
async def check_movie_exists(filename: str, db: Session = Depends(get_db)):
    clean_name = clean_filename(filename)
    existing_movie = db.query(Movie).filter(Movie.filename == clean_name).first()
    if existing_movie:
        return {"exists": True, "detail": f"Soubor '{clean_name}' už v databázi existuje!"}
    return {"exists": False}

@movie_routes.post("/sync")
async def sync_movies(db: Session = Depends(get_db)):
    """Postupně synchronizuje složku s DB (vždy 1 soubor na request)."""
    exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
    files_on_disk = [f for f in MOVIE_DIR.iterdir() if f.suffix.lower() in exts]
    existing = {m[0] for m in db.query(Movie.filename).all()}
    to_sync = [f for f in files_on_disk if f.name not in existing]
    
    if not to_sync:
        return {"status": "done", "remaining": 0}

    v_path = to_sync[0]
    t_name = f"{v_path.stem}.webp"
    t_path = THUMBNAIL_DIR / t_name
    
    success = generate_thumbnail(v_path, t_path)
    db_thumb = f"movie/thumbnails/{t_name}" if success else "movie/thumbnails/default.webp"
    
    new_movie = Movie(
        filename=v_path.name, 
        filepath=f"movie/{v_path.name}",
        thumbnail=db_thumb, 
        title=v_path.stem.replace("_", " ").title()
    )
    db.add(new_movie)
    db.commit()
    return {"status": "continue", "remaining": len(to_sync) - 1}