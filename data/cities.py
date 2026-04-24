# Список поддерживаемых городов: название → slug DNS Shop.
# Используется для хранения предпочтений пользователя.
# Многогородской парсинг будет добавлен в следующем этапе.

CITIES: dict[str, str] = {
    "Москва": "moscow",
    "Санкт-Петербург": "spb",
    "Новосибирск": "novosibirsk",
    "Екатеринбург": "ekaterinburg",
    "Нижний Новгород": "nizhny-novgorod",
    "Казань": "kazan",
    "Краснодар": "krasnodar",
    "Самара": "samara",
    "Уфа": "ufa",
    "Ростов-на-Дону": "rostov-na-donu",
    "Красноярск": "krasnoyarsk",
    "Воронеж": "voronezh",
    "Пермь": "perm",
    "Волгоград": "volgograd",
    "Омск": "omsk",
}

# Обратный маппинг slug → название
SLUG_TO_CITY: dict[str, str] = {v: k for k, v in CITIES.items()}
