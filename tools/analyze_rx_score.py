#!/usr/bin/env python3.11
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import databases
from akatsuki_pp_py import Beatmap
from akatsuki_pp_py import Calculator

# Находим корневую директорию проекта
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root_dir)
sys.path.insert(0, root_dir)

from app.usecases.rx_performance import calculate_rx_performance
from app.usecases.rx_performance import calculate_aim_value
from app.usecases.rx_performance import calculate_speed_penalty
from app.usecases.rx_performance import calculate_combo_factor
from app.usecases.rx_performance import calculate_miss_penalty
from app.usecases.rx_performance import calculate_difficulty_bonus
from app.objects.beatmap import ensure_osu_file_is_available
from app.constants.gamemodes import GameMode

try:
    import app.settings
except ModuleNotFoundError:
    print("\x1b[;91mMust run from tools/ directory\x1b[m")
    raise

BEATMAPS_PATH = Path.cwd() / ".data/osu"

async def analyze_score(score_id: int, database: databases.Database) -> None:
    # Получаем информацию о скоре из базы данных
    score = await database.fetch_one(
        """\
        SELECT s.*, m.id as map_id, m.max_combo as map_max_combo, m.artist, m.title, m.version,
               u.name as username
        FROM scores s
        INNER JOIN maps m ON s.map_md5 = m.md5
        INNER JOIN users u ON s.userid = u.id
        WHERE s.id = :score_id
        """,
        {"score_id": score_id},
    )

    if not score:
        print(f"Score ID {score_id} not found!")
        return

    # Убеждаемся, что файл карты доступен
    osu_file_available = await ensure_osu_file_is_available(
        score["map_id"],
        expected_md5=score["map_md5"],
    )

    if not osu_file_available:
        print(f"Could not find or download beatmap {score['map_id']}!")
        return

    # Загружаем карту
    beatmap = Beatmap(path=str(BEATMAPS_PATH / f"{score['map_id']}.osu"))

    # Создаем калькулятор
    calculator = Calculator(
        mode=GameMode(score["mode"]).as_vanilla,
        mods=score["mods"],
        combo=score["max_combo"],
        n_geki=score["ngeki"],
        n300=score["n300"],
        n_katu=score["nkatu"],
        n100=score["n100"],
        n50=score["n50"],
        n_misses=score["nmiss"],
    )

    # Получаем базовые значения PP
    attrs = calculator.performance(beatmap)

    # Рассчитываем PP для режима relax
    if score["mode"] == 4:  # rx!std
        new_pp = calculate_rx_performance(
            base_pp=attrs.pp,
            max_combo=score["max_combo"],
            map_max_combo=score["map_max_combo"],
            stars=attrs.difficulty.stars,
            aim_stars=attrs.difficulty.aim,
            speed_stars=attrs.difficulty.speed,
            nmiss=score["nmiss"],
        )
    else:
        new_pp = attrs.pp

    # Выводим детальный анализ
    print("\n=== Анализ скора ===")
    print(f"Карта: {score['artist']} - {score['title']} [{score['version']}]")
    print(f"Игрок: {score['username']}")
    print(f"Моды: {score['mods']}")
    print(f"\nОбщая статистика:")
    print(f"300s: {score['n300']}")
    print(f"100s: {score['n100']}")
    print(f"50s: {score['n50']}")
    print(f"Миссы: {score['nmiss']}")
    print(f"Макс комбо: {score['max_combo']}/{score['map_max_combo']}")
    print(f"Аккуратность: {score['acc']:.2f}%")

    print(f"\nСтатистика сложности:")
    print(f"Звёзды: {attrs.difficulty.stars:.2f}★")
    if score['mode'] == 4:  # rx!std
        print(f"Aim звёзды: {attrs.difficulty.aim:.2f}★")
        print(f"Speed звёзды: {attrs.difficulty.speed:.2f}★")

    print(f"\nПодробный PP анализ:")
    print(f"Базовые PP: {attrs.pp:.2f}")
    if score['mode'] == 4:
        # Получаем все множители
        aim_multi = calculate_aim_value(attrs.difficulty.aim, attrs.difficulty.speed)
        speed_multi = calculate_speed_penalty(attrs.difficulty.speed)
        combo_multi = calculate_combo_factor(score["max_combo"], score["map_max_combo"], attrs.difficulty.stars)
        miss_multi = calculate_miss_penalty(score["nmiss"], attrs.difficulty.stars)
        diff_multi = calculate_difficulty_bonus(attrs.difficulty.stars)
        
        print("\nАнализ множителей:")
        
        # Анализ aim
        print("\n1. Aim анализ:")
        aim_ratio = attrs.difficulty.aim / (attrs.difficulty.speed + 0.1)
        print(f"Множитель: {aim_multi:.3f}x")
        if aim_ratio > 2.5:
            print("Тип карты: Чистый aim")
            if attrs.difficulty.aim > 5.0:
                print("→ Получен бонус +10% за высокую aim сложность")
        elif aim_ratio > 1.8:
            print("Тип карты: Aim-heavy")
            if attrs.difficulty.aim > 4.0:
                print("→ Получен бонус +5% за сложный aim")
        elif aim_ratio < 0.5:
            print("Тип карты: Чистые стримы")
            print("→ Применен штраф -5% из-за низкого aim требования")
        elif aim_ratio < 0.8:
            print("Тип карты: Stream-heavy")
            print("→ Небольшой штраф -2% из-за низкого aim требования")
        else:
            print("Тип карты: Сбалансированный паттерн")
            print("→ Без штрафов, карта хорошо сбалансирована")

        # Анализ speed
        print("\n2. Speed анализ:")
        print(f"Множитель: {speed_multi:.3f}x")
        if speed_multi == 1.0:
            print("→ Базовый множитель для умеренного speed")
        else:
            print(f"→ Получен бонус +{(speed_multi - 1.0) * 100:.1f}% за высокий speed")
            
        # Анализ combo
        print("\n3. Combo анализ:")
        print(f"Множитель: {combo_multi:.3f}x")
        combo_completion = score["max_combo"] / score["map_max_combo"]
        print(f"Процент максимального комбо: {combo_completion * 100:.1f}%")
        if combo_completion == 1.0:
            print("→ Идеальное комбо, без штрафов")
        else:
            lost_pp = (1.0 - combo_multi) * 100
            print(f"→ Потеряно {lost_pp:.1f}% PP из-за неполного комбо")

        # Анализ миссов
        print("\n4. Miss анализ:")
        print(f"Множитель: {miss_multi:.3f}x")
        if score["nmiss"] == 0:
            print("→ Без миссов, без штрафов")
        else:
            lost_pp = (1.0 - miss_multi) * 100
            if attrs.difficulty.stars <= 4.0:
                print("→ Строгий штраф за миссы на легкой карте")
            elif attrs.difficulty.stars <= 6.0:
                print("→ Умеренный штраф за миссы на средней карте")
            elif attrs.difficulty.stars <= 8.0:
                print("→ Мягкий штраф за миссы на сложной карте")
            else:
                print("→ Минимальный штраф за миссы на очень сложной карте")
            print(f"→ Потеряно {lost_pp:.1f}% PP из-за {score['nmiss']} миссов")

        # Анализ сложности
        print("\n5. Бонус сложности:")
        print(f"Множитель: {diff_multi:.3f}x")
        if diff_multi > 1.0:
            bonus_pp = (diff_multi - 1.0) * 100
            print(f"→ Получен бонус +{bonus_pp:.1f}% за высокую сложность карты")
        else:
            print("→ Без бонуса сложности (карта ниже 4.5 звёзд)")

    # Итоговый анализ
    print(f"\nИтоговый результат:")
    print(f"Базовые PP: {attrs.pp:.2f}")
    print(f"Итоговые PP: {new_pp:.2f}")
    diff_pp = new_pp - score["pp"]
    if abs(diff_pp) > 0.01:
        print(f"Разница с текущими PP: {diff_pp:+.2f}")
        if diff_pp > 0:
            print("→ Скор получил больше PP после пересчёта")
        else:
            print("→ Скор получил меньше PP после пересчёта")

async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze score PP calculation with detailed breakdown",
    )
    parser.add_argument(
        "score_id",
        type=int,
        help="Score ID to analyze",
    )

    args = parser.parse_args()

    db = databases.Database(app.settings.DB_DSN)
    await db.connect()

    try:
        await analyze_score(args.score_id, db)
    finally:
        await db.disconnect()

    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
