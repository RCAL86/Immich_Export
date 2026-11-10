import os
import json
import time
import random
from typing import Optional, List, Dict, Any, Callable
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Escopo restrito oficial do Google para criar mídias e álbuns
SCOPES = ["https://www.googleapis.com/auth/photoslibrary.appendonly"]
TOKEN_FILE = "token.json"


class GooglePhotosClient:
    def __init__(self, credentials_file: str = "credentials.json", log_fn: Optional[Callable[[str], None]] = None):
        self.credentials_file = credentials_file
        self.log_fn = log_fn or print
        self.creds: Optional[Credentials] = None
        self._authenticate()

    def _log(self, msg: str):
        if self.log_fn:
            self.log_fn(msg)

    def _authenticate(self):
        """Autentica o usuário via OAuth2 e armazena o token de atualização em token.json."""
        if os.path.exists(TOKEN_FILE):
            self.creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Arquivo de credenciais '{self.credentials_file}' não encontrado! "
                        "Baixe-o no Google Cloud Console conforme as instruções do README."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, SCOPES)
                self.creds = flow.run_local_server(port=0)

            # Salva o token para as próximas execuções
            with open(TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(self.creds.to_json())

    def _get_auth_header(self) -> Dict[str, str]:
        """Garante token válido e retorna o cabeçalho Authorization."""
        if self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
        return {"Authorization": f"Bearer {self.creds.token}"}

    def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 6,
        initial_backoff: float = 15.0,
        **kwargs
    ) -> requests.Response:
        """
        Executa requisição HTTP com backoff exponencial automático para tratar erros 429 (Too Many Requests).
        """
        backoff = initial_backoff
        for attempt in range(1, max_retries + 1):
            headers = self._get_auth_header()
            if "headers" in kwargs:
                req_headers = kwargs["headers"].copy()
                req_headers.update(headers)
            else:
                req_headers = headers

            req_kwargs = kwargs.copy()
            req_kwargs["headers"] = req_headers

            res = requests.request(method, url, **req_kwargs)

            # Se for 429 (Too Many Requests) ou 503 (Service Unavailable)
            if res.status_code == 429 or res.status_code >= 500:
                error_msg = ""
                try:
                    err_json = res.json()
                    error_msg = err_json.get("error", {}).get("message", "")
                except Exception:
                    error_msg = res.text[:200]

                if attempt == max_retries:
                    self._log(f"❌ Limite de tentativas atingido ({max_retries}) para {url}: {error_msg}")
                    res.raise_for_status()

                # Verifica se o Google enviou o cabeçalho Retry-After
                retry_after = res.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_seconds = float(retry_after) + 1.0
                    except ValueError:
                        wait_seconds = backoff
                else:
                    wait_seconds = backoff + random.uniform(1.0, 3.0)

                self._log(
                    f"⏳ [Google 429] Limite de requisições por minuto atingido. "
                    f"Aguardando {int(wait_seconds)}s antes de tentar novamente (Tentativa {attempt}/{max_retries})..."
                )
                time.sleep(wait_seconds)
                backoff = min(backoff * 2, 90.0)
                continue

            res.raise_for_status()
            return res

        return res

    def create_album(self, title: str) -> str:
        """Cria um novo álbum no Google Fotos e retorna seu albumId."""
        headers = {"Content-Type": "application/json"}
        payload = {
            "album": {
                "title": title
            }
        }
        res = self._request_with_retry(
            "POST",
            "https://photoslibrary.googleapis.com/v1/albums",
            headers=headers,
            json=payload,
            timeout=30
        )
        data = res.json()
        return data["id"]

    def upload_bytes(self, file_bytes: bytes, filename: str) -> str:
        """
        Envia os bytes brutos da foto/vídeo para o endpoint de upload do Google Photos.
        Retorna o upload_token para ser usado na criação do item de mídia.
        """
        headers = {
            "Content-type": "application/octet-stream",
            "X-Goog-Upload-Protocol": "raw",
            "X-Goog-Upload-File-Name": filename
        }

        res = self._request_with_retry(
            "POST",
            "https://photoslibrary.googleapis.com/v1/uploads",
            headers=headers,
            data=file_bytes,
            timeout=300
        )
        return res.text.strip()

    def batch_create_media_item(
        self,
        upload_token: str,
        filename: str,
        description: str = "",
        album_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Finaliza o registro do item enviado no Google Fotos, vinculando-o à biblioteca
        e opcionalmente a um álbum.
        """
        headers = {"Content-Type": "application/json"}
        new_media_item = {
            "simpleMediaItem": {
                "uploadToken": upload_token,
                "fileName": filename
            }
        }
        if description:
            new_media_item["description"] = description

        payload: Dict[str, Any] = {
            "newMediaItems": [new_media_item]
        }
        if album_id:
            payload["albumId"] = album_id

        res = self._request_with_retry(
            "POST",
            "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
            headers=headers,
            json=payload,
            timeout=60
        )
        result_json = res.json()
        results = result_json.get("newMediaItemResults", [])
        if results:
            first_res = results[0]
            status = first_res.get("status", {})
            if "message" in status and status["message"].lower() not in ["success", "ok", ""]:
                raise RuntimeError(f"Erro ao registrar item no Google Fotos: {status.get('message')}")
            return first_res.get("mediaItem", {})
        return {}

    def add_media_to_album(self, album_id: str, media_item_ids: List[str]):
        """
        Adiciona itens de mídia a um álbum no Google Fotos em lotes de até 50.
        Em caso de erro 400 (ex: fotos/vídeos que o usuário apagou do Google Fotos),
        utiliza divisão recursiva (divide-and-conquer) para isolar e ignorar os IDs
        excluídos, garantindo que 100% dos itens válidos sejam vinculados ao álbum!
        """
        if not media_item_ids:
            return

        def _add_chunk(chunk: List[str]):
            if not chunk:
                return
            headers = {"Content-Type": "application/json"}
            payload = {"mediaItemIds": chunk}
            try:
                self._request_with_retry(
                    "POST",
                    f"https://photoslibrary.googleapis.com/v1/albums/{album_id}:batchAddMediaItems",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
            except requests.exceptions.HTTPError as e:
                # Se for 400 (contém item apagado do Google Fotos)
                if e.response is not None and e.response.status_code == 400:
                    if len(chunk) == 1:
                        # Este item foi deletado pelo usuário do Google Fotos, ignora
                        return
                    time.sleep(0.5)
                    mid = len(chunk) // 2
                    _add_chunk(chunk[:mid])
                    _add_chunk(chunk[mid:])
                else:
                    raise e

        batch_size = 50
        for i in range(0, len(media_item_ids), batch_size):
            batch = media_item_ids[i:i + batch_size]
            _add_chunk(batch)
            if len(media_item_ids) > batch_size:
                time.sleep(1.0)




