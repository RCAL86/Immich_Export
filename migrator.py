import time
from typing import Callable, Optional, Dict, List, Any
from db import MigrationDB
from immich_client import ImmichClient
from google_photos_client import GooglePhotosClient
from exif_injector import inject_media_metadata


class ImmichToGooglePhotosMigrator:
    def __init__(
        self,
        immich: ImmichClient,
        google_photos: GooglePhotosClient,
        db: MigrationDB,
        sync_albums: bool = True,
        inject_exif: bool = True,
        request_delay: float = 1.5
    ):
        self.immich = immich
        self.google_photos = google_photos
        self.db = db
        self.sync_albums = sync_albums
        self.inject_exif = inject_exif
        self.request_delay = request_delay

    def prepare_albums(self, log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, List[str]]:
        """
        Mapeia os álbuns do Immich, recria os que faltam no Google Fotos
        e retorna um dicionário mapeando cada asset_id -> lista de google_album_ids.
        """
        asset_to_google_albums: Dict[str, List[str]] = {}

        if not self.sync_albums:
            return asset_to_google_albums

        if log_fn:
            log_fn("🔍 Carregando álbuns do Immich...")

        try:
            immich_albums = self.immich.get_all_albums()
        except Exception as e:
            if log_fn:
                log_fn(f"⚠️ Erro ao listar álbuns do Immich: {e}")
            return asset_to_google_albums

        if log_fn:
            log_fn(f"📁 {len(immich_albums)} álbum(ns) encontrado(s) no Immich.")

        for alb in immich_albums:
            alb_id = alb.get("id")
            alb_name = alb.get("albumName") or "Sem Nome"

            # Verifica se já foi sincronizado
            google_alb_id = self.db.get_google_album_id(alb_id)
            if not google_alb_id:
                try:
                    if log_fn:
                        log_fn(f"➕ Criando álbum no Google Fotos: '{alb_name}'")
                    google_alb_id = self.google_photos.create_album(alb_name)
                    self.db.record_album(alb_id, alb_name, google_alb_id)
                    # Pausa estratégica para não estourar o limite de criação por minuto do Google
                    time.sleep(2.5)
                except Exception as e:
                    if log_fn:
                        log_fn(f"❌ Falha ao criar álbum '{alb_name}' no Google Fotos: {e}")
                    continue

            # Mapeia quais assets pertencem a este álbum
            try:
                details = self.immich.get_album_details(alb_id)
                alb_assets = details.get("assets", [])
                for a in alb_assets:
                    a_id = a.get("id")
                    if a_id:
                        if a_id not in asset_to_google_albums:
                            asset_to_google_albums[a_id] = []
                        asset_to_google_albums[a_id].append(google_alb_id)
            except Exception as e:
                if log_fn:
                    log_fn(f"⚠️ Falha ao ler itens do álbum '{alb_name}': {e}")

        return asset_to_google_albums

    def populate_albums(self, log_fn: Optional[Callable[[str], None]] = None):
        """
        Vincula todas as fotos já enviadas aos seus respectivos álbuns no Google Fotos,
        sem precisar fazer upload de nada novamente!
        """
        if log_fn:
            log_fn("🔍 Mapeando fotos já enviadas no banco local...")
        asset_map = self.db.get_all_asset_mappings()
        if log_fn:
            log_fn(f"📦 {len(asset_map)} fotos mapeadas com ID do Google Fotos.")

        immich_albums = self.immich.get_all_albums()
        if log_fn:
            log_fn(f"📁 Processando {len(immich_albums)} álbuns do Immich...")

        for alb in immich_albums:
            alb_id = alb.get("id")
            alb_name = alb.get("albumName") or "Sem Nome"
            google_alb_id = self.db.get_google_album_id(alb_id)
            if not google_alb_id:
                try:
                    google_alb_id = self.google_photos.create_album(alb_name)
                    self.db.record_album(alb_id, alb_name, google_alb_id)
                    time.sleep(2.0)
                except Exception as e:
                    if log_fn:
                        log_fn(f"❌ Erro ao criar álbum '{alb_name}': {e}")
                    continue

            # Obter assets do álbum
            alb_assets = self.immich.get_album_assets(alb_id)
            media_ids_to_add = []
            for a in alb_assets:
                a_id = a.get("id")
                if a_id in asset_map:
                    media_ids_to_add.append(asset_map[a_id])

            if media_ids_to_add:
                if log_fn:
                    log_fn(f"📁 Vinculando {len(media_ids_to_add)} fotos ao álbum: '{alb_name}'...")
                try:
                    self.google_photos.add_media_to_album(google_alb_id, media_ids_to_add)
                    if log_fn:
                        log_fn(f"✔ Álbum '{alb_name}' sincronizado com sucesso!")
                except Exception as e:
                    if log_fn:
                        log_fn(f"❌ Falha ao vincular fotos ao álbum '{alb_name}': {e}")
            else:
                if log_fn:
                    log_fn(f"ℹ️ Álbum '{alb_name}': nenhuma foto deste álbum foi enviada ainda.")

            time.sleep(1.0)

    def run_migration(

        self,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_fn: Optional[Callable[[str], None]] = None
    ):
        """
        Executa o processo completo de migração via streaming (sem salvar gigabytes localmente).
        """
        asset_album_map = self.prepare_albums(log_fn)

        if log_fn:
            log_fn("🚀 Iniciando varredura e transferência dos arquivos do Immich...")

        immich_stats = self.immich.get_statistics()
        total_in_immich = immich_stats.get("total", 0)

        processed = 0
        skipped = 0
        errors = 0

        for asset in self.immich.get_all_assets():
            asset_id = asset.get("id")
            filename = asset.get("originalFileName") or f"{asset_id}.jpg"

            # Pula se já sincronizado com sucesso anteriormente
            if self.db.is_asset_synced(asset_id):
                skipped += 1
                if on_progress:
                    on_progress({
                        "status": "skipped",
                        "asset_id": asset_id,
                        "filename": filename,
                        "processed": processed,
                        "skipped": skipped,
                        "errors": errors
                    })
                continue

            current_done = skipped + processed
            if total_in_immich > 0:
                pct = (current_done / total_in_immich) * 100
                prefix = f"[{current_done + 1}/{total_in_immich} | {pct:.1f}%]"
            else:
                prefix = f"[{current_done + 1}]"

            try:
                if log_fn:
                    log_fn(f"{prefix} ⬇️ Baixando: {filename}...")
                file_bytes = self.immich.download_asset_bytes(asset_id)

                # Injeta EXIF ou QuickTime MP4 para garantir a linha do tempo e GPS no Google Fotos
                if self.inject_exif:
                    file_bytes = inject_media_metadata(file_bytes, asset, filename)

                # Upload dos bytes
                if log_fn:
                    log_fn(f"{prefix} ⬆️ Enviando para o Google Fotos: {filename}...")
                upload_token = self.google_photos.upload_bytes(file_bytes, filename)

                # Determina os álbuns de destino
                target_albums = asset_album_map.get(asset_id, [])
                primary_album = target_albums[0] if target_albums else None
                desc = (asset.get("exifInfo") or {}).get("description") or ""

                # Registra na biblioteca e no álbum primário
                media_item = self.google_photos.batch_create_media_item(
                    upload_token=upload_token,
                    filename=filename,
                    description=desc,
                    album_id=primary_album
                )
                google_id = media_item.get("id", "")

                # Se a foto estiver em mais de um álbum, vincula aos demais
                if len(target_albums) > 1 and google_id:
                    for extra_album in target_albums[1:]:
                        try:
                            self.google_photos.add_media_to_album(extra_album, [google_id])
                        except Exception as e:
                            if log_fn:
                                log_fn(f"⚠️ Erro ao vincular ao álbum adicional: {e}")

                # Salva sucesso no banco local SQLite
                self.db.mark_asset_synced(asset_id, filename, google_id)
                processed += 1

                if on_progress:
                    on_progress({
                        "status": "uploaded",
                        "asset_id": asset_id,
                        "filename": filename,
                        "processed": processed,
                        "skipped": skipped,
                        "errors": errors
                    })

                # Pausa para respeitar as quotas de requisições por minuto do Google Fotos
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

            except Exception as e:
                errors += 1
                error_msg = str(e)
                self.db.mark_asset_failed(asset_id, filename, error_msg)
                if log_fn:
                    log_fn(f"❌ Erro ao transferir '{filename}': {error_msg}")

                if on_progress:
                    on_progress({
                        "status": "failed",
                        "asset_id": asset_id,
                        "filename": filename,
                        "error": error_msg,
                        "processed": processed,
                        "skipped": skipped,
                        "errors": errors
                    })

        if log_fn:
            log_fn(f"🎉 Migração de arquivos finalizada! Transferidos: {processed}, Já existentes: {skipped}, Falhas: {errors}")

        # Vincula todas as fotos enviadas aos seus álbuns correspondentes no Google Fotos
        if self.sync_albums:
            if log_fn:
                log_fn("📁 Organizando e vinculando fotos aos álbuns no Google Fotos...")
            self.populate_albums(log_fn=log_fn)


