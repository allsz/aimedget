"""
Arte de tema reutilizável por qualquer container (flyout do Caps, Mixer, ...): imagem de fundo e figurinhas.

Formato no theme.json (todas as chaves são opcionais):

    "background": {"image": "fundo.png", "fit": "cover", "opacity": 1.0},
    "stickers": [
      {"image": "estrela.png", "anchor": "top-right", "x": -4, "y": -6,
       "width": 22, "rotation": 15, "opacity": 1.0, "layer": "above"}
    ]

- Caminhos são relativos à pasta do tema e não podem sair dela.
- `fit`: "cover" (preenche e corta o excesso, padrão) ou "stretch" (estica para o card inteiro).
- Figurinha: o CENTRO dela fica no ponto `anchor` do card + (x, y). Âncoras: top-left, top, top-right,
  left, center, right, bottom-left, bottom, bottom-right. Funciona com cards de largura variável.
- `width`/`height` em pixels do card; só um dos dois mantém a proporção; nenhum = tamanho original.
- `layer`: "above" (por cima do conteúdo, padrão) ou "below" (entre o fundo e o conteúdo).
- A figurinha pode passar da borda do card, até onde a janela transparente permitir.

Tudo é carregado UMA vez ao ler o tema; pintar é só desenhar pixmaps já prontos.
"""

import logging
import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPainterPath, QPixmap

logger = logging.getLogger(__name__)

# --- Relato de problemas ---------------------------------------------------------------------
# Ler um tema nunca falha: o que for inválido volta ao padrão. Cada problema passa por `report_issue`,
# que sempre vai para o log e, dentro de `collect_issues()`, também para uma lista (validador, importação).
# Assim a regra de validação existe num lugar só e o "modo estrito" é só ler essa lista.
_issue_sink: ContextVar[list | None] = ContextVar("theme_issue_sink", default=None)
_issue_where: ContextVar[str] = ContextVar("theme_issue_where", default="")
_issue_label: ContextVar[str] = ContextVar("theme_issue_label", default="")


def report_issue(message: str, *args) -> None:
    """Registra um problema do tema (texto em pt-BR). `args` seguem o formato `%` do logging."""
    text = message % args if args else message
    where = _issue_where.get()
    if where:
        text = f"{where}: {text}"
    label = _issue_label.get()
    logger.warning("Tema%s: %s", f" do {label}" if label else "", text)
    sink = _issue_sink.get()
    if sink is not None:
        sink.append(text)


@contextmanager
def collect_issues():
    """`with collect_issues() as issues:` — tudo o que a leitura do tema reportar vai parar em `issues`."""
    sink: list[str] = []
    token = _issue_sink.set(sink)
    try:
        yield sink
    finally:
        _issue_sink.reset(token)


