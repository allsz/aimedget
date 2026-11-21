import asyncio
import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import DataReader, Buffer, InputStreamOptions
from app.core.paths import get_app_data_dir
from app.services.repeat_modes import gsmtc_to_ui, ui_to_gsmtc
from app.services.session_selection import SessionCandidate, pick_session

# Cache persistente em memória para capas otimizadas (500x500 / 600x600)
_HD_ART_CACHE: dict[str, bytes] = {}
# Cache persistente de extras para a skin Capa Empilhada: track_key -> (album_title, [cover2_bytes, cover3_bytes])
_STACK_EXTRAS_CACHE: dict[str, tuple[str, list[bytes]]] = {}
# Cache por artista para evitar re-downloads na troca de músicas do mesmo artista
_ARTIST_COVERS_CACHE: dict[str, list[bytes]] = {}

# Identificadores de players de música nativos, locais e dedicados
KNOWN_MUSIC_PLAYERS = (
    # Streaming apps
    "spotify", "applemusic", "apple.music", "itunes", "deezer", "tidal", "amazonmusic", "amazon music", "qobuz",
    # Players locais do Windows (Groove, novo Windows Media Player, clássico wmplayer)
    "microsoft.zunemusic", "microsoft.media.player", "windows.media.player", "wmplayer",
    # Players locais de alta fidelidade e clássicos
    "foobar2000", "aimp", "musicbee", "winamp", "dopamine", "clementine", "strawberry",
    "audacious", "mediamonkey", "resonic", "vlc", "potplayer", "mpc-hc", "mpc-be"
)

# Extensões de arquivos de áudio locais
AUDIO_EXTENSIONS = (
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma",
    ".alac", ".aiff", ".dsd", ".ape", ".wv", ".mid", ".midi"
)

# Extensão de áudio como extensão de verdade (ponto + nome inteiro): ".apex" e ".middle" não contam como ".ape"/".mid"
_AUDIO_EXT_RE = re.compile(
    r"\.(?:" + "|".join(re.escape(e[1:]) for e in AUDIO_EXTENSIONS) + r")(?![a-z0-9])", re.IGNORECASE
)
# Título no formato "Artista - Título" (travessão com espaços dos dois lados)
_ARTIST_TITLE_RE = re.compile(r"\S\s[-–—]\s\S")

# Navegadores web
BROWSER_APP_IDS = (
    "chrome", "msedge", "firefox", "brave", "opera", "operagx", "vivaldi", "zen", "arc", "waterfox", "tor"
)

# PWAs e wrappers dedicados a streaming de música
MUSIC_PWA_IDS = (
    "cinhimbnkkghhklpknlkffjgod",  # YouTube Music PWA (Chrome)
    "music.youtube",
    "youtube-music",
    "youtubemusic",
    "soundcloud",
    "tidal.desktop",
    "deezer.desktop",
)

# O Firefox se registra no GSMTC com um AUMID em hash (16 hex), sem o nome do navegador
_FIREFOX_HASH_AUMID = re.compile(r"[0-9a-f]{16}")

def timeline_signature(tl) -> tuple:
    """Identidade de um dado de posição do GSMTC: muda sempre que o player manda uma posição nova."""
    upd = getattr(tl, "last_updated_time", None)
    return (
        round(tl.position.total_seconds(), 3),
        round((tl.end_time - tl.start_time).total_seconds(), 3),
        upd.timestamp() if upd is not None and getattr(upd, "year", 0) >= 2000 else None,
    )


def resolve_track_timeline(sig: tuple, stale_sig: tuple | None, pos: float, dur: float):
    """
    O Firefox troca o título antes da posição: por até ~10 s a faixa nova chega com a posição e a duração da
    ANTERIOR (e com um carimbo de tempo velho, que faria a barra nascer adiantada). `stale_sig` é o último dado
    de posição visto antes da troca de faixa; enquanto o player repetir esse mesmo dado, ele é tratado como
    "ainda não chegou": posição 0 e duração 0 (desconhecida). Devolve (pos, dur, stale_sig a manter).
    """
    if stale_sig is not None and sig == stale_sig:
        return 0.0, 0.0, stale_sig
    return pos, dur, None


def is_browser_app_id(app_id: str) -> bool:
    """AUMID pertence a um navegador? Inclui o Firefox, cujo AUMID é só um hash."""
    a = (app_id or "").strip().lower()
    return bool(_FIREFOX_HASH_AUMID.fullmatch(a)) or any(b in a for b in BROWSER_APP_IDS)


# Termos que denunciam imediatamente vídeos comuns (gameplay, vlogs, notícias, etc.)
NON_MUSIC_PATTERNS = re.compile(
    r"\b(gameplay|walkthrough|playthrough|tutorial|review|unboxing|podcast|"
    r"episódio|episodio|notícia|noticia|react|vídeo novo|video novo|"
    r"ao vivo -|aula \d|curso \d|cortes do|highlights|vlog|vlogs)\b|"
    r"k{4,}|h{4,}|kkk\b",
    re.IGNORECASE,
)


