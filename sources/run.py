"""Запуск всех сборщиков: python -m sources.run [имя ...]

Каждый сборщик работает сам по себе: сбой одного не мешает остальным, а
его прежние таблицы остаются на сайте. Код выхода 1, если хоть один упал, —
GitHub пришлёт владельцу письмо о неудачном запуске, а исправные данные к
этому моменту уже записаны.
"""
from __future__ import annotations

import sys
import traceback

from . import build_index, dagestan, kbr, moscow, tatarstan, world

COLLECTORS = {
    'kbr': kbr.collect,
    'tatarstan': tatarstan.collect,
    'dagestan': dagestan.collect,
    'moscow': moscow.collect,
    'singapore': world.singapore,
    'kazakhstan': world.kazakhstan,
}


def main(argv: list[str]) -> int:
    names = argv or list(COLLECTORS)
    failed = []
    for name in names:
        try:
            written = COLLECTORS[name](lambda msg: print(f'  {msg}', flush=True))
            print(f'{name}: записано таблиц {written}', flush=True)
        except Exception:  # noqa: BLE001 — сбой одного источника не должен ронять остальные
            failed.append(name)
            print(f'{name}: СБОЙ', flush=True)
            traceback.print_exc()
    changed = build_index.write()
    print(f'index.json: {"обновлён" if changed else "без изменений"}')
    if failed:
        print('Сбой сборщиков: ' + ', '.join(failed))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
