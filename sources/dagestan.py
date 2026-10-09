"""Муфтият Дагестана: графики по 28 городам и районам.

Сайт muftiyatrd.ru подгружает JSON на пункт: /json/namaz/<id>.json. Это
вечный календарь — 365 строк без дат, строка N соответствует N-му дню
невисокосного года. Сам сайт берёт строку «день года − 1» и в високосный
год просит править код вручную («−2»). Мы делаем то же явно: 29 февраля
повторяет 28-е, дальше строки сдвинуты на день.

Поля: namaz_1 — Фаджр, voshod — восход, namaz_2..5 — Зухр, Аср, Магриб, Иша.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import time

from . import common

URL = 'https://muftiyatrd.ru/json/namaz/{src}.json'


def row_index(date: dt.date) -> int:
    """Номер строки вечного календаря для даты."""
    doy = date.timetuple().tm_yday  # 1..366
    if calendar.isleap(date.year) and doy >= 60:
        # 29 февраля (день 60) берёт строку 28-го, дальше — на день меньше.
        return doy - 2
    return doy - 1


def collect(log, years=None) -> int:
    auth = common.authority('ru-dagestan')
    today = common.today_msk()
    years = years or [today.year, today.year + 1]
    written = 0
    skipped = []
    for place in auth['places']:
        try:
            written += collect_place(auth, place, years, log)
        except common.SourceError as e:
            # Ошибки в самом календаре пункта (не сеть и не формат сайта):
            # пункт не публикуется, там считает метод. Остальные — своим чередом.
            skipped.append(place['id'])
            log(f'Муфтият РД {place["id"]}: не публикуется — {e}')
    if len(skipped) > len(auth['places']) // 2:
        raise common.SourceError(f'Муфтият РД: не прошли проверку {len(skipped)} пунктов из {len(auth["places"])}')
    return written


def fetch(src: str) -> list:
    """Календарь пункта. Сервер Муфтията иногда отдаёт пустой ответ с кодом
    200 — тогда пауза и ещё попытка."""
    for attempt in range(3):
        body = common.http_get(URL.format(src=src)).decode('utf-8-sig').strip()
        try:
            return json.loads(body)
        except ValueError:
            time.sleep(3 + attempt * 5)
    raise common.SourceError('сервер отдаёт не JSON')


def collect_place(auth, place, years, log) -> int:
    rows = fetch(place['src'])
    time.sleep(0.5)  # не частить: сайт небольшой
    if len(rows) != 365:
        raise common.SourceError(f'{len(rows)} строк вместо 365')
    # Ячейки как есть: битые ('11:5') чинит или отбраковывает repair_days.
    perpetual = [[str(r.get(k, '')) for k in ('namaz_1', 'voshod', 'namaz_2', 'namaz_3', 'namaz_4', 'namaz_5')]
                 for r in rows]
    written = 0
    for year in years:
        dates = list(common.year_dates(year))
        days, repairs = common.repair_days([perpetual[row_index(d)] for d in dates], start=dates[0])
        if year == years[0]:
            for r in repairs:
                log(f'Муфтият РД {place["id"]}: описка в календаре {r}')
        if common.write_table(
                auth, place, year, dates[0], days,
                title=f'Муфтият РД — время намаза, {place["name"]}',
                source=URL.format(src=place['src']), repairs=repairs):
            written += 1
    return written
