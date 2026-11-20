"""
Estado do cartão de clima: o que mostrar (dias da previsão) e em que ponto está cada animação.

Sem Qt e sem relógio próprio: quem usa passa `now` (segundos). O cartão vivo usa `time.perf_counter()`; a miniatura do
Hub monta um estado com tudo já concluído. As animações espelham as da referência (`select()` no JS):
- fundo: troca de céu com fade cruzado;
- ícone grande: o antigo some encolhendo, o novo cresce;
- temperatura, máxima e mínima: dígitos que mudaram sobem com escalonamento;
- condição: o texto sai para cima e o novo entra de baixo;
- dia: só a parte do nome que muda faz o morph (ex.: "Terça" -> "Quarta");
- abas: a pílula desliza até o dia escolhido; ao trocar de cidade (ou se a previsão de um dia mudar), o ícone e o
  nome de cada aba trocam como o ícone grande e a condição, em onda da esquerda para a direita (ou o contrário).
"""

import datetime
from dataclasses import dataclass, field
from typing import Optional

from app.widgets.weather import conditions as cond
from app.widgets.weather import motion as mo

PAST = -1e9   # "começou há muito tempo": animação já concluída


@dataclass
class DayView:
    short: str        # "Seg"
    full: str         # "Segunda"
    condition: str    # chave de conditions.py
    temp: int
    hi: int
    lo: int


class DigitGroup:
    """Número cujos caracteres novos entram com pop-in (`.t-digit-group` da referência)."""

    def __init__(self, text: str = ""):
        self.text = text
        self.starts: list = [PAST] * len(text)   # início da animação de cada caractere (PAST = parado)

    def set(self, text: str, now: float):
        if text == self.text:
            return
        prev = self.text
        same = 0
        while same < len(prev) and same < len(text) and prev[same] == text[same]:
            same += 1
        starts = []
        n = len(text)
        for i in range(n):
            if i < same:
                starts.append(PAST)
            else:
                stagger = 1 if i == n - 2 else 2 if i == n - 1 else 0
                starts.append(now + stagger * mo.DIGIT_STAGGER)
        self.text = text
        self.starts = starts

    def char_state(self, i: int, now: float) -> tuple:
        """(deslocamento y em px, opacidade) do caractere i."""
        e = mo.EASE_DIGIT(mo.progress(now, self.starts[i], mo.DIGIT_DUR))
        return mo.DIGIT_DISTANCE * (1.0 - e), max(0.0, min(1.0, e))

    def busy(self, now: float) -> bool:
        return any(now < s + mo.DIGIT_DUR for s in self.starts)


class TextSwap:
    """Texto que sai para cima e o novo entra de baixo (`.t-text-swap`)."""

    def __init__(self, text: str = ""):
        self.old = text
        self.new = text
        self.t0 = PAST
        self.direction = 1   # 1: sai para cima e entra de baixo; -1: o contrário (cidade anterior)

    def set(self, text: str, now: float, direction: int = 1):
        if text == self.new:
            return
        showing = self.new if now >= self.t0 + mo.TEXT_SWAP_DUR else self.old
        self.old = showing
        self.new = text
        self.t0 = now
        self.direction = 1 if direction >= 0 else -1

    def state(self, now: float) -> tuple:
        """(texto, deslocamento y, opacidade)."""
        d = mo.TEXT_SWAP_DUR
        if now < self.t0 + d:
            p = mo.EASE_IN_OUT(mo.progress(now, self.t0, d))
            return self.old, -mo.TEXT_SWAP_Y * p * self.direction, 1.0 - p
        q = mo.EASE_IN_OUT(mo.progress(now, self.t0 + d, d))
        return self.new, mo.TEXT_SWAP_Y * (1.0 - q) * self.direction, q

    def progress(self, now: float) -> float:
        """0..1 da troca inteira (saída + entrada)."""
        return mo.progress(now, self.t0, 2 * mo.TEXT_SWAP_DUR)

    def busy(self, now: float) -> bool:
        return now < self.t0 + 2 * mo.TEXT_SWAP_DUR


