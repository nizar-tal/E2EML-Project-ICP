# nizar talty
# originally written on the 15th november 2026

import re
from datetime import date

from metrics import normalize


def birth_parts(fields):
    values = [normalize(fields.get(key)) for key in ("birth_year", "birth_month", "birth_day")]
    if not all(re.fullmatch(pattern, value) for pattern, value in zip((r"[0-9]{4}", r"[0-9]{1,2}", r"[0-9]{1,2}"), values)):
        return None
    return tuple(int(value) for value in values)


def check_assertions(fields):
    identifier = normalize(fields.get("id_number"))

    # used for a2 and a3 checks
    parts = birth_parts(fields)

    # this is checking id format has 18 chars with 17 digits and the last char is a digit or X
    a1 = re.fullmatch(r"\d{17}[\dX]", identifier) is not None

    a2, a3 = False, False
    if parts is not None:
        year, month, day = parts
        a2 = a1 and identifier[6:14] == f"{year:04d}{month:02d}{day:02d}"
        try:
            a3 = date(1900, 1, 1) <= date(year, month, day) <= date(2030, 12, 31)
        except ValueError:
            pass
    checks = {"A1": a1, "A2": a2, "A3": a3, "A4": normalize(fields.get("gender")) in {"男", "女"}}
    return {**checks, "all": all(checks.values())}
