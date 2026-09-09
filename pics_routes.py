# pics_routes.py
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form, Query
from sqlalchemy.orm import Session
from pathlib import Path
from PIL import Image
import io
import zipfile
import shutil
import random

from models import Pic, get_db

pics_routes = APIRouter()

# Configure paths
BASE_DIR = Path(__file__).parent
PICS_DIR = BASE_DIR / "pics"

# Konfigurace
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
WEBP_CONFIG = {
    'original_quality': 85,
    'thumbnail_quality': 75,
    'max_original_size': (1920, 1080),
    'thumbnail_size': (450, 750)
}

# Pomocné funkce
def normalize_album_name(name: str) -> str:
    if not name:
        name = "album"
    name = name.replace(' ', '_')
    name = ''.join(c for c in name if c.isalnum() or c in ['_', '-'])
    return name.lower()

def should_process_file(file_info) -> bool:
    if file_info.is_dir():
        return False
    file_ext = Path(file_info.filename).suffix.lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        return False
    if Path(file_info.filename).name.startswith('.'):
        return False
    return True

def convert_to_webp(image_data: bytes, max_size: tuple = None, quality: int = 85) -> bytes:
    try:
        image = Image.open(io.BytesIO(image_data))
        if image.mode in ('RGBA', 'P'):
            image = image.convert('RGB')
        if max_size:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format='WEBP', quality=quality, optimize=True)
        return output.getvalue()
    except Exception as e:
        raise Exception(f"Chyba konverze obrázku: {str(e)}")

def create_thumbnail(image_data: bytes, size: tuple = (320, 240), quality: int = 75) -> bytes:
    try:
        image = Image.open(io.BytesIO(image_data))
        if image.mode in ('RGBA', 'P'):
            image = image.convert('RGB')
        image.thumbnail(size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format='WEBP', quality=quality, optimize=True)
        return output.getvalue()
    except Exception as e:
        raise Exception(f"Chyba vytváření náhledu: {str(e)}")

def select_random_thumbnail(thumbs_dir: Path) -> str:
    image_files = list(thumbs_dir.glob("*.webp"))
    if not image_files:
        return None
    return random.choice(image_files).name


# --- ENDPOINT PRO RYCHLOU KONTROLU PŘED UPLOADEM ---
@pics_routes.get("/check-exists")
async def check_album_exists(album_name: str, db: Session = Depends(get_db)):
    if not album_name:
        return {"exists": False}
        
    normalized_name = normalize_album_name(album_name)
    existing = db.query(Pic).filter(Pic.album == normalized_name).first()
    
    if existing:
        return {
            "exists": True, 
            "detail": f"Album '{normalized_name}' už v databázi existuje! Upload byl zastaven."
        }
    return {"exists": False}


