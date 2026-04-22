# movie_routes.py
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import ffmpeg
import shutil
import random
import re
import uuid
import subprocess
import os
from models import Movie, get_db

movie_routes = APIRouter()

# Configure paths
BASE_DIR = Path(__file__).parent
MOVIE_DIR = BASE_DIR / "movie"
THUMBNAIL_DIR = MOVIE_DIR / "thumbnails"

def clean_filename(filename: str) -> str:
    """
    Vyčistí název souboru - odstraní speciální znaky a mezery
    """
    # Nechá pouze písmena, čísla, tečky, pomlčky a podtržítka
    cleaned = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    
    # Odstraní více po sobě jdoucích podtržítek
    cleaned = re.sub(r'_{2,}', '_', cleaned)
    
    # Odstraní podtržítka ze začátku a konce
    cleaned = cleaned.strip('_')
    
    # Pokud by název byl prázdný, použijeme UUID
    if not cleaned:
        cleaned = f"video_{uuid.uuid4().hex[:8]}"
    
    return cleaned


@movie_routes.post("/upload")
async def upload_movie(video: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        print(f"Starting upload for: {video.filename}")
        
        # Vyčištění názvu souboru
        original_filename = video.filename
        clean_name = clean_filename(original_filename)
        
        print(f"Original: {original_filename} -> Clean: {clean_name}")
        
        # Ujistíme se, že adresáře existují
        MOVIE_DIR.mkdir(exist_ok=True)
        THUMBNAIL_DIR.mkdir(exist_ok=True)
        
        print(f"MOVIE_DIR: {MOVIE_DIR}")
        print(f"THUMBNAIL_DIR: {THUMBNAIL_DIR}")
        
        # Uložení videa s vyčištěným názvem
        video_path = MOVIE_DIR / clean_name
        print(f"Video path: {video_path}")
        
        try:
            with video_path.open("wb") as buffer:
                shutil.copyfileobj(video.file, buffer)
            print("Video saved successfully")
        except Exception as e:
            print(f"Error saving video: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save video: {str(e)}")

        # Generování náhledu
        thumbnail_path = THUMBNAIL_DIR / f"{Path(clean_name).stem}.jpg"
        
        # Zkusíme vygenerovat thumbnail
        thumb_success = False
        try:
            thumb_success = generate_thumbnail(video_path, thumbnail_path)
            print(f"Thumbnail generation result: {thumb_success}")
        except Exception as e:
            print(f"Thumbnail generation error (continuing anyway): {e}")
        
        # Nastavení cesty k náhledu
        if thumb_success and thumbnail_path.exists() and thumbnail_path.stat().st_size > 0:
            thumb_db_path = f"movie/thumbnails/{thumbnail_path.name}"
            print(f"Using generated thumbnail: {thumb_db_path}")
        else:
            # Použijeme defaultní náhled
            thumb_db_path = "movie/thumbnails/default.jpg"
            print("Using default thumbnail")
            
            # Pokud nemáme default thumbnail, vytvoříme ho
            default_thumb_path = THUMBNAIL_DIR / "default.jpg"
            if not default_thumb_path.exists():
                create_default_thumbnail(default_thumb_path)
        
        title = Path(clean_name).stem.replace("_", " ").title()
        
        # Uložení do DB
        try:
            db_movie = Movie(
                filename=clean_name,
                filepath=f"movie/{clean_name}",
                thumbnail=thumb_db_path,
                title=title
            )
            db.add(db_movie)
            db.commit()
            db.refresh(db_movie)
            print("Database record created successfully")
        except Exception as e:
            db.rollback()
            print(f"Database error: {e}")
            # Pokud selže DB, smažeme nahraný soubor
            if video_path.exists():
                video_path.unlink()
            if thumbnail_path.exists():
                thumbnail_path.unlink()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        return {
            "status": "success", 
            "movie_id": db_movie.id,
            "thumbnail_generated": thumb_success
        }
        
    except HTTPException:
        print("HTTPException raised")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        # Vyčištění při neočekávané chybě
        if 'video_path' in locals() and video_path.exists():
            video_path.unlink()
        if 'thumbnail_path' in locals() and thumbnail_path.exists():
            thumbnail_path.unlink()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
def get_video_duration(video_path: Path) -> float:
    try:
        command = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Chyba při zjišťování délky: {e}")
        return 0.0    


def generate_thumbnail(video_path: Path, thumbnail_path: Path) -> bool:
    try:
        duration = get_video_duration(video_path)
        
        # Výběr náhodného času (mezi 10% a 90% délky videa)
        # Pokud je video moc krátké, vezmeme prostě 1. sekundu
        if duration > 2:
            start_point = duration * 0.1
            end_point = duration * 0.9
            random_time = random.uniform(start_point, end_point)
        else:
            random_time = 1.0

        # Formátování času pro FFmpeg (např. 00:01:23)
        time_str = f"{int(random_time // 3600):02d}:{int((random_time % 3600) // 60):02d}:{random_time % 60:05.2f}"

        command = [
            'ffmpeg',
            '-ss', time_str, 
            '-i', str(video_path),
            '-vframes', '1',
            '-vf', 'scale=320:240',
            '-q:v', '2',
            '-y',
            str(thumbnail_path)
        ]

        print(f"[THUMB] Running command: {' '.join(command)}")
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10  # Timeout po 10 sekundách
        )

        if result.returncode != 0:
            print(f"[THUMB] FFMPEG error (code {result.returncode}):")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return False

        # Kontrola výsledku
        if thumbnail_path.exists():
            file_size = thumbnail_path.stat().st_size
            print(f"[THUMB] Thumbnail created: {file_size} bytes")
            return file_size > 0
        else:
            print("[THUMB] Thumbnail file was not created")
            return False

    except subprocess.TimeoutExpired:
        print("[THUMB] FFMPEG timeout")
        return False
    except Exception as e:
        print(f"[THUMB] Unexpected error: {e}")
        return False


