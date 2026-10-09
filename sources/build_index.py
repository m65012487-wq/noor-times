"""Собирает site/v1/index.json из authorities.json и записанных таблиц.

Индекс строится по файлам на диске, а не по итогам последнего запуска:
если сборщик одного управления упал, его прежние таблицы остаются в
индексе, а не пропадают с сайта.
"""
from __future__ import annotations

import datetime as dt
import json

from . import common

# Служебные поля authorities.json, которые приложению не нужны.
PRIVATE = {'src'}


def build() -> dict:
    authorities = []
    for auth in common.load_authorities():
        places = []
        for place in auth['places']:
            tables = []
            folder = common.SITE / auth['id'] / place['id']
            for path in sorted(folder.glob('*.json')) if folder.exists() else []:
                table = json.loads(path.read_text(encoding='utf-8'))
                tables.append({
                    'year': int(path.stem),
                    'path': f'{auth["id"]}/{place["id"]}/{path.name}',
                    'start': table['start'],
                    'days': len(table['days']),
                    'hash': common.sha1_file(path),
                })
            # Пункт без таблиц (календарь не прошёл проверку) в индекс не идёт:
            # иначе приложение выбрало бы его как ближайший и ушло на метод,
            # хотя в 40 км есть таблица соседнего пункта.
            if tables:
                places.append({**{k: v for k, v in place.items() if k not in PRIVATE}, 'tables': tables})
        authorities.append({**{k: v for k, v in auth.items() if k != 'places'}, 'places': places})
    return {'v': 1, 'authorities': authorities}


def write() -> bool:
    index = build()
    path = common.SITE / 'index.json'
    # Время сборки меняется каждый запуск; чтобы не плодить коммиты без
    # изменений в данных, оно обновляется только вместе с содержимым.
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if {k: v for k, v in old.items() if k != 'generated'} == index:
        return False
    index = {'v': 1, 'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
             'authorities': index['authorities']}
    return common.write_json(path, index)