def _get_disk_cache_dir() -> str:
    """Retorna o diretório de cache persistente em disco (%LOCALAPPDATA%/Aimedget/cover_cache)."""
    cache_dir = os.path.join(get_app_data_dir(), "cover_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _track_hash(key: str) -> str:
    return hashlib.sha1(key.lower().strip().encode("utf-8", errors="ignore")).hexdigest()[:20]


def _load_cover_from_disk(track_key: str) -> bytes:
    """Carrega a capa principal do cache em disco em < 1ms se já tiver sido baixada antes."""
    try:
        path = os.path.join(_get_disk_cache_dir(), f"cov_{_track_hash(track_key)}.img")
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            if len(data) > 1024:
                return data
    except Exception:
        pass
    return b""


def _save_cover_to_disk(track_key: str, data: bytes):
    """Salva a capa principal no disco para carregamento instantâneo em sessões futuras."""
    if not data or len(data) <= 1024:
        return
    try:
        path = os.path.join(_get_disk_cache_dir(), f"cov_{_track_hash(track_key)}.img")
        with open(path, "wb") as f:
            f.write(data)
    except Exception:
        pass


# ── Capas por álbum ──────────────────────────────────────────────────────────────────────────────────────────────
# As faixas de um mesmo álbum dividem a capa: a imagem fica guardada UMA vez, sob a chave do álbum, e cada faixa
# (ou etiqueta de álbum do player) só guarda um apontamento para ela. Chaves de álbum, da mais certeira à menos:
#   "deezer:<id>" / "itunes:<id>"  → identidade vinda da busca online
#   "tag:<álbum>|<artista>"        → etiquetas que o próprio player informa (dá para consultar antes de ir à rede)
_ALBUM_ART_CACHE: dict[str, bytes] = {}   # chave do álbum -> bytes da capa
_ALBUM_LINKS: dict[str, str] = {}         # faixa ("título|artista") ou etiqueta -> chave do álbum

_UNKNOWN_ARTISTS = ("", "artista desconhecido", "unknown artist", "youtube")


def album_tag_key(album: str, album_artist: str, artist: str = "") -> str:
    """Chave do álbum a partir das etiquetas do player; vazia quando não há álbum ou artista confiável."""
    alb = " ".join((album or "").split()).lower()
    who = " ".join((album_artist or artist or "").split()).lower()
    if not alb or who in _UNKNOWN_ARTISTS:
        return ""
    return f"tag:{alb}|{who}"


def _link_path(alias: str) -> str:
    return os.path.join(_get_disk_cache_dir(), f"lnk_{_track_hash(alias)}.txt")


def _album_path(album_key: str) -> str:
    return os.path.join(_get_disk_cache_dir(), f"alb_{_track_hash(album_key)}.img")


def _album_cover(album_key: str) -> bytes:
    """Capa do álbum em memória ou disco (vazio se nunca foi guardada)."""
    if not album_key:
        return b""
    data = _ALBUM_ART_CACHE.get(album_key)
    if data:
        return data
    try:
        path = _album_path(album_key)
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            if len(data) > 1024:
                _ALBUM_ART_CACHE[album_key] = data
                return data
    except Exception:
        pass
    return b""


def _album_for(alias: str) -> str:
    """Chave do álbum para a qual uma faixa/etiqueta aponta (memória ou disco)."""
    if not alias:
        return ""
    key = _ALBUM_LINKS.get(alias)
    if key:
        return key
    try:
        path = _link_path(alias)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                _ALBUM_LINKS[alias] = key
                return key
    except Exception:
        pass
    return ""


def _link(alias: str, album_key: str):
    if not alias or not album_key or alias == album_key or _ALBUM_LINKS.get(alias) == album_key:
        return
    _ALBUM_LINKS[alias] = album_key
    try:
        with open(_link_path(alias), "w", encoding="utf-8") as f:
            f.write(album_key)
    except Exception:
        pass


def store_album_cover(album_key: str, data: bytes, aliases=()):
    """Guarda a capa uma vez sob `album_key` e aponta cada alias (faixa, etiqueta) para ela."""
    if not album_key or not data or len(data) <= 1024:
        return
    if _ALBUM_ART_CACHE.get(album_key) != data:
        _ALBUM_ART_CACHE[album_key] = data
        try:
            with open(_album_path(album_key), "wb") as f:
                f.write(data)
        except Exception:
            pass
    for alias in aliases:
        _link(alias, album_key)


def cached_cover(track_key: str, tag_key: str = "") -> bytes:
    """
    Capa já conhecida para a faixa, sem rede: faixa em memória → álbum pelas etiquetas do player → álbum para o
    qual a faixa aponta → capa antiga por faixa (cache de versões anteriores).
    """
    data = _HD_ART_CACHE.get(track_key)
    if data:
        return data
    for alias in (tag_key, track_key):
        album_key = alias if alias.startswith("tag:") and _album_cover(alias) else _album_for(alias)
        data = _album_cover(album_key)
        if data:
            _HD_ART_CACHE[track_key] = data
            if tag_key and alias != tag_key:
                _link(tag_key, album_key)
            return data
    data = _load_cover_from_disk(track_key)
    if data:
        _HD_ART_CACHE[track_key] = data
    return data


# Capa que o worker já confirmou como sendo da faixa atual (cache, capa nativa travada ou busca online).
# Duas faixas do mesmo álbum mandam bytes idênticos; sem isso a UI confunde a capa certa com a "capa velha" da
# faixa anterior que o navegador às vezes repete logo após a troca.
_CONFIRMED_COVER: tuple[str, bytes] = ("", b"")


def confirm_cover(track_key: str, data: bytes):
    global _CONFIRMED_COVER
    if track_key and data:
        _CONFIRMED_COVER = (track_key, data)


def cover_confirmed_for(title: str, artist: str, data: bytes) -> bool:
    """A capa `data` foi confirmada pelo worker para esta faixa (e não é sobra da anterior)?"""
    key, confirmed = _CONFIRMED_COVER
    return bool(data) and key == f"{title}|{artist}" and confirmed == data


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=2.5) as resp:
        data = resp.read()
    return data if len(data) > 1024 else b""


