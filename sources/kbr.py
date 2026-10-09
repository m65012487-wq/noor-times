"""ДУМ КБР: график один на всю республику, выкладывается картинками по месяцам.

Картинки: https://dinri-duneiri.ru/azan/<год><месяц тремя цифрами>.jpg
(2026010.jpg — октябрь 2026). Цифры читаются по образцам (digits.py,
kbr_digits.json — вырезаны из сверенных вручную октября–декабря 2026).

Проверки месяца, прежде чем он попадёт в таблицу:
- строк столько, сколько дней в месяце, и номер дня в первой колонке
  читается как номер строки;
- у каждой цифры уверенность не ниже MIN_MARGIN;
- свойства метода ДУМ КБР: Фаджр не позже чем примерно за 90 минут до
  восхода, Иша через 97–114 минут после Магриба;
- общая проверка таблицы (common.check_days).

Каждый день сегодняшняя строка сверяется со страницей kbrdum.ru — она
меняется ежедневно. Расхождение — сбой запуска и письмо владельцу.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import pathlib
import re
import urllib.error

from . import common, digits

IMAGE = 'https://dinri-duneiri.ru/azan/{year}{month:03d}.jpg'
TODAY_PAGE = 'https://www.kbrdum.ru/8-grafik-namazov'
READER = pathlib.Path(__file__).with_name('kbr_digits.json')
MIN_MARGIN = 0.15
MONTHS = ('январ', 'феврал', 'март', 'апрел', 'ма', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр')


GROUNDTRUTH = 'kbr-*.txt'


def image_url(year: int, month: int) -> str:
    return IMAGE.format(year=year, month=month)


def data_rows(gray) -> list:
    """Строки таблицы с данными: [день, день недели, Фаджр … Иша]."""
    rows, cols = digits.grid(gray)
    if len(cols) != 9:
        raise common.SourceError(f'в таблице {len(cols) - 1} колонок вместо 8')
    # Первая и последняя полосы — шапка с названиями колонок.
    return digits.cells(gray, rows, cols)[1:-1]


def read_month(image: bytes, year: int, month: int, reader: digits.Reader) -> list[str]:
    table = data_rows(digits.load_gray(image))
    ndays = calendar.monthrange(year, month)[1]
    if len(table) != ndays:
        raise common.SourceError(f'{year}-{month:02d}: строк {len(table)} вместо {ndays}')
    days = []
    for day, line in enumerate(table, start=1):
        number, margin = reader.number(line[0])
        if number != str(day) or margin < MIN_MARGIN:
            raise common.SourceError(f'{year}-{month:02d}-{day:02d}: номер дня прочитан как {number!r}')
        times = []
        for c in range(6):
            text, margin = reader.number(line[2 + c])
            if len(text) != 4 or margin < MIN_MARGIN:
                raise common.SourceError(
                    f'{year}-{month:02d}-{day:02d}: колонка {common.NAMES[c]} прочитана как {text!r} '
                    f'(уверенность {margin:.2f})')
            times.append(common.hhmm(f'{text[:2]}:{text[2:]}'))
        f, s, _, _, m, i = (common.minutes(t) for t in times)
        # Запас в пару минут: график сглажен вручную, и 28 сентября 2026
        # между Фаджром и восходом стоит 89 минут при правиле «не меньше 90».
        if s - f < 88 or not 97 <= i - m <= 114:
            raise common.SourceError(f'{year}-{month:02d}-{day:02d}: не похоже на метод ДУМ КБР: {" ".join(times)}')
        days.append(' '.join(times))
    return days


def today_row() -> tuple[dt.date, str]:
    """Дата и строка «Фаджр … Иша» со страницы kbrdum.ru."""
    html = common.http_get(TODAY_PAGE).decode('utf-8', 'replace')
    text = re.sub(r'<[^>]+>|&nbsp;', ' ', html)
    m = re.search(r'(\d{1,2})\s+([а-яё]+)\s+(20\d\d)', text, re.I)
    if not m:
        raise common.SourceError('на kbrdum.ru не найдена дата графика')
    month = next((k + 1 for k, stem in enumerate(MONTHS) if m.group(2).lower().startswith(stem)), None)
    if not month:
        raise common.SourceError(f'kbrdum.ru: непонятный месяц {m.group(2)!r}')
    date = dt.date(int(m.group(3)), month, int(m.group(1)))
    times = []
    for name in ('Фаджр', 'Шурук', 'Зухр', 'Аср', 'Магриб', 'Иша'):
        t = re.search(name + r'\s+(\d{1,2}[.:]\d{2})', text[m.end():])
        if not t:
            raise common.SourceError(f'kbrdum.ru: не найдено время «{name}»')
        times.append(common.hhmm(t.group(1)))
    return date, ' '.join(times)


def existing(auth, place, year) -> dict[dt.date, str]:
    path = common.SITE / auth['id'] / place['id'] / f'{year}.json'
    if not path.exists():
        return {}
    table = json.loads(path.read_text(encoding='utf-8'))
    start = dt.date.fromisoformat(table['start'])
    return {start + dt.timedelta(days=i): row for i, row in enumerate(table['days'])}


def collect(log) -> int:
    auth = common.authority('ru-kbr')
    place = auth['places'][0]
    reader = digits.Reader.load(READER)
    today = common.today_msk()
    written = 0
    for year in (today.year, today.year + 1):
        rows = existing(auth, place, year)
        for month in range(1, 13):
            first = dt.date(year, month, 1)
            last = dt.date(year, month, calendar.monthrange(year, month)[1])
            # Прошедшие месяцы, уже лежащие в таблице, не перечитываем:
            # картинки за прошлое не меняются, а качать их каждый день незачем.
            if last < today.replace(day=1) and first in rows and last in rows:
                continue
            try:
                image = common.http_get(IMAGE.format(year=year, month=month))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                raise
            for i, row in enumerate(read_month(image, year, month, reader)):
                rows[first + dt.timedelta(days=i)] = row
        if not rows:
            continue
        # Таблица — непрерывный отрезок дней с первого известного.
        start = min(rows)
        days, d = [], start
        while d in rows:
            days.append(rows[d])
            d += dt.timedelta(days=1)
        if len(days) != len(rows):
            log(f'ДУМ КБР {year}: есть пропуск после {d - dt.timedelta(days=1)}, таблица обрезана по нему')
        if common.write_table(auth, place, year, start, days,
                              title='ДУМ КБР — график намазов по КБР',
                              source='https://dinri-duneiri.ru/azan/ — картинки по месяцам'):
            written += 1
    # Сверка с сегодняшним графиком на сайте ДУМ.
    date, row = today_row()
    published = existing(auth, place, date.year).get(date)
    if published is None:
        log(f'ДУМ КБР: на {date} в таблице строки нет, сверить не с чем')
    elif published != row:
        raise common.SourceError(f'ДУМ КБР {date}: на kbrdum.ru {row}, в таблице {published}')
    else:
        log(f'ДУМ КБР: {date} совпадает с kbrdum.ru')
    return written