class TextMorph:
    """Nome do dia: prefixo e sufixo comuns ficam, só o miolo troca com fade e a largura acompanha (`.t-morph`)."""

    def __init__(self, text: str = ""):
        self.prev = text
        self.next = text
        self.t0 = PAST

    def set(self, text: str, now: float):
        if text == self.next:
            return
        self.prev = self.next
        self.next = text
        self.t0 = now

    def parts(self) -> tuple:
        """(prefixo, miolo antigo, miolo novo, sufixo)."""
        prev, nxt = self.prev, self.next
        a = 0
        while a < len(prev) and a < len(nxt) and prev[a] == nxt[a]:
            a += 1
        b = 0
        while b < len(prev) - a and b < len(nxt) - a and prev[len(prev) - 1 - b] == nxt[len(nxt) - 1 - b]:
            b += 1
        return nxt[:a], prev[a:len(prev) - b], nxt[a:len(nxt) - b], nxt[len(nxt) - b:]

    def fade(self, now: float) -> float:
        return mo.EASE_SMOOTH_OUT(mo.progress(now, self.t0, mo.TEXT_MORPH_DUR))

    def resize(self, now: float) -> float:
        return mo.EASE_SMOOTH_OUT(mo.progress(now, self.t0, mo.TEXT_MORPH_RESIZE_DUR))

    def busy(self, now: float) -> bool:
        return now < self.t0 + max(mo.TEXT_MORPH_DUR, mo.TEXT_MORPH_RESIZE_DUR)


@dataclass
class Swap:
    """Troca com fade cruzado de uma chave (céu ou ícone)."""
    current: str
    previous: Optional[str] = None
    t0: float = PAST
    duration: float = mo.SKY_FADE

    def set(self, key: str, now: float):
        if key == self.current:
            return
        self.previous = self.current
        self.current = key
        self.t0 = now

    def progress(self, now: float) -> float:
        return mo.progress(now, self.t0, self.duration)

    def busy(self, now: float) -> bool:
        return self.previous is not None and now < self.t0 + self.duration


# Mensagens sem dados (chaves de i18n)
MSG_LOADING = "weather_loading"
MSG_OFFLINE = "weather_offline"
MSG_NO_LOCATION = "weather_no_location"