def _load_extras_from_disk(track_key: str) -> tuple[str, list[bytes]] | None:
    """Carrega metadados de álbum e capas secundárias da pilha diretamente do disco."""
    try:
        cache_dir = _get_disk_cache_dir()
        h = _track_hash(track_key)
        meta_path = os.path.join(cache_dir, f"ext_{h}.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        album_name = meta.get("album", "")
        count = int(meta.get("count", 0))
        extras: list[bytes] = []
        for i in range(count):
            img_path = os.path.join(cache_dir, f"ext_{h}_{i}.img")
            if os.path.exists(img_path):
                with open(img_path, "rb") as img_f:
                    b = img_f.read()
                    if len(b) > 512:
                        extras.append(b)
        if album_name or extras:
            return (album_name, extras)
    except Exception:
        pass
    return None


def _save_extras_to_disk(track_key: str, album_name: str, extras: list[bytes]):
    """Salva o nome do álbum e as capas secundárias da pilha em disco."""
    try:
        cache_dir = _get_disk_cache_dir()
        h = _track_hash(track_key)
        saved_count = 0
        for i, b in enumerate(extras[:2]):
            if b and len(b) > 512:
                img_path = os.path.join(cache_dir, f"ext_{h}_{i}.img")
                with open(img_path, "wb") as img_f:
                    img_f.write(b)
                saved_count += 1
        meta_path = os.path.join(cache_dir, f"ext_{h}.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"album": album_name, "count": saved_count}, f, ensure_ascii=False)
    except Exception:
        pass


def is_browser_logo_thumbnail(thumb_bytes: bytes) -> bool:
    """Detecta se o thumbnail enviado pelo Windows é o logotipo do navegador."""
    if not thumb_bytes:
        return False
    img = QImage.fromData(thumb_bytes)
    if img.isNull() or img.width() < 24 or img.height() < 24:
        return False

    b_cnt, r_cnt, g_cnt, y_cnt = 0, 0, 0, 0
    step = max(1, img.width() // 40)
    samples = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            samples += 1
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if b > 160 and r < 100 and g < 170:
                b_cnt += 1
            elif r > 170 and g < 90 and b < 90:
                r_cnt += 1
            elif g > 130 and r < 80 and b < 110:
                g_cnt += 1
            elif r > 200 and g > 170 and b < 90:
                y_cnt += 1

    if samples == 0:
        return False
    return (
        (b_cnt / samples > 0.03)
        and (r_cnt / samples > 0.04)
        and (g_cnt / samples > 0.04)
        and (y_cnt / samples > 0.04)
    )


def _clean_metadata_for_search(title: str, artist: str) -> tuple[str, str]:
    """Limpa metadados de vídeo/YouTube para busca exata de capa oficial em HD."""
    clean_t = title or ""
    clean_t = re.sub(
        r"[\(\[][^)\]]*(?:official|video|audio|lyric|visualizer|clipe|ao vivo|live|hd|4k|remaster|explicit)[^)\]]*[\)\]]",
        "",
        clean_t,
        flags=re.IGNORECASE,
    )
    clean_t = re.sub(r"\b(?:ft\.?|feat\.?|featuring)\b.*$", "", clean_t, flags=re.IGNORECASE).strip()
    clean_t = clean_t.strip(" -|")

    clean_a = artist or ""
    clean_a = re.sub(r"\s*-\s*Topic$", "", clean_a, flags=re.IGNORECASE)
    clean_a = re.sub(r"VEVO$", "", clean_a, flags=re.IGNORECASE)
    clean_a = re.split(r"[;,/]", clean_a)[0].strip()

    if " - " in clean_t and (not clean_a or clean_a.lower() in ("artista desconhecido", "youtube")):
        parts = clean_t.split(" - ", 1)
        clean_a = parts[0].strip()
        clean_t = parts[1].strip()

    return clean_t, clean_a


def _resolve_album(album_key: str, cover_url: str, track_key: str, tag_key: str) -> bytes:
    """Capa do álbum achado na busca: reaproveita a já guardada (sem baixar) ou baixa uma vez e guarda."""
    data = _album_cover(album_key)
    if not data:
        data = _download(cover_url)
    if data:
        store_album_cover(album_key, data, aliases=(track_key, tag_key))
        _HD_ART_CACHE[track_key] = data
    return data


def fetch_online_album_art(title: str, artist: str, tag_key: str = "") -> bytes:
    """
    Busca automaticamente a capa oficial otimizada para o tamanho do widget (500x500 / 600x600)
    via Deezer API (cover_big) e iTunes Search API (600x600bb). A capa é guardada por álbum: as outras faixas
    do mesmo álbum só fazem a busca de texto e reaproveitam a imagem já baixada.
    """
    track_key = f"{title}|{artist}"
    known = cached_cover(track_key, tag_key)
    if known:
        return known

    clean_title, clean_artist = _clean_metadata_for_search(title, artist)
    if not clean_title or clean_title.lower() in ("sem título", "nenhuma mídia ativa", "main theme"):
        return b""

    if clean_artist.lower() in ("artista desconhecido", "o que vamos ouvir hoje?", "md studio"):
        clean_artist = ""

    query = f"{clean_title} {clean_artist}".strip()
    if not query:
        return b""

    # 1. Deezer API (cover_big = 500x500px -> ~12x mais leve e nitidez 100% idêntica no widget)
    try:
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(query)}&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("data", [])
            if items:
                album_obj = items[0].get("album", {})
                cover_url = (
                    album_obj.get("cover_big")
                    or album_obj.get("cover_medium")
                    or album_obj.get("cover_xl")
                )
                if cover_url:
                    # Sem id do álbum, a própria URL da capa identifica a imagem
                    album_key = f"deezer:{album_obj.get('id') or cover_url}"
                    img_bytes = _resolve_album(album_key, cover_url, track_key, tag_key)
                    if img_bytes:
                        return img_bytes
    except Exception:
        pass

    # 2. iTunes Search API (600x600bb)
    try:
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("resultCount", 0) > 0:
                first = data["results"][0]
                art_100 = first.get("artworkUrl100", "")
                if art_100:
                    cover_url = art_100.replace("100x100bb", "600x600bb")
                    album_key = f"itunes:{first.get('collectionId') or cover_url}"
                    img_bytes = _resolve_album(album_key, cover_url, track_key, tag_key)
                    if img_bytes:
                        return img_bytes
    except Exception:
        pass

    return b""


def fetch_stack_extras(title: str, artist: str) -> tuple[str, list[bytes]]:
    """
    Obtém o nome do álbum e até 2 capas adicionais distintas do mesmo artista/busca
    para compor a pilha visual da skin Capa Empilhada (com cache em memória, artista e disco).
    """
    track_key = f"{title}|{artist}"
    if track_key in _STACK_EXTRAS_CACHE:
        return _STACK_EXTRAS_CACHE[track_key]

    disk_extras = _load_extras_from_disk(track_key)
    if disk_extras is not None:
        _STACK_EXTRAS_CACHE[track_key] = disk_extras
        return disk_extras

    clean_title, clean_artist = _clean_metadata_for_search(title, artist)
    if not clean_title or clean_title.lower() in ("sem título", "nenhuma mídia ativa", "main theme"):
        return "", []

    if clean_artist.lower() in ("artista desconhecido", "o que vamos ouvir hoje?", "md studio"):
        clean_artist = ""

    query = f"{clean_title} {clean_artist}".strip()
    if not query:
        return "", []

    album_name = ""
    extra_covers: list[bytes] = []
    seen_urls: set[str] = set()

    # Se já temos capas extras cacheadas para este mesmo artista, reaproveita imediatamente
    artist_key = clean_artist.lower().strip()
    cached_artist_covers = _ARTIST_COVERS_CACHE.get(artist_key, []) if artist_key else []

    try:
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(query)}&limit=8"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("data", [])
            for idx, item in enumerate(items):
                alb = item.get("album", {})
                if idx == 0:
                    album_name = (alb.get("title") or "").strip()
                    first_url = alb.get("cover_medium") or alb.get("cover_big") or ""
                    if first_url:
                        seen_urls.add(first_url)
                    if len(cached_artist_covers) >= 2:
                        extra_covers = list(cached_artist_covers[:2])
                        break
                else:
                    # Usa cover_medium (250x250) para as capas de fundo da pilha (exibidas em ~158px na tela)
                    c_url = alb.get("cover_medium") or alb.get("cover_big") or ""
                    if c_url and c_url not in seen_urls:
                        seen_urls.add(c_url)
                        with urllib.request.urlopen(c_url, timeout=2.0) as c_resp:
                            b_data = c_resp.read()
                            if len(b_data) > 512:
                                extra_covers.append(b_data)
                                if len(extra_covers) >= 2:
                                    break
    except Exception:
        pass

    # Se ainda faltam capas secundárias do artista, busca pelo nome do artista
    if len(extra_covers) < 2 and clean_artist:
        try:
            url = f"https://api.deezer.com/search?q={urllib.parse.quote(clean_artist)}&limit=10"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode())
                for item in data.get("data", []):
                    alb = item.get("album", {})
                    c_url = alb.get("cover_medium") or alb.get("cover_big") or ""
                    if c_url and c_url not in seen_urls:
                        seen_urls.add(c_url)
                        with urllib.request.urlopen(c_url, timeout=2.0) as c_resp:
                            b_data = c_resp.read()
                            if len(b_data) > 512:
                                extra_covers.append(b_data)
                                if len(extra_covers) >= 2:
                                    break
        except Exception:
            pass

    if artist_key and len(extra_covers) >= 2:
        _ARTIST_COVERS_CACHE[artist_key] = list(extra_covers[:2])

    result = (album_name, extra_covers)
    if album_name or extra_covers:
        _STACK_EXTRAS_CACHE[track_key] = result
        _save_extras_to_disk(track_key, album_name, extra_covers)
    return result


