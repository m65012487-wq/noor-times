"""ДУМ РФ: «Время намазов по Москве и Московской области», картинка на месяц.

Картинки: https://dumrf.ru/img/namaz/<номер месяца>.jpg (10.jpg — октябрь),
без года в адресе: ДУМ держит на сайте текущий и следующий месяц и
перезаписывает файлы. Год выводится из даты запуска: месяц не раньше
текущего — этот год, раньше (январь, выложенный в декабре) — следующий.
Принятые месяцы копятся в таблице года, потому что прошлые картинки с сайта
исчезают.

Цифры читаются по образцам (digits.py, moscow_digits.json — из сверенного
вручную октября 2026). Сегодняшняя строка сверяется с блоком «Время
намазов на сегодня» на главной dumrf.ru.
"""
from __future__ import annotations

import calendar
import datetime as dt
import pathlib
import re
import urllib.error

from . import common, digits
from .kbr import existing

IMAGE = 'https://dumrf.ru/img/namaz/{month}.jpg'
TODAY_PAGE = 'https://dumrf.ru/'
READER = pathlib.Path(__file__).with_name('moscow_digits.json')
GROUNDTRUTH = 'moscow-*.txt'
MIN_MARGIN = 0.15


def image_url(year: int, month: int) -> str:
    return IMAGE.format(month=month)


def data_rows(gray) -> list:
    """Строки с данными: [дата, день недели, Фаджр … Иша, день хиджры]."""
    rows, cols = digits.grid(gray)
    if len(cols) != 10:
        raise common.SourceError(f'в таблице {len(cols) - 1} колонок вместо 9')
    # Первая полоса — шапка; нижней шапки у ДУМ РФ нет.
    return digits.cells(gray, rows, cols)[1:]


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
        days.append(' '.join(times))
    return days


def today_row() -> str:
    """Строка «Фаджр … Иша» из блока на главной dumrf.ru (дата там только по хиджре)."""
    html = common.http_get(TODAY_PAGE).decode('utf-8', 'replace')
    block = re.search(r'<div id="namaz">(.*?)</div>', html, re.S)
    if not block:
        raise common.SourceError('на dumrf.ru нет блока «Время намазов на сегодня»')
    text = re.sub(r'<[^>]+>|&nbsp;', ' ', block.group(1))
    times = []
    for name in ('Фаджр', 'Шурук', 'Зухр', 'Аср', 'Магриб', 'Иша'):
        t = re.search(name + r'\s+(\d{1,2}:\d{2})', text)
        if not t:
            raise common.SourceError(f'dumrf.ru: не найдено время «{name}»')
        times.append(common.hhmm(t.group(1)))
    return ' '.join(times)


def collect(log) -> int:
    auth = common.authority('ru-moscow')
    place = auth['places'][0]
    reader = digits.Reader.load(READER)
    today = common.today_msk()
    tables = {}
    for month in (today.month, today.month % 12 + 1):
        year = today.year if month >= today.month else today.year + 1
        try:
            image = common.http_get(image_url(year, month))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        rows = tables.setdefault(year, existing(auth, place, year))
        first = dt.date(year, month, 1)
        for i, row in enumerate(read_month(image, year, month, reader)):
            rows[first + dt.timedelta(days=i)] = row
    written = 0
    for year, rows in tables.items():
        start = min(rows)
        days, d = [], start
        while d in rows:
            days.append(rows[d])
            d += dt.timedelta(days=1)
        if len(days) != len(rows):
            # Месяц пропущен (сборщик не работал, пока картинка висела): берём
            # непрерывный хвост, чтобы свежие месяцы не пропали из таблицы.
            later = sorted(x for x in rows if x >= d)
            start = later[0]
            days, d = [], start
            while d in rows:
                days.append(rows[d])
                d += dt.timedelta(days=1)
            log(f'ДУМ РФ {year}: пропуск в месяцах, таблица начинается с {start}')
        if common.write_table(auth, place, year, start, days,
                              title='ДУМ РФ — время намазов по Москве и Московской области',
                              source='https://dumrf.ru/img/namaz/ — картинки по месяцам'):
            written += 1
    # Сверка с блоком на главной: дата там только по хиджре, поэтому строку
    # ищем среди вчера, сегодня и завтра — сайт мог не обновиться к полуночи.
    row = today_row()
    near = {}
    for delta in (-1, 0, 1):
        d = today + dt.timedelta(days=delta)
        near[d] = existing(auth, place, d.year).get(d)
    if near[today] is None:
        log(f'ДУМ РФ: на {today} в таблице строки нет, сверить не с чем')
    elif row not in near.values():
        raise common.SourceError(f'ДУМ РФ {today}: на dumrf.ru {row}, в таблице {near[today]}')
    else:
        log(f'ДУМ РФ: {today} совпадает с dumrf.ru')
    return written
