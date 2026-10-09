"""Пересобрать образцы цифр: python -m sources.train kbr|moscow

Образцы вырезаются из месяцев, перенесённых вручную в groundtruth/: картинка
месяца раскладывается на ячейки, и каждая цифра получает метку из сверенной
строки. Нужен, если управление сменит шрифт или вёрстку: перенести вручную
один-два новых месяца, дописать в groundtruth и запустить.
"""
from __future__ import annotations

import datetime as dt
import sys

from . import common, digits, kbr, moscow

SOURCES = {'kbr': kbr, 'moscow': moscow}
PER_DIGIT = 40


def load_truth(pattern: str) -> dict[dt.date, list[str]]:
    truth = {}
    for path in sorted((common.ROOT / 'groundtruth').glob(pattern)):
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('#') or not line.strip():
                continue
            date, *times = line.split()
            truth[dt.date.fromisoformat(date)] = times
    return truth


def pairs_for_month(src, year: int, month: int, truth) -> list:
    table = src.data_rows(digits.load_gray(common.http_get(src.image_url(year, month))))
    pairs = []
    for day, line in enumerate(table, start=1):
        times = truth[dt.date(year, month, day)]
        for c in range(6):
            want = times[c].replace(':', '')
            found = digits.glyphs(line[2 + c])
            if len(found) != len(want):
                raise ValueError(f'{year}-{month:02d}-{day:02d}: цифр {len(found)}, ждали {want}')
            pairs += [(g, int(ch)) for g, ch in zip(found, want)]
        found = digits.glyphs(line[0])
        if len(found) == len(str(day)):
            pairs += [(g, int(ch)) for g, ch in zip(found, str(day))]
    return pairs


def main(name: str):
    src = SOURCES[name]
    truth = load_truth(src.GROUNDTRUTH)
    months = sorted({(d.year, d.month) for d in truth})
    pairs = []
    for year, month in months:
        pairs += pairs_for_month(src, year, month, truth)
    # Не больше PER_DIGIT образцов каждой цифры, ровно по всему набору:
    # шрифт один, и тысячи одинаковых образцов только раздувают файл.
    kept = []
    for digit in range(10):
        same = [p for p in pairs if p[1] == digit]
        step = max(1, len(same) // PER_DIGIT)
        kept += same[::step][:PER_DIGIT]
    digits.Reader.train(kept).save(src.READER)
    print(f'{name}: образцов {len(kept)} (из {len(pairs)}) по месяцам {months} -> {src.READER.name}')


if __name__ == '__main__':
    main(sys.argv[1])
