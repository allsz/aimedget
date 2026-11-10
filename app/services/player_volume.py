"""
Liga o player que o Music Widget está exibindo à sessão de áudio dele no mixer do Windows.

Regra:
- Player de desktop (Spotify, Apple Music, Deezer, Tidal, players locais): volume do próprio app.
- Navegador (YouTube Music, SoundCloud na web, PWAs): volume do navegador inteiro, pois o Windows
  só expõe um controle por processo/aplicativo, não por aba.
- Sem correspondência: devolve None e quem chama usa o volume do sistema.

Lógica pura (sem COM), para ser testável sem áudio real.
"""

import os
import re

# Tokens genéricos de fabricantes que não identificam um app sozinhos
_STOP_TOKENS = {"microsoft", "windows", "google", "apple", "appleinc", "adobe"}

# Palavras-chave de apps desktop por provedor, usadas só quando o AUMID não casa com nada
_PROVIDER_KEYWORDS = {
    "spotify": ("spotify",),
    "apple_music": ("applemusic", "itunes"),
    "deezer": ("deezer",),
    "tidal": ("tidal",),
    "amazon_music": ("amazon",),
}

_FIREFOX_HASH_AUMID = re.compile(r"[0-9a-f]{16}")


def aumid_candidates(aumid: str) -> set[str]:
    """
    Nomes plausíveis do app a partir do AUMID do GSMTC. Exemplos:
    'Spotify.exe' -> {spotify}; 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' -> {spotifyab, spotifymusic, spotify};
    'Chrome._crx_xxx' -> {chrome}; 'MSEdge' -> {msedge}.
    """
    a = (aumid or "").strip().lower()
    if not a:
        return set()
    if _FIREFOX_HASH_AUMID.fullmatch(a):  # o Firefox usa um AUMID em hash
        return {"firefox"}

    cands: set[str] = set()
    pkg, _, app = a.partition("!")
    for part in (pkg, app):
        part = part[:-4] if part.endswith(".exe") else part
        base = part.split("_")[0]  # remove o hash do publisher: "..._zpdnekdrzrea0"
        cands.add(base)
        cands.update(tok for tok in base.replace("-", ".").split(".") if tok)
    return {c for c in cands if len(c) >= 4 and c not in _STOP_TOKENS}


def _session_names(session) -> set[str]:
    names = {(session.name or "").lower()}
    exe = os.path.splitext(os.path.basename(session.app_id or ""))[0].lower()
    names.add(exe)
    return {n for n in names if len(n) >= 4}


def find_session_for_player(aumid: str, provider: str, sessions: list):
    """Sessão do mixer que pertence ao player de origem da mídia, ou None."""
    candidates = [s for s in sessions if not getattr(s, "is_system_sounds", False)]

    cands = aumid_candidates(aumid)
    best = None
    best_len = 0
    for s in candidates:
        for n in _session_names(s):
            if any(n in c or c in n for c in cands) and len(n) > best_len:
                best, best_len = s, len(n)
    if best is not None:
        return best

    # Sem casar pelo AUMID: tenta o app desktop do provedor detectado
    for kw in _PROVIDER_KEYWORDS.get((provider or "").lower(), ()):
        for s in candidates:
            if any(kw in n for n in _session_names(s)):
                return s
    return None
