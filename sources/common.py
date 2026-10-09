"""Общие части сборщиков: сеть, проверка таблиц, запись файлов.

Формат данных описан в FORMAT.md. Здесь — только то, что нужно всем
сборщикам: скачать, проверить, что таблица правдоподобна, и записать её
в site/v1/<authority>/<place>/<year>.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / 'site' / 'v1'
STATE = ROOT / 'state'
AUTHORITIES = ROOT / 'authorities.json'

UA = 'noor-times/1 (+https://github.com/m65012487-wq/noor-times)'
NAMES = ('Fajr', 'Sunrise', 'Dhuhr', 'Asr', 'Maghrib', 'Isha')


class SourceError(Exception):
    """Источник ответил не тем, чего ждали: формат сменился, данных нет."""


def http_get(url: str, *, tries: int = 3, timeout: int = 40) -> bytes:
    """GET с повторами. Сайты ДУМ отвечают нестабильно, поэтому три попытки
    с паузой; 404 не повторяем — файла просто нет."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(2 + attempt * 3)
    raise SourceError(f'{url}: {last}')


def exists(url: str) -> bool:
    try:
        http_get(url, tries=2)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def hhmm(value: str) -> str:
    """'5:53' -> '05:53'. Всё, что не похоже на время суток, — ошибка."""
    s = value.strip().replace('.', ':')
    h, _, m = s.partition(':')
    if not (h.isdigit() and m.isdigit() and len(m) == 2 and 0 <= int(h) < 24 and 0 <= int(m) < 60):
        raise SourceError(f'не время: {value!r}')
    return f'{int(h):02d}:{m}'


def minutes(value: str) -> int:
    h, m = value.split(':')
    return int(h) * 60 + int(m)


# Сколько минут за сутки может сдвинуться каждое время. Сумерки (Фаджр, Иша)
# в высоких широтах весной и осенью уходят на 5–6 минут в день, полдень —
# меньше чем на минуту. Больше этого — описка или сбой распознавания.
JUMPS = {'Fajr': 8, 'Sunrise': 4, 'Dhuhr': 3, 'Asr': 4, 'Maghrib': 4, 'Isha': 8}


def _delta(a: int, b: int) -> int:
    """Разность времён суток с учётом полуночи: от -720 до 719."""
    return (b - a + 720) % 1440 - 720


def check_days(days: list[str], *, start: dt.date, jumps: dict | None = None) -> list[str]:
    """Правдоподобие таблицы. Возвращает список нарушений (пустой — всё в порядке).

    - в строке шесть времён и они идут по порядку суток;
    - соседние дни отличаются не больше порога JUMPS: у солнца нет скачков,
      а описка или сбой распознавания их даёт.
    Переход Фаджра или Иши через полночь допускается: летом в высоких широтах
    так бывает, и тогда порядок сравнивается по кругу.
    jumps — свои пороги для источника, где скачки — часть правил (у ДУМ РТ
    в мае и августе Фаджр и Иша переходят на летний счёт и обратно).
    """
    limits = {**JUMPS, **(jumps or {})}
    problems = []
    prev = prev_row = None
    for i, row in enumerate(days):
        date = start + dt.timedelta(days=i)
        parts = row.split(' ')
        if len(parts) != 6:
            problems.append(f'{date}: не шесть времён: {row!r}')
            prev = None
            continue
        if '??:??' in parts:
            problems.append(f'{date}: нечитаемое время: {row}')
            prev = None
            continue
        t = [minutes(p) for p in parts]
        # Восход < Зухр < Аср < Магриб — всегда в пределах одних суток.
        if not (t[1] < t[2] < t[3] < t[4]):
            problems.append(f'{date}: порядок времён нарушен: {row}')
        # Фаджр до восхода, Иша после Магриба — с учётом полуночи.
        if (t[1] - t[0]) % 1440 > 360 or (t[5] - t[4]) % 1440 > 360:
            problems.append(f'{date}: Фаджр или Иша вне разумных пределов: {row}')
        if prev:
            for k, name in enumerate(NAMES):
                d = _delta(prev[k], t[k])
                if abs(d) > limits[name]:
                    problems.append(f'{date}: {name} скачет на {d} мин ({prev_row} -> {row})')
        prev, prev_row = t, row
    return problems


def _fmt(m: int) -> str:
    m %= 1440
    return f'{m // 60:02d}:{m % 60:02d}'


def _cell(value: str):
    """Минуты или None для битой ячейки ('11:5', пусто)."""
    try:
        return minutes(hhmm(value))
    except (SourceError, ValueError):
        return None


