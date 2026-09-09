import sqlite3
import os
import subprocess
from pathlib import Path

# --- KONFIGURACE ---
# Uprav cesty tak, aby odpovídaly tvému Docker volume
DB_PATH = 'gallery.db' 
THUMB_DIR = Path('movie/thumbnails')

def migrate_to_webp():
    if not os.path.exists(DB_PATH):
        print(f"❌ Databáze {DB_PATH} nenalezena!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Vyhledáme všechny záznamy, které stále odkazují na .jpg
    cursor.execute("SELECT id, thumbnail FROM movies WHERE thumbnail LIKE '%.jpg'")
    rows = cursor.fetchall()

    if not rows:
        print("✅ Žádné staré .jpg náhledy k vyřízení.")
        return

    print(f"🚀 Zahajuji migraci a mazání {len(rows)} souborů...")

    for movie_id, thumb_path_db in rows:
        # 1. Příprava cest
        # V databázi máš pravděpodobně: "movie/thumbnails/video.jpg"
        old_jpg_path = Path(thumb_path_db)
        
        # Pokud skript běží mimo složku 'movie', ujistíme se, že cestu najdeme
        if not old_jpg_path.exists():
            # Zkusíme najít soubor v THUMB_DIR, pokud cesta v DB není absolutní
            actual_jpg = THUMB_DIR / old_jpg_path.name
        else:
            actual_jpg = old_jpg_path

        if not actual_jpg.exists():
            print(f"⚠️ Soubor nenalezen, přeskakuji: {actual_jpg}")
            continue

        new_webp_path = actual_jpg.with_suffix('.webp')
        new_db_path = str(old_jpg_path.with_suffix('.webp'))

        # 2. Konverze (FFmpeg)
        try:
            # -q:v 75 je ideální poměr mezi kvalitou a velikostí
            subprocess.run([
                'ffmpeg', '-i', str(actual_jpg),
                '-c:v', 'libwebp', '-lossless', '0', '-q:v', '75',
                '-y', str(new_webp_path)
            ], capture_output=True, check=True)

            # 3. Aktualizace cesty v SQLite
            cursor.execute("UPDATE movies SET thumbnail = ? WHERE id = ?", (new_db_path, movie_id))
            
            # 4. SMAZÁNÍ ORIGINÁLU (Tady dochází k pročištění)
            actual_jpg.unlink()
            
            print(f"🗑️ Zkonvertováno a smazáno: {actual_jpg.name}")

        except Exception as e:
            print(f"❌ Chyba u {actual_jpg.name}: {e}")

    conn.commit()
    conn.close()
    print("\n✨ Hotovo. Adresář thumbnails je vyčištěn a databáze aktualizována.")

if __name__ == "__main__":
    migrate_to_webp()