@contextmanager
def issue_scope(where: str | None = None, label: str | None = None):
    """Prefixa os problemas com `where` (ex.: "figurinha 3") e o log com `label` (ex.: "keylock")."""
    tokens = []
    if where is not None:
        tokens.append((_issue_where, _issue_where.set(where)))
    if label is not None:
        tokens.append((_issue_label, _issue_label.set(label)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)

ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
STICKER_EXTENSIONS = ALLOWED_EXTENSIONS + (".svg",)   # SVG só em figurinhas
MAX_SVG_BYTES = 1024 * 1024
MAX_SVG_SIDE = 4096
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIDE = 2048
MAX_STICKERS = 12
MIN_STICKER_SIDE, MAX_STICKER_SIDE = 1.0, 200.0
MAX_OFFSET = 200.0

ANCHORS: dict[str, tuple[float, float]] = {
    "top-left": (0.0, 0.0), "top": (0.5, 0.0), "top-right": (1.0, 0.0),
    "left": (0.0, 0.5), "center": (0.5, 0.5), "right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0), "bottom": (0.5, 1.0), "bottom-right": (1.0, 1.0),
}
FITS = ("cover", "stretch")
LAYERS = ("behind", "below", "above")   # atrás do card / entre o fundo e o conteúdo / por cima de tudo

# Antialiasing de imagens reduzidas: cada imagem é pré-reduzida UMA vez (filtro de média de área,
# de alta qualidade) para SUPERSAMPLE x o tamanho final. Na pintura só sobra uma redução de 2x -> 1x,
# que o desenho bilinear do Qt faz sem serrilhar. Reduzir 512px -> 22px direto na pintura serrilha.
SUPERSAMPLE = 2
_BG_CACHE_MAX = 8


# eq=False: compara por identidade (comparar pixmaps pixel a pixel não faz sentido aqui)
@dataclass(frozen=True, eq=False)
class Background:
    pixmap: QPixmap
    fit: str = "cover"
    opacity: float = 1.0
    _scaled: dict = field(default_factory=dict, repr=False)  # cache: (largura, altura) -> pixmap pré-reduzido


@dataclass(frozen=True, eq=False)
class Sticker:
    pixmap: QPixmap
    anchor: str = "center"
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0       # tamanho em px lógicos (já inclui a folga da sombra, se houver)
    height: float = 0.0
    rotation: float = 0.0
    opacity: float = 1.0
    layer: str = "above"
    state: str = "always"    # "on"/"off": só aparece com a tecla ligada/desligada (só no Caps/Num Lock)

    @property
    def above(self) -> bool:
        return self.layer == "above"


@dataclass(frozen=True, eq=False)
class CardShadow:
    """Sombra suave do card (token `shadow` do tema). Medidas em px lógicos do container."""
    color: QColor
    blur: float = 12.0
    dy: float = 4.0
    _cache: dict = field(default_factory=dict, repr=False)   # raio -> pixmap base da sombra (9-slice)


# --- Antialiasing ----------------------------------------------------------------------------

def presample(pm: QPixmap, target_w: float, target_h: float, factor: float = SUPERSAMPLE) -> QPixmap:
    """
    Reduz `pm` para SUPERSAMPLE x (target_w, target_h) com filtro suave. Se a imagem não for bem maior
    que isso, devolve a original (ampliar não ganha nada e só borra).
    """
    want_w = max(1, int(round(target_w * factor)))
    want_h = max(1, int(round(target_h * factor)))
    if pm.width() <= want_w * 1.05 and pm.height() <= want_h * 1.05:
        return pm
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)  # sem franjas escuras na transparência
    scaled = img.scaled(want_w, want_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(scaled)


# --- Leitura ---------------------------------------------------------------------------------

def parse_color(value) -> QColor | None:
    """Aceita '#rgb', '#rrggbb' ou '#aarrggbb' (formato do Qt). Qualquer outra coisa é inválida."""
    if not isinstance(value, str) or not value.startswith("#"):
        return None
    color = QColor(value)
    return color if color.isValid() else None


def _blur(img: QImage, f: float) -> QImage:
    """Desfoque barato e suave: desce a imagem por um fator e sobe de volta com filtro bilinear."""
    f = max(1, int(f))
    if f == 1:
        return img
    w, h = img.width(), img.height()
    small = img.scaled(max(1, w // f), max(1, h // f), Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    return small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def _silhouette(img: QImage, color: QColor) -> QImage:
    sil = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    sil.fill(0)
    p = QPainter(sil)
    p.drawImage(0, 0, img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(sil.rect(), color)
    p.end()
    return sil


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(data: dict, key: str, default: float, lo: float, hi: float) -> float:
    if key not in data:
        return default
    v = data[key]
    if not _is_number(v):
        report_issue("'%s' precisa ser um número, mas veio %r (usando %s)", key, v, default)
        return default
    return max(lo, min(hi, float(v)))


def _resolve_asset(base_dir: str, rel_path, allowed: tuple[str, ...], what: str) -> str | None:
    """Caminho absoluto de um arquivo DENTRO da pasta do tema, ou None (com aviso). Valida extensão."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        report_issue("falta o nome do arquivo em 'image' (veio %r); a imagem foi ignorada", rel_path)
        return None
    if os.path.isabs(rel_path) or os.path.splitdrive(rel_path)[0]:
        report_issue("caminho absoluto não é permitido (%r); use só o nome do arquivo, na pasta do tema", rel_path)
        return None

    base = os.path.realpath(base_dir)
    full = os.path.realpath(os.path.join(base, rel_path))
    try:
        inside = os.path.commonpath([base, full]) == base
    except ValueError:  # drives diferentes
        inside = False
    if not inside:
        report_issue("a imagem precisa ficar dentro da pasta do tema (%r sai dela)", rel_path)
        return None
    if os.path.splitext(full)[1].lower() not in allowed:
        report_issue("formato não suportado em %s (%r); use %s", what, rel_path,
                     ", ".join(e.lstrip(".") for e in allowed))
        return None
    if not os.path.isfile(full):
        report_issue("imagem não encontrada: %r (confira o nome e se o arquivo está na pasta do tema)", rel_path)
        return None
    return full


def load_pixmap(base_dir: str, rel_path, allowed: tuple[str, ...] = ALLOWED_EXTENSIONS,
                what: str = "imagem") -> QPixmap | None:
    """Carrega uma imagem raster (png/jpg/webp) de dentro da pasta do tema. None (com aviso) se inválida."""
    full = _resolve_asset(base_dir, rel_path, allowed, what)
    if full is None:
        return None
    size = os.path.getsize(full)
    if size > MAX_FILE_BYTES:
        report_issue("imagem muito grande (%d KB, máximo %d KB): %r",
                     size // 1024, MAX_FILE_BYTES // 1024, rel_path)
        return None

    reader = QImageReader(full)
    dims = reader.size()  # lê só o cabeçalho, sem decodificar a imagem
    if dims.isValid() and (dims.width() > MAX_IMAGE_SIDE or dims.height() > MAX_IMAGE_SIDE):
        report_issue("imagem com dimensões demais (%dx%d, máximo %d de lado): %r",
                     dims.width(), dims.height(), MAX_IMAGE_SIDE, rel_path)
        return None
    img = reader.read()
    if img.isNull():
        report_issue("não foi possível ler a imagem %r (%s); o arquivo pode estar corrompido", rel_path, reader.errorString())
        return None
    return QPixmap.fromImage(img)


_HREF_RE = re.compile(r"""(?:xlink:)?href\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_URL_RE = re.compile(r"""url\(\s*['"]?\s*([^)'"\s]*)""", re.IGNORECASE)


def svg_is_safe(data: bytes) -> bool:
    """
    O SVG só pode referenciar elementos DELE MESMO (#id). Recusa scripts, entidades externas e qualquer
    href/url() que aponte para arquivo, rede ou dados embutidos: o tema nunca deve ler nada fora da pasta.
    """
    text = data.decode("utf-8", errors="ignore")
    low = text.lower()
    if "<script" in low or "<!entity" in low or "<foreignobject" in low:
        return False
    for ref in _HREF_RE.findall(text):
        if not ref.strip().startswith("#"):
            return False
    for ref in _URL_RE.findall(text):
        if ref and not ref.startswith("#"):
            return False
    return True


def load_svg(base_dir: str, rel_path):
    """Valida e abre um SVG da pasta do tema. Devolve um QSvgRenderer ou None (com aviso)."""
    full = _resolve_asset(base_dir, rel_path, (".svg",), "figurinha")
    if full is None:
        return None
    size = os.path.getsize(full)
    if size > MAX_SVG_BYTES:
        report_issue("SVG muito grande (%d KB, máximo %d KB): %r", size // 1024, MAX_SVG_BYTES // 1024, rel_path)
        return None
    try:
        with open(full, "rb") as f:
            data = f.read()
    except OSError as exc:
        report_issue("não foi possível ler o SVG %r (%s)", rel_path, exc)
        return None
    if not svg_is_safe(data):
        report_issue("SVG recusado por referenciar arquivo externo, imagem embutida ou script: %r "
                     "(o SVG só pode apontar para elementos dele mesmo, como #id)", rel_path)
        return None
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(QByteArray(data))
    dims = renderer.defaultSize()
    if not renderer.isValid() or dims.width() < 1 or dims.height() < 1:
        report_issue("SVG inválido ou sem tamanho definido (falta width/height ou viewBox): %r", rel_path)
        return None
    if dims.width() > MAX_SVG_SIDE or dims.height() > MAX_SVG_SIDE:
        report_issue("SVG com dimensões demais (%dx%d, máximo %d de lado): %r",
                     dims.width(), dims.height(), MAX_SVG_SIDE, rel_path)
        return None
    return renderer


def _rasterize_svg(renderer, w: float, h: float, k: float) -> QPixmap:
    """Desenha o SVG em (w*k, h*k) pixels: vetorial, então fica nítido em qualquer tamanho."""
    pw, ph = max(1, int(round(w * k))), max(1, int(round(h * k)))
    img = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0.0, 0.0, float(pw), float(ph)))
    p.end()
    return QPixmap.fromImage(img)


def parse_background(data, base_dir: str) -> Background | None:
    if data is None:
        return None
    with issue_scope("fundo"):
        if not isinstance(data, dict):
            report_issue("'background' precisa ser um objeto, como {\"image\": \"fundo.png\"}")
            return None
        pm = load_pixmap(base_dir, data.get("image"), what="fundo")
        if pm is None:
            return None
        fit = data.get("fit", "cover")
        if fit not in FITS:
            report_issue("'fit' inválido: %r (use %s; usando cover)", fit, " ou ".join(FITS))
            fit = "cover"
        return Background(pm, fit, _num(data, "opacity", 1.0, 0.0, 1.0))


def _parse_shadow_spec(spec, default_color: QColor, default_blur: float, default_dy: float,
                       max_blur: float) -> tuple[QColor, float, float] | None:
    """`true` = padrão; objeto = {"color", "blur", "dy"}; falso/ausente = sem sombra."""
    if spec is None or spec is False:
        return None
    if spec is True:
        return QColor(default_color), default_blur, default_dy
    if not isinstance(spec, dict):
        report_issue("'shadow' precisa ser true, false ou um objeto como {\"color\": \"#80000000\", \"blur\": 8, \"dy\": 3} (veio %r)", spec)
        return None
    color = QColor(default_color)
    if "color" in spec:
        c = parse_color(spec["color"])
        if c is None:
            report_issue("cor inválida em 'shadow.color': %r (use #rrggbb ou #aarrggbb; usando o padrão)", spec["color"])
        else:
            color = c
    blur = _num(spec, "blur", default_blur, 0.0, max_blur)
    dy = _num(spec, "dy", default_dy, -max_blur, max_blur)
    return color, blur, dy


def _bake_sticker_shadow(pm: QPixmap, w: float, h: float, color: QColor, blur: float, dy: float):
    """
    Assa a sombra de contato DENTRO da imagem da figurinha (uma vez só, ao carregar): a imagem ganha uma
    folga em volta e passa a incluir a silhueta desfocada. Devolve (pixmap, largura, altura) lógicos.
    """
    k = pm.width() / w if w else 1.0                 # pixels de imagem por px lógico
    pad = math.ceil(blur * 2.0 + abs(dy))
    tw, th = w + 2 * pad, h + 2 * pad
    out = QImage(max(1, int(round(tw * k))), max(1, int(round(th * k))), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    base = QImage(out.size(), QImage.Format.Format_ARGB32_Premultiplied)
    base.fill(0)
    q = QPainter(base)
    q.drawPixmap(int(round(pad * k)), int(round(pad * k)), pm)
    q.end()
    shadow = _blur(_silhouette(base, color), blur * k)
    q = QPainter(out)
    q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    q.drawImage(0, int(round(dy * k)), shadow)
    q.drawImage(0, 0, base)
    q.end()
    return QPixmap.fromImage(out), tw, th


DEFAULT_STICKER_SHADOW = (QColor(60, 20, 110, 120), 1.6, 1.6)


STATES = ("always", "on", "off")


def parse_stickers(data, base_dir: str, render_scale: float = 1.0, allow_state: bool = False) -> tuple[Sticker, ...]:
    """
    `render_scale` é a escala do container (ex.: 2.0 no Caps): as imagens são preparadas já na resolução
    necessária para ficarem nítidas e sem serrilhado nesse tamanho.
    """
    if data is None:
        return ()
    if not isinstance(data, list):
        report_issue("'stickers' precisa ser uma lista [ {...}, {...} ]; nenhuma figurinha foi usada")
        return ()
    if len(data) > MAX_STICKERS:
        report_issue("no máximo %d figurinhas; as %d últimas foram ignoradas", MAX_STICKERS, len(data) - MAX_STICKERS)
    factor = SUPERSAMPLE * max(1.0, float(render_scale))
    out: list[Sticker] = []
    for i, item in enumerate(data[:MAX_STICKERS]):
        with issue_scope(f"figurinha {i + 1}"):   # numeração a partir de 1, como o designer conta
            sticker = _parse_sticker(item, base_dir, factor, allow_state)
        if sticker is not None:
            out.append(sticker)
    return tuple(out)


_STICKER_KEYS = ("image", "anchor", "x", "y", "width", "height", "rotation", "opacity", "layer", "shadow")
_STICKER_KEYS_STATE = _STICKER_KEYS + ("state",)


def _parse_sticker(item, base_dir: str, factor: float, allow_state: bool = False) -> Sticker | None:
    if not isinstance(item, dict):
        report_issue("precisa ser um objeto, como {\"image\": \"estrela.svg\"}")
        return None

    rel = item.get("image")
    is_svg = isinstance(rel, str) and rel.lower().endswith(".svg")
    renderer = pm = None
    if is_svg:
        renderer = load_svg(base_dir, rel)
        if renderer is None:
            return None
        nat_w, nat_h = float(renderer.defaultSize().width()), float(renderer.defaultSize().height())
    else:
        pm = load_pixmap(base_dir, rel, STICKER_EXTENSIONS, "figurinha")
        if pm is None:
            return None
        nat_w, nat_h = float(pm.width()), float(pm.height())

    valid_keys = _STICKER_KEYS_STATE if allow_state else _STICKER_KEYS
    for key in item:
        if key not in valid_keys:
            if key == "state":
                report_issue("'state' (figurinha que acende/apaga com a tecla) só existe no Caps/Num Lock (ignorada)")
            else:
                report_issue("chave desconhecida '%s' (ignorada); as válidas são: %s", key, ", ".join(valid_keys))
    state = item.get("state", "always") if allow_state else "always"
    if state not in STATES:
        report_issue("'state' inválido: %r (use %s; usando always)", state, ", ".join(STATES))
        state = "always"

    anchor = item.get("anchor", "center")
    if anchor not in ANCHORS:
        report_issue("'anchor' inválido: %r (use %s; usando center)", anchor, ", ".join(ANCHORS))
        anchor = "center"
    layer = item.get("layer", "above")
    if layer not in LAYERS:
        report_issue("'layer' inválido: %r (use %s; usando above)", layer, ", ".join(LAYERS))
        layer = "above"

    w = _num(item, "width", 0.0, MIN_STICKER_SIDE, MAX_STICKER_SIDE) if "width" in item else 0.0
    h = _num(item, "height", 0.0, MIN_STICKER_SIDE, MAX_STICKER_SIDE) if "height" in item else 0.0
    if w and not h:
        h = w * nat_h / nat_w
    elif h and not w:
        w = h * nat_w / nat_h
    elif not w and not h:
        w, h = nat_w, nat_h
    w = max(MIN_STICKER_SIDE, min(MAX_STICKER_SIDE, w))
    h = max(MIN_STICKER_SIDE, min(MAX_STICKER_SIDE, h))

    pixmap = _rasterize_svg(renderer, w, h, factor) if is_svg else presample(pm, w, h, factor)
    shadow = _parse_shadow_spec(item.get("shadow"), *DEFAULT_STICKER_SHADOW, max_blur=20.0)
    if shadow is not None:
        pixmap, w, h = _bake_sticker_shadow(pixmap, w, h, *shadow)

    return Sticker(
        pixmap=pixmap, anchor=anchor,
        x=_num(item, "x", 0.0, -MAX_OFFSET, MAX_OFFSET),
        y=_num(item, "y", 0.0, -MAX_OFFSET, MAX_OFFSET),
        width=w, height=h,
        rotation=_num(item, "rotation", 0.0, -360.0, 360.0),
        opacity=_num(item, "opacity", 1.0, 0.0, 1.0),
        layer=layer, state=state,
    )


def parse_card_shadow(data) -> CardShadow | None:
    """Token `shadow` do tema: sombra suave do card. `true` usa um padrão discreto."""
    spec = _parse_shadow_spec(data, QColor(0, 0, 0, 70), 8.0, 3.0, max_blur=60.0)
    if spec is None:
        return None
    color, blur, dy = spec
    return CardShadow(color=color, blur=blur, dy=dy)


def dir_signature(base_dir: str, limit: int = 200, recursive: bool = True) -> tuple:
    """Assinatura (arquivo, data, tamanho) da pasta do tema: muda quando QUALQUER arquivo muda."""
    sig = []
    for root, _dirs, files in os.walk(base_dir):
        if not recursive:
            _dirs[:] = []
        for name in files:
            full = os.path.join(root, name)
            try:
                sig.append((full, os.path.getmtime(full), os.path.getsize(full)))
            except OSError:
                continue
            if len(sig) >= limit:
                return tuple(sorted(sig))
    return tuple(sorted(sig))


# --- Pintura ---------------------------------------------------------------------------------

def _background_for_size(bg: Background, w: float, h: float) -> QPixmap:
    """Fundo já cortado (cover) e pré-reduzido para o tamanho do card; guardado em cache por tamanho."""
    key = (int(round(w)), int(round(h)))
    cached = bg._scaled.get(key)
    if cached is not None:
        return cached

    pm = bg.pixmap
    if bg.fit == "cover" and pm.width() > 0 and pm.height() > 0:
        target_ratio = w / h
        sw, sh = float(pm.width()), float(pm.height())
        if sw / sh > target_ratio:  # imagem mais larga: corta as laterais
            new_w = sh * target_ratio
            crop = QRectF((sw - new_w) / 2.0, 0.0, new_w, sh)
        else:  # mais alta: corta topo e base
            new_h = sw / target_ratio
            crop = QRectF(0.0, (sh - new_h) / 2.0, sw, new_h)
        pm = pm.copy(crop.toAlignedRect())
    result = presample(pm, w, h)

    if len(bg._scaled) >= _BG_CACHE_MAX:
        bg._scaled.clear()
    bg._scaled[key] = result
    return result


def paint_background(p: QPainter, rect: QRectF, bg: Background, radius: float):
    """Pinta a imagem de fundo recortada pelo cartão arredondado (recuada 1px para não cobrir a borda)."""
    inner = rect.adjusted(1.0, 1.0, -1.0, -1.0)
    if inner.width() <= 0 or inner.height() <= 0:
        return
    pm = _background_for_size(bg, inner.width(), inner.height())
    src = QRectF(0.0, 0.0, float(pm.width()), float(pm.height()))

    p.save()
    clip = QPainterPath()
    r = max(0.0, radius - 1.0)
    clip.addRoundedRect(inner, r, r)
    p.setClipPath(clip)
    p.setOpacity(p.opacity() * bg.opacity)
    p.drawPixmap(inner, pm, src)
    p.restore()


def _paint_layer(p: QPainter, rect: QRectF, stickers, layer: str, on_amount: float | None = None):
    for st in stickers:
        if st.layer != layer:
            continue
        # Figurinha de estado: aparece com a tecla ligada (on) ou desligada (off), com transição suave
        k = 1.0
        if on_amount is not None and st.state != "always":
            k = on_amount if st.state == "on" else 1.0 - on_amount
            if k <= 0.003:
                continue
        ax, ay = ANCHORS[st.anchor]
        cx = rect.x() + rect.width() * ax + st.x
        cy = rect.y() + rect.height() * ay + st.y
        p.save()
        p.setOpacity(p.opacity() * st.opacity * k)
        p.translate(cx, cy)
        if st.rotation:
            p.rotate(st.rotation)
        p.drawPixmap(
            QRectF(-st.width / 2.0, -st.height / 2.0, st.width, st.height),
            st.pixmap,
            QRectF(0.0, 0.0, float(st.pixmap.width()), float(st.pixmap.height())),
        )
        p.restore()


def paint_stickers(p: QPainter, rect: QRectF, stickers, above: bool, on_amount: float | None = None):
    """
    Camadas "above" (por cima do conteúdo; above=True) ou "below" (entre o fundo e o conteúdo).
    `on_amount` (0 = desligado, 1 = ligado) só importa para figurinhas com `state`; sem ele, valem todas.
    """
    _paint_layer(p, rect, stickers, "above" if above else "below", on_amount)


def paint_stickers_behind(p: QPainter, rect: QRectF, stickers, on_amount: float | None = None):
    """Camada "behind": figurinhas ATRÁS do card (desenhar antes do fundo do card)."""
    _paint_layer(p, rect, stickers, "behind", on_amount)


def _shadow_base(sh: CardShadow, radius: float) -> tuple[QPixmap, float, float]:
    """Pixmap base da sombra, calculado uma vez por raio, fatiado em 9 partes na hora de pintar."""
    rc = max(1, math.ceil(radius))
    key = rc
    cached = sh._cache.get(key)
    if cached is not None:
        return cached
    K = 2.0                                  # pixels de imagem por px lógico
    pad = math.ceil(sh.blur * 2.0)
    bw = max(4, 2 * rc + 2)                  # card pequeno: os cantos + 2px de miolo esticável
    W = int(round((bw + 2 * pad) * K))
    img = QImage(W, W, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    q = QPainter(img)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(sh.color)
    q.drawRoundedRect(QRectF(pad * K, pad * K, bw * K, bw * K), radius * K, radius * K)
    q.end()
    pm = QPixmap.fromImage(_blur(img, sh.blur * K / 1.6))
    sh._cache[key] = (pm, float(pad), float(rc))
    return sh._cache[key]


def paint_card_shadow(p: QPainter, rect: QRectF, radius: float, sh: CardShadow):
    """Sombra suave por trás do card. Barata e independente do tamanho (9-slice), então serve para cards animados."""
    if sh.color.alpha() == 0:
        return
    pm, pad, rc = _shadow_base(sh, radius)
    K = pm.width() / (max(4, 2 * int(rc) + 2) + 2 * pad)
    corner = pad + rc                                    # tamanho do canto, em px lógicos
    dest = QRectF(rect.x() - pad, rect.y() - pad + sh.dy, rect.width() + 2 * pad, rect.height() + 2 * pad)
    if dest.width() < 2 * corner or dest.height() < 2 * corner:
        return                                           # card menor que o próprio raio: nada a desenhar
    cs = corner * K                                      # canto em px de imagem
    mid_s = pm.width() - 2 * cs                          # miolo esticável em px de imagem
    xs = (0.0, cs, pm.width() - cs, float(pm.width()))
    ys = (0.0, cs, pm.height() - cs, float(pm.height()))
    xd = (dest.left(), dest.left() + corner, dest.right() - corner, dest.right())
    yd = (dest.top(), dest.top() + corner, dest.bottom() - corner, dest.bottom())
    for iy in range(3):
        for ix in range(3):
            if ix == 1 and iy == 1 and mid_s <= 0:
                continue
            p.drawPixmap(QRectF(xd[ix], yd[iy], xd[ix + 1] - xd[ix], yd[iy + 1] - yd[iy]), pm,
                         QRectF(xs[ix], ys[iy], xs[ix + 1] - xs[ix], ys[iy + 1] - ys[iy]))


def overflow_margins(stickers, shadow: CardShadow | None, card_w: float, card_h: float) -> tuple[float, float, float, float]:
    """
    Quanto a arte passa para fora do card, em px lógicos: (esquerda, topo, direita, base).
    O flyout usa isso para dar à janela transparente folga suficiente (senão a arte seria cortada).
    """
    left = top = right = bottom = 0.0
    for st in stickers:
        ax, ay = ANCHORS[st.anchor]
        cx = card_w * ax + st.x
        cy = card_h * ay + st.y
        a = math.radians(st.rotation)
        hw = (abs(st.width * math.cos(a)) + abs(st.height * math.sin(a))) / 2.0
        hh = (abs(st.width * math.sin(a)) + abs(st.height * math.cos(a))) / 2.0
        left = max(left, hw - cx)
        right = max(right, cx + hw - card_w)
        top = max(top, hh - cy)
        bottom = max(bottom, cy + hh - card_h)
    if shadow is not None:
        reach = shadow.blur * 2.0
        left = max(left, reach)
        right = max(right, reach)
        top = max(top, reach - shadow.dy)
        bottom = max(bottom, reach + shadow.dy)
    return left, top, right, bottom