def detect_provider(app_id: str, title: str, artist: str, album: str = "") -> str:
    """Identifica o provedor de streaming ativo."""
    app_lower = (app_id or "").lower()
    title_lower = (title or "").lower()

    if (
        "cinhimbnkkghhklpknlkffjgod" in app_lower
        or "youtubemusic" in app_lower
        or "youtube-music" in app_lower
        or "youtube music" in app_lower
        or "youtube music" in title_lower
        or "music.youtube" in app_lower
    ):
        return "youtube_music"

    if "spotify" in app_lower or "spotify" in title_lower:
        return "spotify"

    if "applemusic" in app_lower or "apple.music" in app_lower or "itunes" in app_lower:
        return "apple_music"

    if "deezer" in app_lower:
        return "deezer"

    if "tidal" in app_lower:
        return "tidal"

    if "amazonmusic" in app_lower or "amazon music" in app_lower:
        return "amazon_music"

    if "soundcloud" in app_lower or "soundcloud" in title_lower:
        return "soundcloud"

    return "generic"


# --- Diagnóstico da detecção (só com AIMEDGET_MEDIA_DIAG=1) ------------------------------------------------------
# Registra o que cada sessão de mídia do Windows manda (app id, título, artista, álbum, tipo, capa) e como o
# classificador a tratou, para decidir as regras do filtro com dados reais. Desligado por padrão: não custa nada.
_DIAG_ENABLED = os.environ.get("AIMEDGET_MEDIA_DIAG", "").strip() in ("1", "true", "yes")
_DIAG_MAX_BYTES = 2_000_000
_diag_last: dict[str, tuple] = {}


def _diag_path() -> str:
    return os.path.join(get_app_data_dir(), "media_diagnostic.jsonl")


