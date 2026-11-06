import asyncio
import datetime
import threading
from PySide6.QtCore import QObject, Signal

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import DataReader, Buffer, InputStreamOptions


class WindowsMediaWorker(QObject):
    """
    Worker em background que conversa com a API nativa do Windows (GSMTC):
    - Detecta Spotify, Chrome, Edge, YouTube, Apple Music, etc.
    - Lê Título, Artista, Status (Playing/Paused), Posição real (compensando last_updated_time) e Capa em bytes.
    - Envia comandos reais de Play, Pause, Toggle, Próxima, Anterior e Seek.
    """
    media_updated = Signal(str, str, bool, float, float, bytes)

    def __init__(self):
        super().__init__()
        self._running = True
        self._cmd_queue = []
        self._last_track_key = ""
        self._cached_thumb = b""
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def send_command(self, action: str, value=None):
        self._cmd_queue.append((action, value))

    def stop(self):
        self._running = False

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._async_loop())

    @staticmethod
    def _compute_real_position(tl, is_playing: bool) -> tuple[float, float]:
        """
        Calcula a posição real da faixa no Windows GSMTC.
        O Windows não atualiza `tl.position` continuamente a cada frame; ele guarda o último
        snapshot em `tl.position` junto com o timestamp UTC `tl.last_updated_time`.
        Quando `is_playing` é True, somamos o tempo decorrido desde `last_updated_time`.
        """
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

                session = mgr.get_current_session() if mgr else None

                had_command = False
                while self._cmd_queue:
                    action, val = self._cmd_queue.pop(0)
                    if session:
                        try:
                            if action == "play":
                                await session.try_play_async()
                            elif action == "pause":
                                await session.try_pause_async()
                            elif action == "toggle":
                                await session.try_toggle_play_pause_async()
                            elif action == "next":
                                await session.try_skip_next_async()
                            elif action == "prev":
                                await session.try_skip_previous_async()
                            elif action == "seek" and val is not None:
                                ticks = int(float(val) * 10_000_000)
                                await session.try_change_playback_position_async(ticks)
                            had_command = True
                        except Exception:
                            pass

                if had_command:
                    await asyncio.sleep(0.10)

                if session:
                    info = session.get_playback_info()
                    is_playing = (info.playback_status == PlaybackStatus.PLAYING)

                    props = await session.try_get_media_properties_async()
                    title = (props.title or "Sem Título").strip()
                    artist = (props.artist or "Artista Desconhecido").strip()

                    tl = session.get_timeline_properties()
                    pos, dur = self._compute_real_position(tl, is_playing)

                    track_key = f"{title}|{artist}"
                    if track_key != self._last_track_key:
                        self._last_track_key = track_key
                        self._cached_thumb = b""
                        if props.thumbnail:
                            try:
                                stream = await props.thumbnail.open_read_async()
                                size = stream.size
                                if size > 0:
                                    buf = Buffer(size)
                                    await stream.read_async(buf, size, InputStreamOptions.NONE)
                                    reader = DataReader.from_buffer(buf)
                                    raw = bytearray(size)
                                    reader.read_bytes(raw)
                                    self._cached_thumb = bytes(raw)
                            except Exception:
                                pass

                    self.media_updated.emit(title, artist, is_playing, pos, dur, self._cached_thumb)
                else:
                    self.media_updated.emit("Nenhuma mídia ativa", "Abra o Spotify ou navegador", False, 0.0, 0.0, b"")

            except Exception:
                pass

            await asyncio.sleep(0.35)
