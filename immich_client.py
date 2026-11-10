import requests
from typing import List, Dict, Any, Generator, Optional
from urllib.parse import urljoin


class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            self.base_url = f"http://{self.base_url}"
        
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": self.api_key,
            "Accept": "application/json"
        })

    def _url(self, path: str) -> str:
        # Handles paths starting with or without /
        path = path.lstrip("/")
        return f"{self.base_url}/api/{path}"

    def ping(self) -> Dict[str, Any]:
        """Testa conexão e retorna informações do servidor e do usuário."""
        # 1. Obter usuário logado
        user_res = self.session.get(self._url("users/me"), timeout=10)
        user_res.raise_for_status()
        user_data = user_res.json()

        # 2. Obter versão do servidor
        version = "desconhecida"
        try:
            ver_res = self.session.get(self._url("server/version"), timeout=5)
            if ver_res.status_code == 200:
                version = ver_res.json().get("major", "")
                version = f"{ver_res.json().get('major')}.{ver_res.json().get('minor')}.{ver_res.json().get('patch')}"
        except Exception:
            try:
                ver_res = self.session.get(self._url("server-info/version"), timeout=5)
                if ver_res.status_code == 200:
                    v_data = ver_res.json()
                    version = f"{v_data.get('major')}.{v_data.get('minor')}.{v_data.get('patch')}"
            except Exception:
                pass

        return {
            "user_email": user_data.get("email"),
            "user_name": user_data.get("name"),
            "user_id": user_data.get("id"),
            "server_version": version
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Obtém contagem total de fotos e vídeos no Immich."""
        try:
            res = self.session.get(self._url("server/statistics"), timeout=10)
            if res.status_code == 200:
                data = res.json()
                photos = data.get("photos", 0)
                videos = data.get("videos", 0)
                return {
                    "photos": photos,
                    "videos": videos,
                    "total": photos + videos
                }
        except Exception:
            pass
        return {"photos": 0, "videos": 0, "total": 0}


    def get_all_albums(self) -> List[Dict[str, Any]]:
        """Retorna todos os álbuns da conta do usuário."""
        res = self.session.get(self._url("albums"), timeout=30)
        res.raise_for_status()
        return res.json()

    def get_album_details(self, album_id: str) -> Dict[str, Any]:
        """Obtém detalhes do álbum, incluindo a lista de assets nele contidos."""
        res = self.session.get(self._url(f"albums/{album_id}"), timeout=30)
        res.raise_for_status()
        return res.json()

    def get_all_assets(self, page_size: int = 250) -> Generator[Dict[str, Any], None, None]:
        """
        Gera todos os assets do usuário usando paginação.
        Tenta POST /search/metadata e fallback para GET /assets.
        """
        # Tentativa 1: Endpoint de busca de metadados
        page = 1
        has_more = True
        
        while has_more:
            payload = {
                "size": page_size,
                "page": page,
                "isVisible": True
            }
            res = self.session.post(self._url("search/metadata"), json=payload, timeout=60)
            if res.status_code == 200:
                data = res.json()
                # A resposta pode ser { assets: { items: [...] } } ou { items: [...] } ou uma lista direta [...]
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    if "assets" in data and isinstance(data["assets"], dict):
                        items = data["assets"].get("items", [])
                    elif "items" in data:
                        items = data.get("items", [])
                    elif "assets" in data and isinstance(data["assets"], list):
                        items = data["assets"]

                if not items:
                    break

                for item in items:
                    yield item

                if len(items) < page_size:
                    has_more = False
                else:
                    page += 1
            else:
                # Se /search/metadata falhar (ex: versão mais antiga), tenta fallback para GET /assets
                fallback_res = self.session.get(self._url("assets"), timeout=60)
                fallback_res.raise_for_status()
                all_items = fallback_res.json()
                for item in all_items:
                    yield item
                break

    def download_asset_bytes(self, asset_id: str) -> bytes:
        """Baixa o arquivo binário original do asset."""
        # Tenta /assets/{id}/original
        url = self._url(f"assets/{asset_id}/original")
        res = self.session.get(url, stream=True, timeout=120)
        
        if res.status_code == 404:
            # Fallback para rotas legadas
            url = self._url(f"asset/download/{asset_id}")
            res = self.session.get(url, stream=True, timeout=120)

        res.raise_for_status()
        return res.content

