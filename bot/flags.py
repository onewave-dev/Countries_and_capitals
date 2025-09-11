"""Utility helpers for country flags."""
from __future__ import annotations

from functools import lru_cache

try:  # optional dependency
    import country_converter as coco  # type: ignore
    _converter = coco.CountryConverter(language="ru")  # type: ignore[misc]
except Exception:  # pragma: no cover - library may be missing
    coco = None  # type: ignore
    _converter = None  # type: ignore

# Fallback ISO alpha-2 codes for Russian country names. This allows
# flag generation even when :mod:`country_converter` is not installed or
# fails to recognise a particular name.
ISO_CODES: dict[str, str] = {
    "Алжир": "DZ",
    "Ангола": "AO",
    "Бенин": "BJ",
    "Ботсвана": "BW",
    "Буркина-Фасо": "BF",
    "Бурунди": "BI",
    "Кабо-Верде": "CV",
    "Камерун": "CM",
    "Центральноафриканская Республика": "CF",
    "Чад": "TD",
    "Коморы": "KM",
    "Республика Конго": "CG",
    "Демократическая Республика Конго": "CD",
    "Кот-д’Ивуар": "CI",
    "Джибути": "DJ",
    "Египет": "EG",
    "Экваториальная Гвинея": "GQ",
    "Эритрея": "ER",
    "Эсватини": "SZ",
    "Эфиопия": "ET",
    "Габон": "GA",
    "Гамбия": "GM",
    "Гана": "GH",
    "Гвинея": "GN",
    "Гвинея-Бисау": "GW",
    "Кения": "KE",
    "Лесото": "LS",
    "Либерия": "LR",
    "Ливия": "LY",
    "Мадагаскар": "MG",
    "Малави": "MW",
    "Мали": "ML",
    "Мавритания": "MR",
    "Маврикий": "MU",
    "Марокко": "MA",
    "Мозамбик": "MZ",
    "Намибия": "NA",
    "Нигер": "NE",
    "Нигерия": "NG",
    "Руанда": "RW",
    "Сан-Томе и Принсипи": "ST",
    "Сенегал": "SN",
    "Сейшелы": "SC",
    "Сьерра-Леоне": "SL",
    "Сомали": "SO",
    "Южная Африка": "ZA",
    "Южный Судан": "SS",
    "Судан": "SD",
    "Танзания": "TZ",
    "Того": "TG",
    "Тунис": "TN",
    "Уганда": "UG",
    "Замбия": "ZM",
    "Зимбабве": "ZW",
    "Афганистан": "AF",
    "Бахрейн": "BH",
    "Бангладеш": "BD",
    "Бутан": "BT",
    "Бруней": "BN",
    "Мьянма": "MM",
    "Камбоджа": "KH",
    "Китай": "CN",
    "Кипр": "CY",
    "Грузия": "GE",
    "Индия": "IN",
    "Индонезия": "ID",
    "Иран": "IR",
    "Ирак": "IQ",
    "Япония": "JP",
    "Иордания": "JO",
    "Казахстан": "KZ",
    "Кувейт": "KW",
    "Кыргызстан": "KG",
    "Лаос": "LA",
    "Ливан": "LB",
    "Малайзия": "MY",
    "Мальдивы": "MV",
    "Монголия": "MN",
    "Непал": "NP",
    "Северная Корея": "KP",
    "Оман": "OM",
    "Пакистан": "PK",
    "Филиппины": "PH",
    "Катар": "QA",
    "Южная Корея": "KR",
    "Саудовская Аравия": "SA",
    "Сингапур": "SG",
    "Шри-Ланка": "LK",
    "Сирия": "SY",
    "Таджикистан": "TJ",
    "Таиланд": "TH",
    "Туркменистан": "TM",
    "Объединенные Арабские Эмираты": "AE",
    "Узбекистан": "UZ",
    "Вьетнам": "VN",
    "Йемен": "YE",
    "Албания": "AL",
    "Андорра": "AD",
    "Австрия": "AT",
    "Беларусь": "BY",
    "Бельгия": "BE",
    "Босния и Герцеговина": "BA",
    "Болгария": "BG",
    "Хорватия": "HR",
    "Чехия": "CZ",
    "Дания": "DK",
    "Эстония": "EE",
    "Финляндия": "FI",
    "Франция": "FR",
    "Германия": "DE",
    "Греция": "GR",
    "Венгрия": "HU",
    "Исландия": "IS",
    "Ирландия": "IE",
    "Италия": "IT",
    "Латвия": "LV",
    "Лихтенштейн": "LI",
    "Литва": "LT",
    "Люксембург": "LU",
    "Северная Македония": "MK",
    "Мальта": "MT",
    "Молдова": "MD",
    "Монако": "MC",
    "Черногория": "ME",
    "Нидерланды": "NL",
    "Норвегия": "NO",
    "Польша": "PL",
    "Португалия": "PT",
    "Румыния": "RO",
    "Россия": "RU",
    "Сан-Марино": "SM",
    "Сербия": "RS",
    "Словакия": "SK",
    "Словения": "SI",
    "Испания": "ES",
    "Швеция": "SE",
    "Швейцария": "CH",
    "Украина": "UA",
    "Ватикан": "VA",
    "Великобритания": "GB",
    "Антигуа и Барбуда": "AG",
    "Багамы": "BS",
    "Барбадос": "BB",
    "Белиз": "BZ",
    "Канада": "CA",
    "Коста-Рика": "CR",
    "Куба": "CU",
    "Доминика": "DM",
    "Доминиканская Республика": "DO",
    "Сальвадор": "SV",
    "Гренада": "GD",
    "Гватемала": "GT",
    "Гаити": "HT",
    "Гондурас": "HN",
    "Ямайка": "JM",
    "Мексика": "MX",
    "Никарагуа": "NI",
    "Панама": "PA",
    "Соединенные Штаты Америки": "US",
    "Сент-Китс и Невис": "KN",
    "Сент-Люсия": "LC",
    "Сент-Винсент и Гренадины": "VC",
    "Аргентина": "AR",
    "Боливия": "BO",
    "Бразилия": "BR",
    "Чили": "CL",
    "Колумбия": "CO",
    "Эквадор": "EC",
    "Гайана": "GY",
    "Парагвай": "PY",
    "Перу": "PE",
    "Суринам": "SR",
    "Уругвай": "UY",
    "Венесуэла": "VE",
    "Австралия": "AU",
    "Федеративные Штаты Микронезии": "FM",
    "Фиджи": "FJ",
    "Кирибати": "KI",
    "Маршалловы Острова": "MH",
    "Науру": "NR",
    "Новая Зеландия": "NZ",
    "Палау": "PW",
    "Папуа-Новая Гвинея": "PG",
    "Самоа": "WS",
    "Соломоновы Острова": "SB",
    "Тонга": "TO",
    "Тувалу": "TV",
    "Вануату": "VU",
}


def _code_to_flag(code: str) -> str:
    """Convert ISO alpha-2 country code to an emoji flag."""
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code.upper())


@lru_cache(maxsize=None)
def get_country_flag(country: str) -> str:
    """Return emoji flag for given country name.

    Uses :mod:`country_converter` if available to translate the country name
    (in various languages, including Russian) into an ISO alpha-2 code.  A
    fallback dictionary is used if the library is missing or cannot resolve the
    name, so the function attempts to return a flag whenever possible.
    """

    if not country:
        return ""

    if _converter is not None:
        try:
            code = _converter.convert(names=country, to="ISO2", not_found=None)
            if isinstance(code, str) and len(code) == 2:
                return _code_to_flag(code)
        except Exception:
            pass

    code = ISO_CODES.get(country)
    if code:
        return _code_to_flag(code)
    return ""
