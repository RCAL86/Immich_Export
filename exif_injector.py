import io
import os
import struct
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import piexif

OFFSET_1904 = 2082844800  # Segundos entre 01/01/1904 (QuickTime Epoch) e 01/01/1970 (Unix Epoch)


def _to_deg(value: float, loc: list):
    """Converte coordenadas decimais em graus, minutos e segundos para o formato EXIF."""
    if value < 0:
        loc_value = loc[0]
    else:
        loc_value = loc[1]
    abs_value = abs(value)
    deg = int(abs_value)
    t1 = (abs_value - deg) * 60
    min_val = int(t1)
    sec = round((t1 - min_val) * 60, 4)
    return ((deg, 1), (min_val, 1), (int(sec * 10000), 10000)), loc_value


def _parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Converte string ISO do Immich para objeto datetime."""
    if not date_str:
        return None
    try:
        clean_str = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except Exception:
        return None


def _format_exif_date(dt: Optional[datetime]) -> Optional[str]:
    """Formata datetime para o padrão EXIF: YYYY:MM:DD HH:MM:SS."""
    if not dt:
        return None
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def inject_video_metadata(file_bytes: bytes, asset_info: Dict[str, Any]) -> bytes:
    """
    Injeta o timestamp de criação nos átomos QuickTime/MP4 (mvhd, tkhd, mdhd).
    O Google Fotos lê essa informação para posicionar o vídeo na linha do tempo!
    """
    exif_info = asset_info.get("exifInfo") or {}
    raw_date = (
        exif_info.get("dateTimeOriginal")
        or asset_info.get("fileCreatedAt")
        or asset_info.get("createdAt")
    )
    dt = _parse_datetime(raw_date)
    if not dt:
        return file_bytes

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts_1904 = int(dt.timestamp()) + OFFSET_1904

    data = bytearray(file_bytes)
    target_atoms = [b"mvhd", b"tkhd", b"mdhd"]

    for atom in target_atoms:
        idx = 0
        while True:
            idx = data.find(atom, idx)
            if idx == -1:
                break

            if idx >= 4 and idx + 16 <= len(data):
                version = data[idx + 4]
                if version == 0 and idx + 16 <= len(data):
                    struct.pack_into(">I", data, idx + 8, ts_1904)
                    struct.pack_into(">I", data, idx + 12, ts_1904)
                elif version == 1 and idx + 24 <= len(data):
                    struct.pack_into(">Q", data, idx + 8, ts_1904)
                    struct.pack_into(">Q", data, idx + 16, ts_1904)

            idx += 4

    return bytes(data)


def inject_exif_metadata(file_bytes: bytes, asset_info: Dict[str, Any]) -> bytes:
    """
    Injeta ou sobrescreve metadados de data/hora (DateTimeOriginal) e GPS no cabeçalho EXIF
    da imagem, garantindo que o Google Fotos leia a data exata do Immich.
    """
    try:
        try:
            exif_dict = piexif.load(file_bytes)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        modified = False

        # 1. Determina a data correta vinda do Immich
        exif_info = asset_info.get("exifInfo") or {}
        raw_date = (
            exif_info.get("dateTimeOriginal")
            or asset_info.get("fileCreatedAt")
            or asset_info.get("createdAt")
        )
        dt = _parse_datetime(raw_date)
        exif_date_str = _format_exif_date(dt)

        if exif_date_str:
            date_bytes = exif_date_str.encode("utf-8")
            # Força a gravação da data exata do Immich
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_bytes
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_bytes
            exif_dict["0th"][piexif.ImageIFD.DateTime] = date_bytes
            modified = True

        # 2. Determina coordenadas GPS
        lat = exif_info.get("latitude")
        lon = exif_info.get("longitude")
        if lat is not None and lon is not None:
            gps_lat, lat_ref = _to_deg(float(lat), ["S", "N"])
            gps_lon, lon_ref = _to_deg(float(lon), ["W", "E"])

            exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref.encode("utf-8")
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = gps_lat
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref.encode("utf-8")
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = gps_lon
            modified = True

        # 3. Descrição / Legenda
        desc = exif_info.get("description")
        if desc:
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = desc.encode("utf-8")
            modified = True

        if modified:
            exif_bytes = piexif.dump(exif_dict)
            output = io.BytesIO()
            piexif.insert(exif_bytes, file_bytes, output)
            return output.getvalue()

    except Exception:
        pass

    return file_bytes


def inject_media_metadata(file_bytes: bytes, asset_info: Dict[str, Any], filename: str) -> bytes:
    """
    Roteador inteligente: aplica injeção de data/hora dependendo do tipo de arquivo (foto ou vídeo).
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".mp4", ".mov", ".3gp", ".m4v"):
        return inject_video_metadata(file_bytes, asset_info)
    elif ext in (".jpg", ".jpeg", ".tiff", ".tif", ".webp"):
        return inject_exif_metadata(file_bytes, asset_info)
    return file_bytes
