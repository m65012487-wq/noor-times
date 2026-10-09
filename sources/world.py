"""Управления за пределами России с открытыми данными.

- Сингапур, MUIS: data.gov.sg, коллекция «Muslim Prayer Timetables» — по
  набору на год. Годы находятся сами по метаданным наборов коллекции.
- Казахстан, ДУМК: api.muftyat.kz отдаёт год целиком для города из своего
  списка (координаты нужно передавать ровно как в списке). Берём крупные
  города; остальные места страны дальше radiusKm уходят на метод.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import time

from . import common

SG_COLLECTION = 'https://api-production.data.gov.sg/v2/public/api/collections/2312/metadata'
SG_META = 'https://api-production.data.gov.sg/v2/public/api/datasets/{id}/metadata'
SG_DOWNLOAD = 'https://api-open.data.gov.sg/v1/public/api/datasets/{id}/poll-download'
KZ_YEAR = 'https://api.muftyat.kz/prayer-times/{year}/{coords}'


def _json(url: str):
    return json.loads(common.http_get(url).decode('utf-8'))


def _rows_to_table(by_date: dict[dt.date, list[str]], year: int):
    dates = [d for d in common.year_dates(year) if d in by_date]
    if not dates:
        return None, []
    start, days, d = dates[0], [], dates[0]
    while d in by_date and d.year == year:
        days.append(' '.join(by_date[d]))
        d += dt.timedelta(days=1)
    return start, days


def singapore(log) -> int:
    auth = common.authority('sg-muis')
    place = auth['places'][0]
    collection = _json(SG_COLLECTION)['data']['collectionMetadata']
    written = 0
    for dataset in collection['childDatasets']:
        meta = _json(SG_META.format(id=dataset))['data']
        # Годовые наборы называются «Muslim Prayer Timetable 2026»; сводный
        # набор за несколько лет пропускаем — в нём часть строк в 12-часовом виде.
        m = re.fullmatch(r'Muslim Prayer Timetable (\d{4})', meta['name'].strip())
        if not m:
            continue
        year = int(m.group(1))
        # Прошлые годы не нужны, а их выдача на data.gov.sg бывает очень медленной.
        if year < common.today_msk().year:
            continue
        # Выгрузка CSV по ссылке из poll-download: постраничный datastore_search
        # на годовом наборе упирается в таймауты.
        link = _json(SG_DOWNLOAD.format(id=dataset))['data']['url']
        records = csv.DictReader(io.StringIO(common.http_get(link).decode('utf-8-sig')))
        by_date = {}
        for r in records:
            by_date[dt.date.fromisoformat(r['Date'])] = [
                common.hhmm(r[k]) for k in ('Subuh', 'Syuruk', 'Zohor', 'Asar', 'Maghrib', 'Isyak')]
        start, days = _rows_to_table(by_date, year)
        if start and common.write_table(auth, place, year, start, days,
                                        title=f'MUIS — Muslim Prayer Timetable {year}',
                                        source=f'https://data.gov.sg/datasets/{dataset}/view'):
            written += 1
    return written


def kazakhstan(log) -> int:
    auth = common.authority('kz-dumk')
    today = common.today_msk()
    written = 0
    skipped = []
    for place in auth['places']:
        for year in (today.year, today.year + 1):
            try:
                data = _json(KZ_YEAR.format(year=year, coords=place['src']))
            except Exception as e:  # noqa: BLE001 — 404 на следующий год, пока его нет
                if year == today.year:
                    skipped.append(place['id'])
                    log(f'ДУМК {place["id"]} {year}: {e}')
                continue
            by_date = {}
            for r in data.get('result') or []:
                by_date[dt.date.fromisoformat(r['Date'])] = [
                    common.hhmm(r[k]) for k in ('fajr', 'sunrise', 'dhuhr', 'asr', 'maghrib', 'isha')]
            start, days = _rows_to_table(by_date, year)
            if start and common.write_table(auth, place, year, start, days,
                                            title=f'ДУМК — уақыт кестесі, {place["name"]}',
                                            source=KZ_YEAR.format(year=year, coords=place['src'])):
                written += 1
            time.sleep(0.3)
    if len(skipped) > len(auth['places']) // 2:
        raise common.SourceError(f'ДУМК: не получены {len(skipped)} городов из {len(auth["places"])}')
    return written