def _diag_record(session, props, info, thumb_bytes: bytes, result: tuple):
    """Acrescenta uma linha JSON por MUDANÇA de estado de cada sessão (sem repetir a cada ciclo)."""
    if not _DIAG_ENABLED or not session:
        return
    try:
        def safe(getter, default=None):
            try:
                value = getter()
                return default if value is None else value
            except Exception:
                return default

        ptype = safe(lambda: info.playback_type)
        ptype = getattr(ptype, "name", ptype)
        aspect = None
        if thumb_bytes:
            img = QImage.fromData(thumb_bytes)
            if not img.isNull() and img.height() > 0:
                aspect = round(img.width() / img.height(), 3)
        app_id = (safe(lambda: session.source_app_user_model_id, "") or "")
        record = {
            "app_id": app_id,
            "is_browser": is_browser_app_id(app_id.lower()),
            "title": safe(lambda: props.title, ""),
            "artist": safe(lambda: props.artist, ""),
            "album": safe(lambda: props.album_title, ""),
            "album_artist": safe(lambda: props.album_artist, ""),
            "subtitle": safe(lambda: props.subtitle, ""),
            "track_number": safe(lambda: props.track_number, 0),
            "album_track_count": safe(lambda: props.album_track_count, 0),
            "playback_type": str(ptype) if ptype is not None else None,
            "status": _status_name(info) if info else "",
            "thumb_bytes": len(thumb_bytes or b""),
            "thumb_aspect": aspect,
            "is_music": result[0],
            "provider": result[1],
            "score": result[2],
            "auto_open": result[3] if len(result) > 3 else None,
        }
        sig = tuple(record[k] for k in ("title", "artist", "album", "playback_type", "status", "is_music", "provider", "score"))
        if _diag_last.get(app_id) == sig:
            return
        _diag_last[app_id] = sig
        record["time"] = datetime.datetime.now().isoformat(timespec="seconds")
        path = _diag_path()
        if os.path.exists(path) and os.path.getsize(path) > _DIAG_MAX_BYTES:
            os.remove(path)   # arquivo de diagnóstico: recomeça em vez de crescer sem limite
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass   # diagnóstico nunca pode derrubar a detecção


def _status_name(info) -> str:
    """Status de reprodução da sessão como texto estável para a lógica de seleção."""
    st = getattr(info, "playback_status", None)
    if st is None:
        return "other"
    if st == PlaybackStatus.PLAYING:
        return "playing"
    if st == getattr(PlaybackStatus, "CHANGING", object()):
        return "changing"
    if st == getattr(PlaybackStatus, "PAUSED", object()):
        return "paused"
    return "other"