def repair_days(days: list[list[str]], *, start: dt.date, jumps: dict | None = None):
    """Чинит ошибки ручного ведения графика — то, что видно по самому ряду.

    days — строки по шесть времён (строками 'HH:MM', битые допустимы).
    Возвращает (строки 'HH:MM …', список правок). Правки трёх видов:

    - 'hour': блок дней, сдвинутый ровно на час, — след перевода часов,
      отменённого в 2014 году. В календаре Муфтията РД, например, Аср
      25–31 октября на час раньше соседних дней. Блок сдвигается обратно,
      если после сдвига ряд сходится на обоих краях.
    - 'gap': до трёх дней подряд, которые выбиваются из ряда (описка
      03:37 среди 03:59 и 03:55) или не читаются ('11:5'), когда дни по
      краям между собой согласны. Значения заменяются прямой между краями.

    Всё прочее оставляется как есть — его ловит check_days, и такую таблицу
    лучше не публиковать, чем гадать.
    """
    limits = {**JUMPS, **(jumps or {})}
    n = len(days)
    cols = [[_cell(days[i][k]) for i in range(n)] for k in range(6)]
    repairs = []
    for k, name in enumerate(NAMES):
        s, lim = cols[k], limits[name]
        # Часовые блоки: скачок около ±60 и обратный скачок не дальше 62 дней.
        i = 1
        while i < n:
            if s[i - 1] is None or s[i] is None:
                i += 1
                continue
            jump = _delta(s[i - 1], s[i])
            if not (60 - lim <= abs(jump) <= 60 + lim):
                i += 1
                continue
            for j in range(i + 1, min(n, i + 63)):
                if s[j - 1] is None or s[j] is None:
                    continue
                back = _delta(s[j - 1], s[j])
                if 60 - lim <= abs(back) <= 60 + lim and back * jump < 0:
                    shift = -60 if jump > 0 else 60
                    if abs(_delta(s[i - 1], s[i] + shift)) <= lim and abs(_delta(s[j - 1] + shift, s[j])) <= lim:
                        for t in range(i, j):
                            if s[t] is not None:
                                s[t] = (s[t] + shift) % 1440
                        repairs.append({'kind': 'hour', 'prayer': name, 'shift': shift,
                                        'from': (start + dt.timedelta(days=i)).isoformat(),
                                        'to': (start + dt.timedelta(days=j - 1)).isoformat()})
                        i = j
                    break
            i += 1
        # Короткие сбои: до трёх дней между согласными краями.
        for i in range(1, n - 1):
            for g in (1, 2, 3):
                if i + g >= n or s[i - 1] is None or s[i + g] is None:
                    continue
                total = _delta(s[i - 1], s[i + g])
                if abs(total) > lim * (g + 1):
                    continue
                line = [(s[i - 1] + round(total * (t + 1) / (g + 1))) % 1440 for t in range(g)]
                bad = [t for t in range(g) if s[i + t] is None or abs(_delta(line[t], s[i + t])) > lim]
                # Сбой — когда выбивается именно этот кусок: на краях ряд ровный.
                if bad and (s[i] is None or abs(_delta(s[i - 1], s[i])) > lim):
                    for t in range(g):
                        if s[i + t] is None or abs(_delta(line[t], s[i + t])) > lim:
                            old = days[i + t][k]
                            s[i + t] = line[t]
                            repairs.append({'kind': 'gap', 'prayer': name,
                                            'date': (start + dt.timedelta(days=i + t)).isoformat(),
                                            'from': old, 'to': _fmt(line[t])})
                    break
    out = []
    for i in range(n):
        row = [cols[k][i] for k in range(6)]
        out.append(' '.join(_fmt(v) if v is not None else '??:??' for v in row))
    return out, repairs


def write_json(path: pathlib.Path, data) -> bool:
    """Пишет JSON, только если содержимое изменилось. Возвращает True при записи."""
    text = json.dumps(data, ensure_ascii=False, indent=1) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return True


def write_table(authority: dict, place: dict, year: int, start: dt.date, days: list[str], *,
                title: str, source: str, extra: dict | None = None, repairs: list | None = None,
                jumps: dict | None = None) -> bool:
    """Записывает таблицу года после проверки. Нарушения — SourceError: лучше
    оставить на сайте прошлую версию, чем выложить сбойную."""
    problems = check_days(days, start=start, jumps=jumps)
    if problems:
        raise SourceError(f'{authority["id"]}/{place["id"]}/{year}: ' + '; '.join(problems[:5]))
    data = {
        'authority': authority['id'],
        'title': title,
        'source': source,
        'place': {
            'id': place['id'], 'name': place['name'], 'regions': authority.get('regions', []),
            'lat': place['lat'], 'lng': place['lng'], 'radiusKm': place['radiusKm'],
        },
        'utcOffset': authority['utcOffset'],
        'start': start.isoformat(),
        'days': days,
    }
    if extra:
        for key, values in extra.items():
            if len(values) != len(days):
                raise SourceError(f'extra.{key}: {len(values)} строк против {len(days)}')
        data['extra'] = extra
    if repairs:
        data['repairs'] = repairs
    return write_json(SITE / authority['id'] / place['id'] / f'{year}.json', data)


def load_authorities() -> list[dict]:
    return json.loads(AUTHORITIES.read_text(encoding='utf-8'))['authorities']


def authority(auth_id: str) -> dict:
    for a in load_authorities():
        if a['id'] == auth_id:
            return a
    raise KeyError(auth_id)


def year_dates(year: int):
    d = dt.date(year, 1, 1)
    while d.year == year:
        yield d
        d += dt.timedelta(days=1)


def distance_km(lat1, lng1, lat2, lng2) -> float:
    rad = math.pi / 180
    a = (math.sin((lat2 - lat1) * rad / 2) ** 2
         + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lng2 - lng1) * rad / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def sha1_file(path: pathlib.Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def today_msk() -> dt.date:
    """Дата по Москве: расписание запускается по UTC ночью, а графики — по
    местному времени, и в 01:00 UTC в Москве уже следующий день."""
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).date()