# --- UPLOAD ENDPOINT PRO VÍCE SOUBORŮ ---
@pics_routes.post("/upload")
async def upload_pics(
    zip_files: list[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    overall_stats = []
    
    for zip_file in zip_files:
        stats = {
            'file_name': zip_file.filename,
            'total_files': 0,
            'converted': 0,
            'skipped': 0,
            'errors': []
        }
        
        album_name = Path(zip_file.filename).stem
        final_album_name = normalize_album_name(album_name)
        
        # 1. KONTROLA DUPLICITY
        existing_check = db.query(Pic).filter(Pic.album == final_album_name).first()
        if existing_check:
            stats['errors'].append(f"Album '{final_album_name}' už existuje v DB! Tento ZIP byl přeskočen.")
            overall_stats.append({"status": "skipped", "album_name": final_album_name, "stats": stats})
            continue

        album_dir = PICS_DIR / final_album_name
        thumbs_dir = album_dir / "thumbs"
        
        album_dir_existed_before = album_dir.exists()
        
        album_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir.mkdir(exist_ok=True)
        
        temp_zip_path = album_dir / "temp_upload.zip"
        created_files = []  
        
        try:
            with open(temp_zip_path, "wb") as buffer:
                shutil.copyfileobj(zip_file.file, buffer)
            
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                for file_info in zip_ref.filelist:
                    if should_process_file(file_info):
                        stats['total_files'] += 1
                        original_filename = Path(file_info.filename).name
                        
                        try:
                            file_data = zip_ref.read(file_info.filename)
                            if not file_data:
                                stats['skipped'] += 1
                                stats['errors'].append(f"{original_filename}: Prázdný soubor")
                                continue
                            
                            webp_filename = Path(file_info.filename).stem + '.webp'
                            
                            webp_data = convert_to_webp(
                                file_data, 
                                max_size=WEBP_CONFIG['max_original_size'],
                                quality=WEBP_CONFIG['original_quality']
                            )
                            
                            thumb_data = create_thumbnail(
                                file_data,
                                size=WEBP_CONFIG['thumbnail_size'], 
                                quality=WEBP_CONFIG['thumbnail_quality']
                            )
                            
                            original_path = album_dir / webp_filename
                            thumb_path = thumbs_dir / webp_filename
                            
                            with open(original_path, 'wb') as f:
                                f.write(webp_data)
                            created_files.append(original_path)
                                
                            with open(thumb_path, 'wb') as f:
                                f.write(thumb_data)
                            created_files.append(thumb_path)
                            
                            db_pic = Pic(
                                album=final_album_name,
                                filename=webp_filename,
                                filepath=f"pics/{final_album_name}/{webp_filename}"
                            )
                            db.add(db_pic)
                            stats['converted'] += 1
                            
                        except Exception as e:
                            stats['skipped'] += 1
                            stats['errors'].append(f"{original_filename}: {str(e)}")
                            continue
            
            random_thumb_name = select_random_thumbnail(thumbs_dir)
            thumbnail_url = f"/media/pics/{final_album_name}/thumbs/{random_thumb_name}" if random_thumb_name else None
            
            db.commit()
            overall_stats.append({
                "status": "success",
                "album_name": final_album_name,
                "thumbnail": thumbnail_url,
                "stats": stats
            })
            
        except zipfile.BadZipFile:
            stats['errors'].append("Neplatný nebo poškozený ZIP soubor")
            overall_stats.append({"status": "failed", "album_name": final_album_name, "stats": stats})
            if not album_dir_existed_before and album_dir.exists():
                shutil.rmtree(album_dir)
        except Exception as e:
            db.rollback()
            for f_path in created_files:
                if f_path.exists():
                    f_path.unlink()
            if not album_dir_existed_before and album_dir.exists():
                remaining = [p for p in album_dir.iterdir() if p.name != "thumbs" and p.name != "temp_upload.zip"]
                if not remaining:
                    shutil.rmtree(album_dir)
                    
            stats['errors'].append(f"Kritická chyba: {str(e)}")
            overall_stats.append({"status": "failed", "album_name": final_album_name, "stats": stats})
        finally:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
                
    return {"status": "finished", "results": overall_stats}

@pics_routes.delete("/album/{album_name}")
async def delete_album(album_name: str, db: Session = Depends(get_db)):
    try:
        db.query(Pic).filter(Pic.album == album_name).delete()
        db.commit()
        
        album_dir = PICS_DIR / album_name
        if album_dir.exists():
            shutil.rmtree(album_dir)
            
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Failed to delete album: {str(e)}")

@pics_routes.post("/sync")
async def sync_pics(db: Session = Depends(get_db)):
    stats = {'new_albums': 0, 'new_images': 0, 'errors': []}
    
    if not PICS_DIR.exists():
        PICS_DIR.mkdir(parents=True, exist_ok=True)

    for album_path in PICS_DIR.iterdir():
        if not album_path.is_dir():
            continue
            
        album_name = album_path.name
        thumbs_dir = album_path / "thumbs"
        thumbs_dir.mkdir(exist_ok=True)

        for img_path in album_path.iterdir():
            if not img_path.is_file() or img_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                continue

            existing = db.query(Pic).filter(
                Pic.album == album_name, 
                Pic.filename == img_path.name
            ).first()
            
            if existing:
                continue

            try:
                with open(img_path, "rb") as f:
                    file_data = f.read()

                if img_path.suffix.lower() != '.webp':
                    webp_data = convert_to_webp(
                        file_data, 
                        max_size=WEBP_CONFIG['max_original_size'],
                        quality=WEBP_CONFIG['original_quality']
                    )
                    webp_name = img_path.stem + ".webp"
                    new_img_path = album_path / webp_name
                    
                    with open(new_img_path, "wb") as f:
                        f.write(webp_data)
                    
                    img_path.unlink()
                    current_filename = webp_name
                else:
                    current_filename = img_path.name

                thumb_path = thumbs_dir / current_filename
                if not thumb_path.exists():
                    thumb_data = create_thumbnail(
                        file_data,
                        size=WEBP_CONFIG['thumbnail_size'], 
                        quality=WEBP_CONFIG['thumbnail_quality']
                    )
                    with open(thumb_path, "wb") as f:
                        f.write(thumb_data)

                db_pic = Pic(
                    album=album_name,
                    filename=current_filename,
                    filepath=f"pics/{album_name}/{current_filename}"
                )
                db.add(db_pic)
                stats['new_images'] += 1
                
            except Exception as e:
                stats['errors'].append(f"Chyba {img_path.name}: {str(e)}")

    db.commit()
    return {"status": "success", "stats": stats}

@pics_routes.get("/albums")
async def get_paginated_albums(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    distinct_albums = db.query(Pic.album).distinct().all()
    all_album_names = [a[0] for a in distinct_albums]
    total_albums = len(all_album_names)

    albums_with_mtime = []
    for name in all_album_names:
        album_dir = PICS_DIR / name
        mtime = album_dir.stat().st_mtime if album_dir.exists() else 0
        albums_with_mtime.append((name, mtime))

    albums_with_mtime.sort(key=lambda x: x[1], reverse=True)

    top_count = 4
    newest = [a[0] for a in albums_with_mtime[:top_count]]
    rest = [a[0] for a in albums_with_mtime[top_count:]]
    
    ordered_album_names = newest + rest

    offset = (page - 1) * limit
    paged_names = ordered_album_names[offset:offset + limit]

    albums_data = []
    for album_name in paged_names:
        count = db.query(Pic).filter(Pic.album == album_name).count()
        
        album_dir = PICS_DIR / album_name
        thumbs_dir = album_dir / "thumbs"
        
        random_thumb = select_random_thumbnail(thumbs_dir) if thumbs_dir.exists() else None
        thumb_url = f"/media/pics/{album_name}/thumbs/{random_thumb}" if random_thumb else None

        albums_data.append({
            "name": album_name,
            "preview": thumb_url,
            "count": count
        })

    has_more = (offset + limit) < total_albums

    return {
        "albums": albums_data,
        "has_more": has_more,
        "total": total_albums
    }