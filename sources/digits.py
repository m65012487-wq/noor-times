"""Распознавание графиков-картинок: сетка таблицы и цифры в ячейках.

Графики ДУМ КБР и ДУМ РФ выкладываются картинками — чистыми, без шума
сканера, одним шрифтом из месяца в месяц. Поэтому здесь не общий OCR, а
сравнение с образцами: каждая цифра приводится к одному размеру и сличается
с образцами, вырезанными из уже сверенных вручную месяцев (groundtruth/).
Чужой шрифт или сдвиг сетки дают низкую уверенность или неправдоподобную
таблицу — тогда месяц не публикуется, а не публикуется с ошибкой.
"""
from __future__ import annotations

import base64
import io
import json
import pathlib

import numpy as np
from PIL import Image

GLYPH = (16, 24)  # ширина, высота приведённой цифры


def load_gray(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert('L'), dtype=np.uint8)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def grid(gray: np.ndarray, *, dark: int = 110) -> tuple[list[int], list[int]]:
    """Линии таблицы: середины горизонтальных и вертикальных линий.

    Горизонтальная линия — строка картинки, тёмная больше чем на половину
    ширины. Вертикальная — столбец, тёмный на 90% высоты таблицы: порог
    выше, иначе за линию сходит цифра «1», стоящая в каждой строке столбца
    «12:0x» на одном месте.
    """
    ink = gray < dark
    rows = [(a + b) // 2 for a, b in _runs(ink.mean(axis=1) > 0.5)]
    if len(rows) < 3:
        raise ValueError('не найдены строки таблицы')
    cols = [(a + b) // 2 for a, b in _runs(ink[rows[0]:rows[-1]].mean(axis=0) > 0.9)]
    return rows, cols


def glyphs(cell: np.ndarray, *, ink_level: int = 140) -> list[np.ndarray]:
    """Цифры ячейки слева направо, без двоеточия, приведённые к GLYPH.

    Глиф — группа соседних столбцов с чернилами. Отбрасываются:
    - двоеточие: по высоте у него два отдельных пятна (две точки), у цифры одно;
    - тонкие обрывки линий сетки у краёв ячейки;
    - мелкие пятна ниже половины высоты цифр — у ДУМ РФ в углу каждой
      строки нарисован треугольник-метка, и он читался бы как «7».
    """
    ink = cell < ink_level
    h, w = ink.shape
    found = []
    for a, b in _runs(ink.any(axis=0)):
        rows_with_ink = ink[:, a:b + 1].any(axis=1)
        if len(_runs(rows_with_ink)) >= 2:
            continue  # двоеточие
        if (b - a) <= 3 and (a <= 1 or b >= w - 2):
            continue  # край линии сетки
        ys = np.where(rows_with_ink)[0]
        found.append((a, b, ys[0], ys[-1]))
    if not found:
        return []
    tall = max(y1 - y0 for _, _, y0, y1 in found)
    out = []
    for a, b, y0, y1 in found:
        if (y1 - y0) < 0.5 * tall:
            continue
        crop = cell[y0:y1 + 1, a:b + 1]
        img = Image.fromarray(crop).resize(GLYPH, Image.BILINEAR)
        out.append(np.asarray(img, dtype=np.float32) / 255.0)
    return out


def cells(gray: np.ndarray, rows: list[int], cols: list[int], *, inset: int = 6):
    """Ячейки таблицы: [строка][столбец] -> массив серого."""
    out = []
    for r0, r1 in zip(rows, rows[1:]):
        line = []
        for c0, c1 in zip(cols, cols[1:]):
            line.append(gray[r0 + inset:r1 - inset, c0 + inset:c1 - inset])
        out.append(line)
    return out


class Reader:
    """Классификатор цифр по образцам: ближайший сосед по сумме модулей."""

    def __init__(self, samples: np.ndarray, labels: np.ndarray):
        self.samples = samples.reshape(len(samples), -1)
        self.labels = labels

    @classmethod
    def train(cls, pairs: list[tuple[np.ndarray, int]]) -> 'Reader':
        return cls(np.stack([g for g, _ in pairs]), np.array([d for _, d in pairs], dtype=np.int8))

    def save(self, path: pathlib.Path):
        data = (self.samples * 255).round().astype(np.uint8)
        path.write_text(json.dumps({
            'glyph': GLYPH,
            'labels': self.labels.tolist(),
            'samples': base64.b64encode(data.tobytes()).decode('ascii'),
        }), encoding='utf-8')

    @classmethod
    def load(cls, path: pathlib.Path) -> 'Reader':
        data = json.loads(path.read_text(encoding='utf-8'))
        raw = np.frombuffer(base64.b64decode(data['samples']), dtype=np.uint8)
        labels = np.array(data['labels'], dtype=np.int8)
        return cls(raw.reshape(len(labels), -1).astype(np.float32) / 255.0, labels)

    def read(self, glyph: np.ndarray) -> tuple[int, float]:
        """Цифра и уверенность: насколько ближайший образец чужой цифры
        дальше ближайшего своей (1.0 — вдвое дальше и больше)."""
        d = np.abs(self.samples - glyph.reshape(1, -1)).mean(axis=1)
        order = np.argsort(d)
        best = int(self.labels[order[0]])
        other = next((d[i] for i in order if self.labels[i] != best), d[order[0]] * 2)
        margin = float(min(1.0, (other - d[order[0]]) / max(d[order[0]], 1e-6)))
        return best, margin

    def number(self, cell: np.ndarray) -> tuple[str, float]:
        """Ячейка -> строка цифр и худшая уверенность среди них."""
        digits, worst = [], 1.0
        for g in glyphs(cell):
            d, m = self.read(g)
            digits.append(str(d))
            worst = min(worst, m)
        return ''.join(digits), worst
