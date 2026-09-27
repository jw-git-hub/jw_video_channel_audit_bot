# Иконка @jw_video_channel_audit_bot — «Отчёт»: лист с загнутым углом, на нём «play» и две строки текста.
# Смысл — «канал → отчёт». Выбрана владельцем 26.09.2026 из десяти вариантов (ten.py).
# Координаты — в пространстве аватарки 800×800 (центр кольца 400,400); иконка центрирована на 400.
# Толщина линий — как у кольца (SW=21), углы скруглены.
# Порядок элементов = порядок волны яркости: лист → «play» → строки (как читается страница).
SW = 21

SHEET = [(300, 250), (440, 250), (500, 310), (500, 550), (300, 550)]
FOLD = [(440, 250), (440, 310), (500, 310)]
PLAY_C, PLAY_H = (392, 365), 88          # центр тяжести и высота «play»
LINES = [[(345, 455), (455, 455)], [(345, 500), (420, 500)]]


def _dot(d, P, p, r):
    x, y = P(*p)
    d.ellipse([x - r, y - r, x + r, y + r], fill=255)


def _poly(d, P, w, pts, closed=False):
    seq = pts + pts[:1] if closed else pts
    for a, b in zip(seq, seq[1:]):
        d.line([P(*a), P(*b)], fill=255, width=int(w))
    for p in pts:                       # скруглённые углы и концы
        _dot(d, P, p, w / 2)


def sheet(d, P, w):
    _poly(d, P, w, SHEET, closed=True)
    _poly(d, P, w, FOLD)


def play(d, P, w):
    (cx, cy), h = PLAY_C, PLAY_H
    a = h * 0.87
    _poly(d, P, w, [(cx - a / 3, cy - h / 2), (cx - a / 3, cy + h / 2), (cx + 2 * a / 3, cy)], closed=True)


def lines(d, P, w):
    for ln in LINES:
        _poly(d, P, w, ln)


ELEMENTS = [sheet, play, lines]
