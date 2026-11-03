"""Natural display labels for synthetic fixtures; provenance lives in metadata/docs."""
from datetime import date

VENUES = ('Ипподром «Север»', 'Ипподром «Волга»', 'Ипподром «Степь»', 'Ипподром «Урал»')
MONTHS = ('январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
          'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь')
MONTHS_GENITIVE = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                   'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')


def competition_title(index: int, day: date, distance: int) -> str:
    """Date/season/distance determine the label without consuming sporting RNG."""
    season = (day.month % 12) // 3
    adjective = ('Зимний', 'Весенний', 'Летний', 'Осенний')[season]
    derby = ('Зимнее', 'Весеннее', 'Летнее', 'Осеннее')[season]
    titles = (
        f'{adjective} кубок',
        f'Большой приз {MONTHS_GENITIVE[day.month - 1]}',
        f'{derby} дерби',
        'Кубок скорости' if distance <= 1600 else 'Приз выносливости',
        'Мемориал сезона',
        'Приз ипподрома',
        'Кубок спринтеров' if distance <= 1200 else 'Приз длинной дистанции' if distance >= 2000 else 'Приз мастерства',
        'Открытый кубок клуба',
    )
    if index % len(titles) == 1:
        return f'Большой приз {MONTHS_GENITIVE[day.month - 1]} {day.year}'
    return f'{titles[index % len(titles)]} · {MONTHS[day.month - 1]} {day.year}'