def create_default_thumbnail(output_path: Path):
    """Vytvoří jednoduchý defaultní thumbnail"""
    try:
        # Vytvoříme jednoduchý obrázek s textem
        from PIL import Image, ImageDraw, ImageFont
        
        img = Image.new('RGB', (320, 240), color=(40, 40, 40))
        d = ImageDraw.Draw(img)
        
        # Jednoduchý text
        d.text((160, 120), "NO THUMBNAIL", fill=(255, 255, 255), anchor="mm")
        
        # Uložení
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "JPEG", quality=85)
        print(f"Default thumbnail created at: {output_path}")
    except Exception as e:
        print(f"Could not create default thumbnail: {e}")
        # Vytvoř prázdný soubor jako fallback
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b'')


    
@movie_routes.post("/delete/{video_name}")
async def delete_video(video_name: str, db: Session = Depends(get_db)):
    movie = db.query(Movie).filter(Movie.filename == video_name).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Video not found")
    
    video_path = MOVIE_DIR / video_name
    thumbnail_path = THUMBNAIL_DIR / f"{Path(video_name).stem}.jpg"
    
    try:
        # Smazat video pokud existuje
        if video_path.exists():
            video_path.unlink()
        
        # Smazat náhled pokud existuje
        if thumbnail_path.exists():
            thumbnail_path.unlink()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting files: {str(e)}")
    
    # Smazat záznam z databáze
    db.delete(movie)
    db.commit()
    
    return {"status": "success"}
    
@movie_routes.post("/sync")
async def sync_movies(db: Session = Depends(get_db)):
    supported_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
    
    # 1. Najdeme všechny soubory na disku
    files_on_disk = [f for f in MOVIE_DIR.iterdir() if f.is_file() and f.suffix.lower() in supported_extensions]
    
    # 2. Zjistíme, co už máme v DB
    existing_filenames = {m[0] for m in db.query(Movie.filename).all()}
    
    # 3. Najdeme soubory, které chybí
    to_sync = [f for f in files_on_disk if f.name not in existing_filenames]
    
    if not to_sync:
        return {"status": "done", "message": "Vše je synchronizováno", "remaining": 0}

    # 4. Zpracujeme pouze JEDEN (první) soubor ze seznamu
    video_path = to_sync[0]
    try:
        thumb_name = f"{video_path.stem}.jpg"
        thumbnail_path = THUMBNAIL_DIR / thumb_name
        
        # Pokus o generování náhledu
        success = generate_thumbnail(video_path, thumbnail_path)
        
        # Cesta pro DB (včetně fallbacku, pokud náhled selže)
        thumb_db_path = f"movie/thumbnails/{thumb_name}" if success else "movie/thumbnails/default.jpg"
        
        title = " ".join(video_path.stem.split("_")).title()
        
        new_movie = Movie(
            filename=video_path.name,
            filepath=f"movie/{video_path.name}",
            thumbnail=thumb_db_path,
            title=title
        )
        db.add(new_movie)
        db.commit()
        
        return {
            "status": "continue", 
            "message": f"Zpracováno: {video_path.name}",
            "remaining": len(to_sync) - 1
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e), "remaining": len(to_sync) - 1}

@movie_routes.post("/regenerate/{video_name}")
async def regenerate_thumbnail(video_name: str, db: Session = Depends(get_db)):
    """
    Vynutí vygenerování nového náhodného náhledu pro konkrétní video.
    """
    movie = db.query(Movie).filter(Movie.filename == video_name).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Video v databázi nenalezeno")
    
    video_path = MOVIE_DIR / video_name
    thumbnail_path = THUMBNAIL_DIR / f"{Path(video_name).stem}.jpg"
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Soubor videa {video_name} neexistuje na disku")

    # Spustíme tvou existující funkci generate_thumbnail, 
    # která v sobě má ten random.uniform
    success = generate_thumbnail(video_path, thumbnail_path)
    
    if success:
        # Aktualizujeme cestu v DB, pokud by tam náhodou byl dřív default.jpg
        movie.thumbnail = f"movie/thumbnails/{thumbnail_path.name}"
        db.commit()
        return {"status": "success", "thumbnail": movie.thumbnail}
    else:
        raise HTTPException(status_code=500, detail="Nepodařilo se vygenerovat nový náhled")