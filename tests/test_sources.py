"""Проверки без сети: правдоподобие таблиц, починка ручных графиков, разбор форматов."""
import datetime as dt

import pytest

from sources import common, dagestan, tatarstan

START = dt.date(2026, 3, 1)


def smooth(n=10, base=('05:00', '06:30', '12:10', '15:20', '18:00', '19:30'), step=1):
    """Ровный ряд: каждое время сдвигается на step минут в день."""
    rows = []
    for i in range(n):
        rows.append([common._fmt(common.minutes(t) + i * step) for t in base])
    return rows


def test_check_days_accepts_a_smooth_table():
    assert common.check_days([' '.join(r) for r in smooth()], start=START) == []


def test_check_days_catches_a_jump_and_disorder():
    rows = smooth()
    rows[4][3] = '15:40'
    problems = common.check_days([' '.join(r) for r in rows], start=START)
    assert any('Asr' in p for p in problems)
    rows = smooth()
    rows[2][1], rows[2][2] = rows[2][2], rows[2][1]
    assert any('порядок' in p for p in common.check_days([' '.join(r) for r in rows], start=START))


def test_check_days_allows_fajr_after_midnight_and_wider_rules():
    rows = [['00:58', '02:59', '12:00', '17:35', '20:33', '22:03'],
            ['23:54', '03:01', '12:00', '17:34', '20:31', '22:00']]
    days = [' '.join(r) for r in rows]
    assert any('Fajr' in p for p in common.check_days(days, start=START))
    assert common.check_days(days, start=START, jumps={'Fajr': 130}) == []


def test_repair_fixes_a_typo_and_an_unreadable_cell():
    rows = smooth()
    rows[4][0] = '04:37'      # описка: −23 минуты среди ровного ряда
    rows[6][2] = '11:5'       # нечитаемая ячейка
    days, repairs = common.repair_days(rows, start=START)
    assert common.check_days(days, start=START) == []
    assert {(r['prayer'], r['kind']) for r in repairs} == {('Fajr', 'gap'), ('Dhuhr', 'gap')}
    assert days[4].split()[0] == common._fmt(common.minutes('05:00') + 4)


def test_repair_shifts_an_hour_block_back():
    rows = smooth(30)
    for i in range(10, 17):   # неделя Асра на час раньше — след перевода часов
        rows[i][3] = common._fmt(common.minutes(rows[i][3]) - 60)
    days, repairs = common.repair_days(rows, start=START)
    assert common.check_days(days, start=START) == []
    assert repairs == [{'kind': 'hour', 'prayer': 'Asr', 'shift': 60,
                        'from': '2026-03-11', 'to': '2026-03-17'}]


def test_repair_leaves_a_real_step_alone():
    rows = smooth(20)
    for i in range(8, 20):    # постоянный сдвиг на 11 минут — не описка
        rows[i][0] = common._fmt(common.minutes(rows[i][0]) - 11)
    days, _ = common.repair_days(rows, start=START)
    assert common.check_days(days, start=START)


def test_dagestan_perpetual_calendar_in_leap_and_common_years():
    assert dagestan.row_index(dt.date(2026, 1, 1)) == 0
    assert dagestan.row_index(dt.date(2026, 12, 31)) == 364
    assert dagestan.row_index(dt.date(2028, 2, 28)) == 58
    assert dagestan.row_index(dt.date(2028, 2, 29)) == 58
    assert dagestan.row_index(dt.date(2028, 3, 1)) == 59
    assert dagestan.row_index(dt.date(2028, 12, 31)) == 364


def test_tatarstan_csv_columns():
    text = '﻿09.10.2026;03:58;04:31;06:02;11:31;12:00;15:01;16:59;18:40\n10.10.2026;4:00;4:33;6:04;11:31;12:00;14:59;16:57;18:38;12:52\n'
    rows = tatarstan.parse_csv(text)
    assert rows[dt.date(2026, 10, 9)] == (['03:58', '06:02', '12:00', '15:01', '16:59', '18:40'], '04:31')
    assert rows[dt.date(2026, 10, 10)][0][0] == '04:00'


@pytest.mark.parametrize('value', ['24:00', '12:60', '1200', ''])
def test_hhmm_rejects_garbage(value):
    with pytest.raises(common.SourceError):
        common.hhmm(value)
