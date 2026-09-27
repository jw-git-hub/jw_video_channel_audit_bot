# Живая аватарка @jw_video_channel_audit_bot (иконка «Отчёт») — по системе экосистемы (_avatars/_src/avatar.py):
# общий фон, кольцо teal наполняется за 2,6 с, по элементам иконки бежит волна яркости.
# Отличия от шаблона: иконка из icon.py; длина — ровно 3 оборота кольца (7,8 с), чтобы повтор был бесшовным.
# Запуск: python3 avatar.py [имя без расширения]  → <имя>.png (первый кадр) и <имя>.mp4
import cv2, numpy as np, subprocess, sys
from PIL import Image, ImageDraw
from icon import ELEMENTS, SW

S = 4; W = 800; C = 400; R = 250
bg = cv2.imread('bg.png').astype(np.float32)
yy, xx = np.mgrid[0:W, 0:W]
TEAL = np.array([172, 182, 77], np.float32)   # BGR #4DB6AC
DIM = np.array([60, 62, 34], np.float32)
ICON = np.array([164, 173, 73], np.float32)


def layer(fn):
    im = Image.new('L', (W * S, W * S), 0); d = ImageDraw.Draw(im); fn(d)
    return np.asarray(im.resize((W, W), Image.LANCZOS), np.float32) / 255.


P = lambda x, y: (x * S, y * S)
ring = layer(lambda d: d.ellipse([P(C - R - SW / 2, C - R - SW / 2), P(C + R + SW / 2, C + R + SW / 2)],
                                 outline=255, width=SW * S))
elems = [layer(lambda d, f=f: f(d, P, SW * S)) for f in ELEMENTS]

ang = (np.degrees(np.arctan2(xx - C, -(yy - C))) % 360)
CYC = 2.6
centers = np.linspace(0.45, 1.6, len(elems))


def ring_frac(t):
    return min(1.0, 0.28 + 0.72 * (t % CYC) / 1.6)


def elem_b(k, t):
    p = t % CYC; best = 1.0
    for off in (-CYC, 0, CYC):
        dt = abs(p + off - centers[k])
        if dt < 0.45: best = min(best, 1 - 0.24 * 0.5 * (1 + np.cos(np.pi * dt / 0.45)))
    return best


def frame_img(t, still=False):
    img = bg.copy(); f = ring_frac(t)
    bright = np.clip((f * 360 - ang) * np.pi * R / 180 + 0.5, 0, 1) if f < 1 else np.ones_like(ang)
    col = DIM * (1 - bright[..., None]) + TEAL * bright[..., None]
    img = img * (1 - ring[..., None]) + col * ring[..., None]
    for k, e in enumerate(elems):
        c = ICON * (1.0 if still else elem_b(k, t))
        img = img * (1 - e[..., None]) + c * e[..., None]
    return img.clip(0, 255).astype(np.uint8)


name = sys.argv[1] if len(sys.argv) > 1 else 'jw-video-channel-audit-800'
cv2.imwrite(name + '.png', frame_img(0, still=True))
fps = 25; N = int(round(3 * CYC * fps))
p = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{W}', '-r', str(fps),
                      '-i', '-', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'slow', '-crf', '30',
                      '-movflags', '+faststart', name + '.mp4'], stdin=subprocess.PIPE)
for i in range(N):
    p.stdin.write(frame_img(i / fps).tobytes())
p.stdin.close(); p.wait()
