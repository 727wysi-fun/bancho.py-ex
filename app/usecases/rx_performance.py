from __future__ import annotations

import math
from typing import TypedDict
from app.objects.beatmap import Beatmap

class RXPerformanceResult(TypedDict):
    pp: float
    sr: float

def sigmoid(x: float, steepness: float = 1.0) -> float:
    """Сигмоидная функция для плавных переходов значений."""
    return 1 / (1 + math.exp(-steepness * x))

def calculate_aim_value(aim_stars: float | None, speed_stars: float | None) -> float:
    """Рассчитывает ценность aim составляющей."""
    if aim_stars is None or speed_stars is None:
        return 1.0
        
    # Балансируем aim и speed
    ratio = aim_stars / (speed_stars + 0.1)  # Избегаем деления на 0
    
    if ratio > 2.5:  # Чистый aim
        # Даем бонус в зависимости от уровня aim
        if aim_stars is not None and aim_stars > 5.0:
            return 1.1  # +10% для сложных aim карт
        else:
            return 1.0  # Без штрафа для обычных aim карт
    elif ratio > 1.8:  # Aim-heavy карты
        if aim_stars is not None and aim_stars > 4.0:
            return 1.05  # +5% для сложных aim-heavy карт
        else:
            return 1.0  # Без штрафа
    elif ratio < 0.5:  # Чистые стримы
        return 0.95  # Минимальный штраф для pure stream (-5%)
    elif ratio < 0.8:  # Stream-heavy карты
        return 0.98  # Почти без штрафа (-2%)
    else:  # Сбалансированные паттерны
        return 1.0  # Без штрафа для смешанных карт

def calculate_speed_penalty(speed_stars: float | None) -> float:
    """Рассчитывает множитель для speed составляющей."""
    if speed_stars is None:
        return 1.0
    
    # Очень умеренный бонус для speed
    if speed_stars <= 2.0:
        return 1.0
    elif speed_stars <= 4.0:
        # Малый линейный бонус до 4 звезд speed (максимум +4%)
        return 1.0 + (speed_stars - 2.0) * 0.02
    else:
        # Фиксированный небольшой бонус для высокого speed
        return 1.04  # Фиксированный +4% бонус

def calculate_combo_factor(combo: int, max_combo: int, stars: float) -> float:
    """Рассчитывает множитель комбо с учетом сложности карты."""
    if max_combo == 0:
        return 1.0
        
    combo_completion = combo / max_combo
    
    # Более строгий множитель для простых карт
    base_importance = 0.4 * (1.0 + sigmoid(stars - 5.5, 0.5))
    
    # Нелинейная зависимость потери PP от процента комбо
    combo_factor = 1.0 - (base_importance * (1.0 - math.pow(combo_completion, 0.8)))
    
    return combo_factor

def calculate_miss_penalty(nmiss: int, stars: float) -> float:
    """Рассчитывает штраф за миссы с учетом сложности карты."""
    if nmiss == 0:
        return 1.0

    # Определяем базовый штраф за мисс в зависимости от сложности
    if stars <= 4.0:
        # Умеренный штраф на легких картах
        base_penalty_per_miss = 0.06  # -6% за каждый мисс
    elif stars <= 6.0:
        # Меньший штраф на средних картах
        base_penalty_per_miss = 0.04  # -4% за каждый мисс
    elif stars <= 8.0:
        # Небольшой штраф на сложных картах
        base_penalty_per_miss = 0.025  # -2.5% за каждый мисс
    else:
        # Минимальный штраф на очень сложных картах
        base_penalty_per_miss = 0.015  # -1.5% за каждый мисс
    
    # Более мягкий рост штрафа с количеством миссов
    penalty = math.exp(-base_penalty_per_miss * nmiss)  # Убрали sqrt для более плавного роста
    
    # Небольшой дополнительный штраф только за первый мисс на легких картах
    if nmiss == 1 and stars <= 5.0:
        penalty *= 0.95  # Всего -5% дополнительно за первый мисс
    
    # Более щадящее минимальное значение для сложных карт
    min_penalty = 0.6 if stars >= 7.0 else 0.4
    return max(penalty, min_penalty)

def calculate_difficulty_bonus(stars: float) -> float:
    """
    Рассчитывает бонус за общую сложность карты.
    С увеличенными бонусами для высоких звезд.
    """
    if stars <= 4.5:  # Снижен порог начала бонусов
        return 1.0
    elif stars <= 6.0:
        # Умеренный бонус от 4.5 до 6.0 звезд
        return 1.0 + (stars - 4.5) * 0.04  # До +6% на 6.0 звездах
    else:
        # Повышенные бонусы после 6.0 звезд
        base = 1.06  # +6% от предыдущего диапазона
        extra = min((stars - 6.0) * 0.025, 0.14)  # До +14% дополнительно
        return base + extra

def calculate_rx_performance(
    base_pp: float,
    max_combo: int,
    map_max_combo: int,
    stars: float,
    aim_stars: float | None,
    speed_stars: float | None,
    nmiss: int,
) -> float:
    """
    Комплексный расчет PP для режима Relax с учетом множества факторов:
    - Нелинейная зависимость от aim/speed соотношения
    - Экспоненциальный штраф speed составляющей
    - Динамический множитель комбо зависящий от сложности
    - Прогрессивный штраф за миссы с учетом сложности
    - Бонус за общую сложность карты
    """
    # Рассчитываем все компоненты
    aim_multiplier = calculate_aim_value(aim_stars, speed_stars)
    speed_penalty = calculate_speed_penalty(speed_stars)
    combo_factor = calculate_combo_factor(max_combo, map_max_combo, stars)
    miss_penalty = calculate_miss_penalty(nmiss, stars)
    difficulty_bonus = calculate_difficulty_bonus(stars)
    
    # Применяем все множители
    final_pp = (
        base_pp *
        aim_multiplier *  # Множитель aim (1.0 - 2.0)
        speed_penalty *   # Штраф за speed (0.2 - 1.0)
        combo_factor *    # Влияние комбо (0.6 - 1.0)
        miss_penalty *    # Штраф за миссы (0.0 - 1.0)
        difficulty_bonus  # Бонус за сложность (1.0 - 1.5)
    )
    
    # Очень строгое ограничение максимального PP
    if stars >= 7.0:
        # Минимальное увеличение для сложных карт
        max_multiplier = min(1.15 + (stars - 7.0) * 0.02, 1.25)
    else:
        max_multiplier = 1.15
        
    if final_pp > base_pp * max_multiplier:
        final_pp = base_pp * max_multiplier
        
    return final_pp