@dataclass
class CardState:
    place: str = ""
    days: list = field(default_factory=list)   # list[DayView], até 5
    selected: int = 0
    message: Optional[str] = None             # chave de i18n quando não há dados
    message_detail: str = ""                  # texto já traduzido para a linha de baixo (ex.: "Escolha no Hub")
    font_family: str = ""                     # vazio = fonte do app (Inter)
    animated: bool = True                     # False = efeitos do Windows desligados: tudo estático

    sky: Swap = field(default_factory=lambda: Swap(cond.SUNNY))
    icon: Swap = field(default_factory=lambda: Swap("sun", duration=mo.ICON_SWAP_DUR))
    temp: DigitGroup = field(default_factory=DigitGroup)
    hi: DigitGroup = field(default_factory=DigitGroup)
    lo: DigitGroup = field(default_factory=DigitGroup)
    cond_text: TextSwap = field(default_factory=TextSwap)
    day_text: TextMorph = field(default_factory=TextMorph)
    pill_from: float = 0.0     # índice (fracionário) de onde a pílula partiu
    pill_t0: float = PAST

    place_text: TextSwap = field(default_factory=TextSwap)
    city_count: int = 1        # cidades na lista (os pontos só aparecem com 2 ou mais)
    city_index: int = 0
    city_from: float = 0.0     # posição (fracionária) de onde o ponto ativo partiu
    city_t0: float = PAST

    tab_prev: list = field(default_factory=list)   # [(nome, ícone) | None] por aba: o que ela mostrava antes
    tab_t0: float = PAST
    tab_dir: int = 1           # 1: a onda vai da esquerda para a direita; -1: o contrário
    tab_all: bool = False      # troca de cidade: todas as abas animam (mesmo as que não mudaram)

    hovered_tab: int = -1
    pressed_tab: int = -1
    press_t0: float = PAST

    # --- Conteúdo ---

    def set_days(self, place: str, days: list, condition_names: dict, now: float, animate: bool,
                 direction: int = 1):
        """Troca os dados (nova previsão ou outra cidade). Mantém o dia escolhido se ele ainda existir."""
        old_tabs = [tab_content(d) for d in self.days] if not self.message else []
        new_city = place != self.place
        self.set_place(place, now if animate else PAST, direction)
        self.days = list(days)
        if animate and old_tabs:
            self.tab_prev = [old_tabs[i] if i < len(old_tabs) else None for i in range(5)]
            self.tab_t0, self.tab_dir, self.tab_all = now, (1 if direction >= 0 else -1), new_city
        else:
            self.tab_prev, self.tab_t0 = [], PAST
        self.message = None
        self.message_detail = ""
        self.selected = min(self.selected, max(0, len(self.days) - 1))
        self._show_selected(condition_names, now if animate else PAST)

    def set_message(self, key: str, detail: str = ""):
        self.message = key
        self.message_detail = detail

    def set_place(self, place: str, now: float, direction: int = 1):
        self.place = place
        self.place_text.set(place, now, direction)

    def set_city(self, index: int, count: int, now: float):
        """Posição na lista de cidades (os pontos). Da última para a primeira (e vice-versa) o ponto não atravessa
        a fileira: salta, como a lista dá a volta."""
        index = max(0, min(index, max(0, count - 1)))
        if count == self.city_count and index == self.city_index:
            return
        wraps = count == self.city_count and abs(index - self.city_index) > 1
        self.city_from = float(index) if (wraps or now == PAST or count != self.city_count) else self.dot_position(now)
        self.city_t0 = now
        self.city_index = index
        self.city_count = count

    def dot_position(self, now: float) -> float:
        e = mo.EASE_SMOOTH_OUT(mo.progress(now, self.city_t0, mo.TABS_DUR))
        return mo.lerp(self.city_from, float(self.city_index), e)

    def select(self, index: int, condition_names: dict, now: float) -> bool:
        if not self.days or not 0 <= index < len(self.days) or index == self.selected:
            return False
        self.pill_from = self.pill_position(now)
        self.pill_t0 = now
        self.selected = index
        self._show_selected(condition_names, now)
        return True

    def preview_condition(self, condition: str, condition_names: dict, now: float):
        """Força a condição do dia escolhido (menu de pré-visualização das condições)."""
        if not self.days:
            return
        d = self.days[self.selected]
        self.days[self.selected] = DayView(d.short, d.full, condition, d.temp, d.hi, d.lo)
        self._show_selected(condition_names, now)

    def _show_selected(self, condition_names: dict, now: float):
        d = self.days[self.selected]
        scene = cond.scene_for(d.condition)
        self.sky.set(d.condition, now)
        self.icon.set(scene.icon, now)
        self.temp.set(str(d.temp), now)
        self.hi.set(str(d.hi), now)
        self.lo.set(str(d.lo), now)
        self.cond_text.set(condition_names.get(d.condition, ""), now)
        self.day_text.set(d.full, now)
        if now == PAST:   # sem animação: tudo já no estado final
            self.sky.previous = None
            self.icon.previous = None
            self.pill_t0 = PAST

    # --- Animação ---

    def tab_swap(self, i: int, now: float):
        """(conteúdo anterior da aba, progresso 0..1) se a aba `i` está trocando agora; senão None."""
        if i >= len(self.tab_prev) or i >= len(self.days) or self.tab_prev[i] is None:
            return None
        prev = self.tab_prev[i]
        if not self.tab_all and prev == tab_content(self.days[i]):
            return None   # mesma cidade e a previsão desta aba não mudou: fica parada
        order = i if self.tab_dir > 0 else len(self.days) - 1 - i
        f = mo.progress(now, self.tab_t0 + order * mo.TAB_SWAP_STAGGER, 2 * mo.TEXT_SWAP_DUR)
        return (prev, f) if f < 1.0 else None

    def tabs_busy(self, now: float) -> bool:
        return bool(self.tab_prev) and now < self.tab_t0 + 4 * mo.TAB_SWAP_STAGGER + 2 * mo.TEXT_SWAP_DUR

    def pill_position(self, now: float) -> float:
        e = mo.EASE_SMOOTH_OUT(mo.progress(now, self.pill_t0, mo.TABS_DUR))
        return mo.lerp(self.pill_from, float(self.selected), e)

    def transitions_busy(self, now: float) -> bool:
        """Alguma troca (não o movimento ambiente) ainda em curso?"""
        return (self.sky.busy(now) or self.icon.busy(now) or self.temp.busy(now) or self.hi.busy(now)
                or self.lo.busy(now) or self.cond_text.busy(now) or self.day_text.busy(now)
                or self.place_text.busy(now) or self.tabs_busy(now) or now < self.city_t0 + mo.TABS_DUR
                or now < self.pill_t0 + mo.TABS_DUR or now < self.press_t0 + mo.PRESS_DUR)


def tab_content(day: DayView) -> tuple:
    """O que uma aba mostra: (nome curto do dia, ícone)."""
    return day.short, cond.TAB_ICON.get(day.condition, "cloud")


def weekday_names(lang_short: list, lang_full: list, date_iso: str) -> tuple:
    """(curto, completo) do dia da semana de uma data ISO."""
    try:
        wd = datetime.date.fromisoformat(date_iso).weekday()
    except ValueError:
        wd = 0
    return lang_short[wd], lang_full[wd]