class WindowsMediaWorker(QObject):
    """
    Worker em background que conversa com a API nativa do Windows (GSMTC):
    - Detecta Spotify, Chrome, Edge, YouTube Music, Apple Music, etc.
    - Sincroniza títulos, artistas, timeline e status de reprodução.
    - Atualiza instantaneamente a capa em Ultra-HD (1000x1000) com cache em memória.
    """
    media_updated = Signal(str, str, bool, float, float, bytes, str)
    # Modo de repetição real do player, na semântica da interface (0/1/2); -1 = não informado
    repeat_state_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self._running = True
        self._cmd_queue = []
        self._last_track_key = ""
        self._cached_thumb = b""
        self._last_gsmtc_raw = b""
        self._cand_thumb_cache: dict[str, tuple[tuple[str, str], bytes]] = {}
        self._prev_track_gsmtc_raw = b""
        self._track_changed_at = 0.0
        self._last_tl_sig: tuple | None = None    # último dado de posição recebido (ver resolve_track_timeline)
        self._stale_tl_sig: tuple | None = None   # dado da faixa anterior que ainda não foi substituído
        self._hd_cover_locked = False
        self._fetching_hd_for_key = ""
        self._no_session_since = 0.0
        # AUMID (minúsculo) do app que originou a mídia atual; usado para o volume por aplicativo
        self.current_source_app_id = ""
        # A sessão exibida pode abrir o widget sozinha? (False = nível C: aparece, mas só se o usuário abrir.)
        self.current_auto_open_ok = True
        # Estabilidade da escolha de sessão (ver session_selection.py)
        self._sticky_key: str | None = None
        self._sticky_ok_at = 0.0
        self._last_repeat_ui = -2

        # Último estado emitido para repasse imediato quando a capa HD chegar
        self._last_title = ""
        self._last_artist = ""
        self._last_is_playing = False
        self._last_pos = 0.0
        self._last_dur = 0.0
        self._last_provider = "generic"

        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def send_command(self, action: str, value=None):
        self._cmd_queue.append((action, value))

    def stop(self, timeout: float = 3.0):
        """Sinaliza o fim e aguarda a thread (com limite) para não destruir WinRT/Qt em uso."""
        self._running = False
        t = getattr(self, "_thread", None)
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_loop())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    @staticmethod
    def _compute_real_position(tl, is_playing: bool) -> tuple[float, float]:
        start_sec = tl.start_time.total_seconds()
        end_sec = tl.end_time.total_seconds()
        dur = max(0.0, end_sec - start_sec)
        raw_pos = max(0.0, tl.position.total_seconds() - start_sec)

        pos = raw_pos
        last_upd = getattr(tl, "last_updated_time", None)
        if is_playing and last_upd is not None and getattr(last_upd, "year", 0) >= 2020:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (now_utc - last_upd).total_seconds()
            if 0.0 <= elapsed <= max(dur + 10.0, 7200.0):
                pos = raw_pos + elapsed

        if dur > 0.0:
            pos = max(0.0, min(dur, pos))
        return pos, dur

    @staticmethod
    async def _read_gsmtc_thumbnail(props) -> bytes:
        if not props or not props.thumbnail:
            return b""
        try:
            stream = await props.thumbnail.open_read_async()
            size = stream.size
            if size > 0:
                buf = Buffer(size)
                await stream.read_async(buf, size, InputStreamOptions.NONE)
                reader = DataReader.from_buffer(buf)
                raw = bytearray(size)
                reader.read_bytes(raw)
                return bytes(raw)
        except Exception:
            pass
        return b""

    async def _candidate_thumbnail(self, key: str, props) -> bytes:
        """
        Thumbnail de uma sessão candidata de navegador (a classificação não usa a capa: serve ao diagnóstico e a
        pré-carrega para a sessão escolhida). Nos demais players devolve b"" (a capa da sessão escolhida é lida mais
        adiante, e só se ainda não estiver travada em cache).
        Em navegadores, a leitura (cara) é reaproveitada enquanto a faixa não muda.
        """
        if not is_browser_app_id(key):
            return b""
        track = (
            (getattr(props, "title", "") or "").strip(),
            (getattr(props, "artist", "") or "").strip(),
        )
        cached = self._cand_thumb_cache.get(key)
        if cached and cached[0] == track:
            return cached[1]
        raw = await self._read_gsmtc_thumbnail(props)
        if raw:  # vazio = a capa pode ainda não ter chegado; tenta de novo no próximo ciclo
            self._cand_thumb_cache[key] = (track, raw)
        else:
            self._cand_thumb_cache.pop(key, None)
        return raw

    @staticmethod
    def _is_low_res_or_cropped(thumb_bytes: bytes) -> bool:
        """
        Verifica se a imagem é menor que 280px (ex: ícone pequeno) ou se possui formato 16:9 de vídeo.
        Capas quadradas nativas do Spotify/Apple Music/Deezer (>= 300x300) já são aceitas sem busca extra!
        """
        if not thumb_bytes:
            return True
        img = QImage.fromData(thumb_bytes)
        if img.isNull():
            return True
        w, h = img.width(), img.height()
        if w < 280 or h < 280:
            return True
        aspect = w / max(1, h)
        if aspect > 1.15 or aspect < 0.85:
            return True
        return False

    @staticmethod
    def _is_video_frame(thumb_bytes: bytes) -> bool:
        """Imagem retangular (ex.: miniatura 16:9 de vídeo do YouTube), em vez de capa quadrada de álbum."""
        img = QImage.fromData(thumb_bytes) if thumb_bytes else QImage()
        if img.isNull() or img.height() <= 0:
            return False
        aspect = img.width() / img.height()
        return aspect > 1.25 or aspect < 0.8

    def _classify_session(
        self,
        session,
        props,
        info,
    ) -> tuple[bool, str, int, bool]:
        """
        Classifica a sessão em: (é_música, provedor, pontuação_de_prioridade, abre_sozinho).

        `é_música` False = rejeitada (nunca aparece). `abre_sozinho` decide só a ABERTURA AUTOMÁTICA do widget:
        sessões ambíguas (True, ..., False) ainda aparecem se o usuário abrir o widget, mas não o abrem sozinhas.

        Níveis:
        - A (abre sozinho): players de streaming e locais conhecidos, PWAs de música conhecidos, arquivos de áudio.
        - B (abre sozinho): navegador com sinal forte de música (álbum preenchido ou canal "- Topic") e arquivo
          local sem tags mas com título "Artista - Título".
        - C (não abre sozinho): o resto que vem de navegador/app instalado desconhecido (Work Adventure, Kick, Twitch,
          vídeos, SoundCloud na aba) e arquivo local sem nenhuma pista de música.

        A capa quadrada NÃO é sinal: Kick, Twitch, Spotify Web e YouTube Music mandam todos capa 1:1 (medido).
        """
        if not session or not props:
            return False, "generic", -1, False

        app_id = (session.source_app_user_model_id or "").lower()
        title = (getattr(props, "title", "") or "").strip()
        artist = (getattr(props, "artist", "") or "").strip()
        album = (getattr(props, "album_title", "") or "").strip()
        track_no = getattr(props, "track_number", 0) or 0
        is_playing = (info.playback_status == PlaybackStatus.PLAYING) if info else False
        play_bonus = 20 if is_playing else 0

        if not title or title.lower() in ("sem título", "nenhuma mídia ativa"):
            return False, "generic", -1, False

        has_tags = bool(artist or album or track_no > 0)
        looks_like_song = bool(_ARTIST_TITLE_RE.search(title))   # "Artista - Título"

        # 1. PWA dedicado de música conhecido (YouTube Music, ...). Um app instalado DESCONHECIDO (outro
        #    `Chrome._crx_<id>`, como o Work Adventure) não entra aqui: cai no nível C mais abaixo.
        if any(p in app_id for p in MUSIC_PWA_IDS) or "youtube music" in title.lower():
            return True, detect_provider(app_id, title, artist, album), 80 + play_bonus, True

        # 2. Players de streaming conhecidos (Spotify, Apple Music, Deezer, Tidal, etc.)
        streaming_players = (
            "spotify", "applemusic", "apple.music", "itunes", "deezer",
            "tidal", "amazonmusic", "amazon music", "qobuz"
        )
        if any(p in app_id for p in streaming_players):
            return True, detect_provider(app_id, title, artist, album), 90 + play_bonus, True

        # 3. Players locais de áudio do Windows (Groove, Media Player, Foobar, AIMP, MusicBee, Winamp...)
        #    O Media Player também toca VÍDEO e manda o mesmo tipo de dado (só título): sem tags e sem cara de
        #    "Artista - Título", não dá para saber se é música, então não abre sozinho.
        local_music_apps = (
            "microsoft.zunemusic", "microsoft.media.player", "windows.media.player", "wmplayer",
            "foobar2000", "aimp", "musicbee", "winamp", "dopamine", "clementine", "strawberry",
            "audacious", "mediamonkey", "resonic"
        )
        if any(p in app_id for p in local_music_apps):
            if has_tags or _AUDIO_EXT_RE.search(title):
                return True, "local", 85 + play_bonus, True
            if looks_like_song:
                return True, "local", 75 + play_bonus, True
            return True, "local", 45 + play_bonus, False

        # 4. Players multimídia mistos (VLC, PotPlayer, MPC)
        video_audio_players = ("vlc", "potplayer", "mpc-hc", "mpc-be")
        if any(p in app_id for p in video_audio_players):
            if _AUDIO_EXT_RE.search(title) or has_tags:
                return True, "local", 85 + play_bonus, True
            if title.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".wmv")):
                return False, "video_file", -1, False
            if looks_like_song:
                return True, "local", 70 + play_bonus, True
            return True, "local", 45 + play_bonus, False

        # 5. Arquivo com extensão de áudio explícita no título, em qualquer outro app
        if _AUDIO_EXT_RE.search(title):
            return True, "local", 85 + play_bonus, True

        # 6. Navegadores Web (Chrome, Edge, Firefox, Brave, Opera, etc.)
        if is_browser_app_id(app_id):
            # 6a. Descarte imediato: gameplay, react, vlog, podcast...
            if NON_MUSIC_PATTERNS.search(title):
                return False, "browser_video_rejected", -1, False

            # 6b. Artista é o próprio navegador e o título não tem o formato "Artista - Título"
            if artist.lower() in ("youtube", "google chrome", "chrome", "microsoft edge", "firefox", "navegador") and not looks_like_song:
                return False, "browser_video_rejected", -1, False

            # 6c. Canal oficial de música do YouTube (termina com "- Topic")
            if artist.endswith("- Topic"):
                return True, "youtube_music", 65 + play_bonus, True

            # 6d. Álbum preenchido: só players de música mandam isso (Spotify Web). Vídeo, live e rede social não.
            if album:
                return True, detect_provider(app_id, title, artist, album), 75 + play_bonus, True

            # 6e. Nível C: o navegador só informa título e canal, e nada separa de forma confiável um vídeo de
            #     música de Work Adventure, Kick, Twitch ou X. Aparece se o usuário abrir o widget, mas não abre
            #     sozinho. A capa é resolvida à parte (busca online; sem achar, a capa padrão, nunca o quadro).
            return True, "generic", 40 + play_bonus, False

        # Não é navegador nem player conhecido: só com tags completas de álbum e artista, e sem abrir sozinho.
        if album and artist and artist.lower() not in ("artista desconhecido", "youtube"):
            return True, "generic", 40 + play_bonus, False

        return False, "unknown", -1, False

    def _publish_repeat_state(self, info):
        """Informa a UI do modo de repetição REAL do player (ela não adivinha mais por contagem)."""
        try:
            ui_mode = gsmtc_to_ui(getattr(info, "auto_repeat_mode", None))
        except Exception:
            ui_mode = -1
        if ui_mode != self._last_repeat_ui:
            self._last_repeat_ui = ui_mode
            self.repeat_state_changed.emit(ui_mode)

    def _trigger_hd_fetch_async(self, track_key: str, title: str, artist: str, tag_key: str = ""):
        """Busca a capa oficial otimizada (500x500 / 600x600) em background e emite o sinal no instante em que chega."""
        if self._fetching_hd_for_key == track_key:
            return
        self._fetching_hd_for_key = track_key

        def _worker():
            hd_bytes = fetch_online_album_art(title, artist, tag_key)
            if not hd_bytes and " - " in title:
                # Vídeo de terceiros: o "artista" é o canal e o título vem como "Obra - Faixa"; tenta pelas partes
                left, _, right = title.partition(" - ")
                if left.strip() and right.strip():
                    hd_bytes = fetch_online_album_art(right.strip(), left.strip())
            if hd_bytes and self._last_track_key == track_key and not self._hd_cover_locked:
                _HD_ART_CACHE[track_key] = hd_bytes
                self._cached_thumb = hd_bytes
                self._hd_cover_locked = True
                confirm_cover(track_key, hd_bytes)
                print(f"[MediaWorker] Capa otimizada aplicada para: '{title}' ({len(hd_bytes)} bytes)")
                # Emite imediatamente para a UI atualizar sem esperar o próximo ciclo de loop
                self.media_updated.emit(
                    self._last_title or title,
                    self._last_artist or artist,
                    self._last_is_playing,
                    self._last_pos,
                    self._last_dur,
                    hd_bytes,
                    self._last_provider,
                )

        threading.Thread(target=_worker, daemon=True).start()

    async def _async_loop(self):
        mgr = None
        try:
            mgr = await SessionManager.request_async()
        except Exception:
            pass

        while self._running:
            try:
                if mgr is None:
                    mgr = await SessionManager.request_async()

                # Seleção Inteligente da melhor sessão de música ativa
                best_session = None
                best_props = None
                best_info = None
                best_provider = "generic"
                best_score = -1
                best_raw_thumb = b""

                sessions = []
                if mgr:
                    try:
                        sessions = list(mgr.get_sessions())
                    except Exception:
                        sessions = []

                now_sel = time.monotonic()
                candidates: list[SessionCandidate] = []
                for s in sessions:
                    key = ""
                    try:
                        key = (s.source_app_user_model_id or "").lower()
                        s_props = await s.try_get_media_properties_async()
                        s_info = s.get_playback_info()
                        s_thumb = await self._candidate_thumbnail(key, s_props)
                        is_m, p_name, score, auto_ok = self._classify_session(s, s_props, s_info)
                        _diag_record(s, s_props, s_info, s_thumb, (is_m, p_name, score, auto_ok))
                        candidates.append(
                            SessionCandidate(
                                key=key,
                                is_music=is_m,
                                score=score,
                                status=_status_name(s_info),
                                payload=(s, s_props, s_info, p_name, s_thumb, auto_ok),
                            )
                        )
                    except Exception:
                        if key:  # falha momentânea: a sessão continua existindo para a lógica de estabilidade
                            candidates.append(SessionCandidate(key=key, is_music=False, score=-1, status="other"))
                        continue

                if self._sticky_key and any(c.key == self._sticky_key and c.is_music for c in candidates):
                    self._sticky_ok_at = now_sel
                chosen, hold = pick_session(candidates, self._sticky_key, self._sticky_ok_at, now_sel)
                if chosen is not None and chosen.payload is not None:
                    best_session, best_props, best_info, best_provider, best_raw_thumb, best_auto_ok = chosen.payload
                    best_score = chosen.score
                    self.current_auto_open_ok = best_auto_ok
                    self._sticky_key = chosen.key
                    self._sticky_ok_at = now_sel
                elif not hold:
                    self._sticky_key = None

                session = best_session
                if session is not None:
                    try:
                        self.current_source_app_id = (session.source_app_user_model_id or "").lower()
                    except Exception:
                        pass
                had_command = False
                while self._cmd_queue:
                    action, val = self._cmd_queue.pop(0)
                    cmd_target = session or (mgr.get_current_session() if mgr else None)
                    if cmd_target:
                        try:
                            if action == "play":
                                await cmd_target.try_play_async()
                            elif action == "pause":
                                await cmd_target.try_pause_async()
                            elif action == "toggle":
                                await cmd_target.try_toggle_play_pause_async()
                            elif action == "next":
                                await cmd_target.try_skip_next_async()
                            elif action == "prev":
                                await cmd_target.try_skip_previous_async()
                                if val == "force_double":
                                    await asyncio.sleep(0.09)
                                    await cmd_target.try_skip_previous_async()
                            elif action == "seek" and val is not None:
                                ticks = int(float(val) * 10_000_000)
                                await cmd_target.try_change_playback_position_async(ticks)
                            elif action == "shuffle" and val is not None:
                                await cmd_target.try_change_shuffle_active_async(bool(val))
                            elif action == "repeat" and val is not None:
                                await cmd_target.try_change_auto_repeat_mode_async(ui_to_gsmtc(int(val)))
                            had_command = True
                        except Exception:
                            pass

                if had_command:
                    await asyncio.sleep(0.10)

                if session and best_props and best_info:
                    self._no_session_since = 0.0
                    props = best_props
                    info = best_info
                    is_playing = (info.playback_status == PlaybackStatus.PLAYING)
                    self._publish_repeat_state(info)

                    title = (props.title or "Sem Título").strip()
                    artist = (props.artist or "Artista Desconhecido").strip()

                    tl = session.get_timeline_properties()
                    pos, dur = self._compute_real_position(tl, is_playing)

                    now_mono = time.monotonic()
                    track_key = f"{title}|{artist}"
                    tag_key = album_tag_key(
                        getattr(props, "album_title", "") or "", getattr(props, "album_artist", "") or "", artist
                    )

                    # 1. Mudança de faixa detectada na playlist
                    if track_key != self._last_track_key:
                        self._prev_track_gsmtc_raw = self._last_gsmtc_raw
                        self._last_track_key = track_key
                        self._last_gsmtc_raw = b""
                        self._track_changed_at = now_mono
                        # O dado de posição que vinha antes da troca: se ele continuar chegando, é da faixa anterior
                        self._stale_tl_sig = self._last_tl_sig

                        # 1a. Capa já conhecida da faixa ou do álbum dela (memória/disco, 0ms, zero piscadas!)
                        known = cached_cover(track_key, tag_key)
                        if known:
                            self._cached_thumb = known
                            self._hd_cover_locked = True
                            confirm_cover(track_key, known)
                        else:
                            # Retém suavemente a capa atual na tela até que a nova (GSMTC ou online) esteja pronta
                            self._hd_cover_locked = False
                            self._trigger_hd_fetch_async(track_key, title, artist, tag_key)

                    # 2. Monitora o GSMTC para usar a capa nativa do player imediatamente se for quadrada/nítida
                    if not self._hd_cover_locked:
                        raw_gsmtc = best_raw_thumb or await self._read_gsmtc_thumbnail(props)
                        if raw_gsmtc and raw_gsmtc != self._last_gsmtc_raw:
                            is_stale_from_prev = (
                                bool(self._prev_track_gsmtc_raw)
                                and raw_gsmtc == self._prev_track_gsmtc_raw
                                and (now_mono - self._track_changed_at) < 3.5
                            )
                            if not is_stale_from_prev and not is_browser_logo_thumbnail(raw_gsmtc):
                                self._last_gsmtc_raw = raw_gsmtc
                                # Quadro de vídeo (widescreen) não serve de capa: fica a capa padrão até a busca online
                                # achar a oficial. Ícones pequenos e quadrados continuam valendo como capa provisória.
                                self._cached_thumb = b"" if self._is_video_frame(raw_gsmtc) else raw_gsmtc
                                if self._is_low_res_or_cropped(raw_gsmtc):
                                    self._trigger_hd_fetch_async(track_key, title, artist, tag_key)
                                else:
                                    # Capa nativa já é quadrada e de boa resolução: trava e salva no cache para evitar 2ª atualização!
                                    self._hd_cover_locked = True
                                    _HD_ART_CACHE[track_key] = raw_gsmtc
                                    confirm_cover(track_key, raw_gsmtc)
                                    if tag_key:
                                        # Com álbum informado, guarda uma vez para todas as faixas dele
                                        store_album_cover(tag_key, raw_gsmtc, aliases=(track_key,))
                                    else:
                                        _save_cover_to_disk(track_key, raw_gsmtc)

                    # Posição/duração ainda da faixa anterior (Firefox): segura em "desconhecida" até chegar a nova
                    tl_sig = timeline_signature(tl)
                    pos, dur, self._stale_tl_sig = resolve_track_timeline(tl_sig, self._stale_tl_sig, pos, dur)
                    self._last_tl_sig = tl_sig

                    provider = best_provider

                    self._last_title = title
                    self._last_artist = artist
                    self._last_is_playing = is_playing
                    self._last_pos = pos
                    self._last_dur = dur
                    self._last_provider = provider

                    self.media_updated.emit(title, artist, is_playing, pos, dur, self._cached_thumb, provider)
                elif hold:
                    # Troca de faixa em curso na sessão atual: mantém o estado exibido, sem contar como ausência
                    self._no_session_since = 0.0
                else:
                    # Debounce / Histerese: ao pular de faixa ou quando um vídeo não-musical estiver tocando no navegador,
                    # mantém o estado anterior e só emite 'Nenhuma mídia ativa' se a ausência de música durar mais de 2.0 segundos!
                    now_mono = time.monotonic()
                    if self._no_session_since == 0.0:
                        self._no_session_since = now_mono

                    if (now_mono - self._no_session_since) > 2.0:
                        self.media_updated.emit("Nenhuma mídia ativa", "O que vamos ouvir hoje?", False, 0.0, 0.0, b"", "generic")

            except Exception:
                pass

            await asyncio.sleep(0.35)
