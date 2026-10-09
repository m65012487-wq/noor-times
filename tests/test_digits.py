"""Распознавание картинок на сверенных вручную месяцах (нужна сеть).

Образцы цифр вырезаны из этих же месяцев, поэтому тест прежде всего ловит
поломку разметки: сетка, лишние пятна, двоеточие. Если картинка за прошлый
месяц исчезла с сайта ДУМ, тест пропускается, а не падает.
"""
import datetime as dt
import urllib.error

import pytest

from sources import common, digits, kbr, moscow, train


@pytest.mark.parametrize('src', [kbr, moscow])
def test_reader_reproduces_the_groundtruth(src):
    truth = train.load_truth(src.GROUNDTRUTH)
    reader = digits.Reader.load(src.READER)
    for year, month in sorted({(d.year, d.month) for d in truth}):
        try:
            image = common.http_get(src.image_url(year, month))
        except (urllib.error.HTTPError, common.SourceError) as e:
            pytest.skip(f'{src.__name__} {year}-{month}: картинки нет ({e})')
        days = src.read_month(image, year, month, reader)
        for i, row in enumerate(days):
            assert row == ' '.join(truth[dt.date(year, month, i + 1)])
