"""ДУМ РТ: графики по 44 городам и районам Татарстана.

Источник машинный: страница dumrt.ru/ru/help-info/prayertime/ перечисляет
CSV-файлы по пунктам, в каждом — два года подряд (в 2026 году — 2025 и 2026).
Столбцы, как их раскладывает сам сайт (netcat_template/.../main.js):

  дата; конец сухура; утренний намаз в мечетях; восход; зенит; Зухр; Аср;
  Магриб; Иша; [время киблы]

Фаджр в нашей таблице — конец сухура, то есть начало времени утреннего
намаза. Время, когда его совершают в мечетях, у ДУМ РТ заметно позже (летом
на полчаса и больше) и идёт в extra.fajrInMosque.
"""
from __future__ import annotations

import datetime as dt
import re

from . import common

PAGE = 'https://dumrt.ru/ru/help-info/prayertime/'

# Скачки, которые у ДУМ РТ — правило графика, а не сбой:
# - в начале мая и в начале августа Фаджр и Иша переходят на летний счёт и
#   обратно: за сутки Фаджр сдвигается почти на два часа, Иша — на час;
# - Зухр в мечетях держится круглым временем и меняется ступенью в 5 минут.
RULES = {'Fajr': 130, 'Isha': 70, 'Dhuhr': 5}
CSV = 'https://dumrt.ru/netcat_files/391/638/{src}.csv'


def listed_files() -> set[str]:
    """Имена CSV, которые сейчас перечислены на странице ДУМ РТ."""
    html = common.http_get(PAGE).decode('utf-8', 'replace')
    found = set(re.findall(r'data-url="/netcat_files/391/638/([^".?/]+)\.csv', html))
    if not found:
        raise common.SourceError('на странице ДУМ РТ нет списка CSV — сменилась вёрстка?')
    return found


def parse_csv(text: str) -> dict[dt.date, tuple[list[str], str]]:
    """Дата -> (шесть времён, время в мечетях)."""
    rows = {}
    for line in text.splitlines():
        line = line.strip().lstrip('﻿')
        if not line:
            continue
        cells = line.split(';')
        if len(cells) < 9:
            raise common.SourceError(f'строка CSV короче 9 полей: {line!r}')
        d, m, y = cells[0].split('.')
        date = dt.date(int(y), int(m), int(d))
        suhur_end, in_mosque, sunrise, _zenith, dhuhr, asr, maghrib, isha = (common.hhmm(c) for c in cells[1:9])
        rows[date] = ([suhur_end, sunrise, dhuhr, asr, maghrib, isha], in_mosque)
    return rows


def collect(log) -> int:
    auth = common.authority('ru-tatarstan')
    listed = listed_files()
    known = {p['src'] for p in auth['places']}
    for extra in sorted(listed - known):
        log(f'ДУМ РТ: новый пункт {extra}.csv — добавить координаты в authorities.json')
    written = 0
    for place in auth['places']:
        if place['src'] not in listed:
            log(f'ДУМ РТ: {place["src"]}.csv больше не перечислен на странице, пропускаю')
            continue
        rows = parse_csv(common.http_get(CSV.format(src=place['src'])).decode('utf-8-sig', 'replace'))
        for year in sorted({d.year for d in rows}):
            dates = [d for d in common.year_dates(year) if d in rows]
            if not dates:
                continue
            # Строки идут подряд: таблица начинается с первой даты года, которая
            # есть в CSV, и обрывается на первом пропуске.
            start = dates[0]
            run = []
            d = start
            while d in rows and d.year == year:
                run.append(d)
                d += dt.timedelta(days=1)
            # Графики ДУМ РТ машинные и ровные — правок не делаем, только проверка.
            days = [' '.join(rows[x][0]) for x in run]
            mosque = [rows[x][1] for x in run]
            if common.write_table(
                    auth, place, year, start, days,
                    title=f'ДУМ РТ — время намазов, {place["name"]}',
                    source=CSV.format(src=place['src']),
                    extra={'fajrInMosque': mosque}, jumps=RULES):
                written += 1
    return written
