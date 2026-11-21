"""
AccentWipe - transição "barra de progresso" quando a cor de destaque do Hub muda.

O QSS não anima cor, e reaplicar o estilo do Hub inteiro leva ~70 ms (impossível interpolar quadro a quadro). Então:
1. quem chama tira uma FOTO da janela com a cor antiga (`start(snapshot, ...)`);
2. aplica a cor nova de uma vez (o Hub já fica certo por baixo, e o custo some atrás da foto);
3. esta camada, transparente para o mouse, pinta a foto antiga SÓ à direita de uma borda que anda da esquerda para a
   direita em DURATION_MS: a cor nova vai sendo "pintada", como o preenchimento de uma barra de progresso. A borda
   tem uma faixa suave (FEATHER) para não ficar serrilhada.

`exclude` são retângulos (no sistema da camada) que NUNCA são cobertos pela foto, como o próprio seletor de cor e o
campo hex: eles têm de responder na hora ao clique/arrasto. `carve` são retângulos que ficam FORA dessa exceção
(mesmo dentro da margem de um `exclude`): o que eles contêm é pintado pela onda por inteiro, nunca meio ao vivo e
meio na foto (um anel de cor cortado pela margem do seletor mostraria só um arco novo e o resto velho até a onda
chegar). Sem "Efeitos de animação" do Windows, quem chama aplica a cor direto e nem usa esta camada.
"""

from PySide6.QtCore import QEasingCurve, QEvent, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QWidget

DURATION_MS = 300
FEATHER = 36   # largura (px) da borda suave da frente da onda


class AccentWipe(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._snapshot: QPixmap | None = None
        self._progress = 0.0
        self._exclude = QRegion()
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.valueChanged.connect(self._on_progress)
        self._anim.finished.connect(self.stop)
        parent.installEventFilter(self)   # a janela mudou de tamanho: a foto não serve mais
        self.hide()

    def is_running(self) -> bool:
        return self._snapshot is not None

    def start(self, snapshot: QPixmap, exclude: list[QRect] | None = None, carve: list[QRect] | None = None):
        parent = self.parentWidget()
        self._anim.stop()
        self.setGeometry(parent.rect())
        self._snapshot = snapshot
        self._exclude = QRegion()
        for rect in exclude or []:
            self._exclude = self._exclude.united(QRegion(rect))
        for rect in carve or []:
            self._exclude = self._exclude.subtracted(QRegion(rect))
        self._progress = 0.0
        self.raise_()
        self.show()
        self._anim.start()

    def stop(self):
        """Termina na hora (a cor nova já está aplicada por baixo): some a foto e libera a camada."""
        self._anim.stop()
        self._snapshot = None
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.is_running():
            self.stop()
        return super().eventFilter(obj, event)

    def _on_progress(self, value):
        self._progress = float(value)
        self.update()

    def paintEvent(self, _event):
        snap = self._snapshot
        if snap is None:
            return
        w, h = self.width(), self.height()
        dpr = snap.devicePixelRatio()
        edge = -FEATHER + self._progress * (w + FEATHER)   # x onde a faixa suave começa (a cor nova fica à esquerda)
        solid_x = int(round(edge + FEATHER))                # daqui para a direita, a foto antiga inteira

        p = QPainter(self)
        keep = QRegion(0, 0, w, h).subtracted(self._exclude)
        if solid_x < w:
            p.setClipRegion(keep.intersected(QRegion(max(0, solid_x), 0, w - max(0, solid_x), h)))
            p.drawPixmap(0, 0, snap)

        # Faixa suave: a foto antiga com opacidade subindo de 0 (lado da cor nova) a 1
        band_x = int(round(edge))
        band_l, band_r = max(0, band_x), min(w, band_x + FEATHER)
        if band_r > band_l:
            part = snap.copy(int(band_l * dpr), 0, int((band_r - band_l) * dpr), int(h * dpr))
            part.setDevicePixelRatio(dpr)
            gx = band_x - band_l   # início da faixa no sistema do recorte (negativo se ela entra pela esquerda)
            grad = QLinearGradient(gx, 0, gx + FEATHER, 0)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 255))
            mask = QPainter(part)
            mask.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            mask.fillRect(QRectF(gx, 0, FEATHER, h), grad)
            mask.end()
            p.setClipRegion(keep.intersected(QRegion(band_l, 0, band_r - band_l, h)))
            p.drawPixmap(band_l, 0, part)
        p.end()
