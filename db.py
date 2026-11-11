import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any

DB_FILE = "migration.db"


class MigrationDB:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Tabela de mídias migradas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_assets (
                    asset_id TEXT PRIMARY KEY,
                    filename TEXT,
                    google_media_item_id TEXT,
                    status TEXT,
                    error_message TEXT,
                    synced_at TIMESTAMP
                )
            """)
            # Tabela de álbuns mapeados
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_albums (
                    immich_album_id TEXT PRIMARY KEY,
                    album_name TEXT,
                    google_album_id TEXT,
                    created_at TIMESTAMP
                )
            """)
            conn.commit()

    def is_asset_synced(self, asset_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM synced_assets WHERE asset_id = ? AND status = 'uploaded'", (asset_id,))
            return cursor.fetchone() is not None

    def mark_asset_synced(self, asset_id: str, filename: str, google_id: str = ""):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO synced_assets (asset_id, filename, google_media_item_id, status, error_message, synced_at)
                VALUES (?, ?, ?, 'uploaded', NULL, ?)
            """, (asset_id, filename, google_id, datetime.now().isoformat()))
            conn.commit()

    def mark_asset_failed(self, asset_id: str, filename: str, error_msg: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO synced_assets (asset_id, filename, google_media_item_id, status, error_message, synced_at)
                VALUES (?, ?, NULL, 'failed', ?, ?)
            """, (asset_id, filename, error_msg, datetime.now().isoformat()))
            conn.commit()

    def get_google_album_id(self, immich_album_id: str) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT google_album_id FROM synced_albums WHERE immich_album_id = ?", (immich_album_id,))
            row = cursor.fetchone()
            return row["google_album_id"] if row else None

    def get_all_asset_mappings(self) -> Dict[str, str]:
        """Retorna um dicionário mapeando immich asset_id -> google_media_item_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id, google_media_item_id FROM synced_assets WHERE status = 'uploaded' AND google_media_item_id IS NOT NULL AND google_media_item_id != ''")
            return {row["asset_id"]: row["google_media_item_id"] for row in cursor.fetchall()}


    def record_album(self, immich_album_id: str, album_name: str, google_album_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO synced_albums (immich_album_id, album_name, google_album_id, created_at)
                VALUES (?, ?, ?, ?)
            """, (immich_album_id, album_name, google_album_id, datetime.now().isoformat()))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM synced_assets WHERE status = 'uploaded'")
            uploaded = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM synced_assets WHERE status = 'failed'")
            failed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM synced_albums")
            albums = cursor.fetchone()[0]

            return {
                "uploaded_assets": uploaded,
                "failed_assets": failed,
                "synced_albums": albums
            }

    def reset_video_assets(self) -> int:
        """Remove registros de vídeos enviados para permitir reenviá-los com a data corrigida."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM synced_assets 
                WHERE LOWER(filename) LIKE '%.mp4' 
                   OR LOWER(filename) LIKE '%.mov'
                   OR LOWER(filename) LIKE '%.3gp'
                   OR LOWER(filename) LIKE '%.m4v'
                   OR LOWER(filename) LIKE '%.avi'
                   OR LOWER(filename) LIKE '%.mkv'
            """)
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def reset_failed_assets(self) -> int:
        """Limpa registros com falha para permitir que sejam tentados novamente."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM synced_assets WHERE status = 'failed'")
            deleted = cursor.rowcount
            conn.commit()
            return deleted



