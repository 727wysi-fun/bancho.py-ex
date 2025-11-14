#!/usr/bin/env python3.11
from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from collections.abc import Awaitable
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import TypeVar
from datetime import datetime
import jinja2

import databases
from akatsuki_pp_py import Beatmap
from akatsuki_pp_py import Calculator
from redis import asyncio as aioredis

sys.path.insert(0, os.path.abspath(os.pardir))
os.chdir(os.path.abspath(os.pardir))

from app.usecases.rx_performance import calculate_rx_performance

try:
    import app.settings
    import app.state.services
    from app.constants.gamemodes import GameMode
    from app.constants.mods import Mods
    from app.constants.privileges import Privileges
    from app.objects.beatmap import ensure_osu_file_is_available
except ModuleNotFoundError:
    print("\x1b[;91mMust run from tools/ directory\x1b[m")
    raise

T = TypeVar("T")

debug_mode_enabled = True

DEBUG = True

BEATMAPS_PATH = Path.cwd() / ".data/osu"


@dataclass
class Context:
    database: databases.Database
    redis: aioredis.Redis
    beatmaps: dict[int, Beatmap] = field(default_factory=dict)
    pp_changes: list[dict[str, Any]] = field(default_factory=list)  # Для хранения изменений PP


def divide_chunks(values: list[T], n: int) -> Iterator[list[T]]:
    for i in range(0, len(values), n):
        yield values[i : i + n]

async def recalculate_score(
    score: dict[str, Any],
    beatmap_path: Path,
    ctx: Context,
) -> None:
    try:
        beatmap = ctx.beatmaps.get(score["map_id"])
        if beatmap is None:
            beatmap = Beatmap(path=str(beatmap_path))
            ctx.beatmaps[score["map_id"]] = beatmap

        calculator = Calculator(
            mode=GameMode(score["mode"]).as_vanilla,
            mods=score["mods"],
            combo=score["max_combo"],
            n_geki=score["ngeki"],  # Mania 320s
            n300=score["n300"],
            n_katu=score["nkatu"],  # Mania 200s, Catch tiny droplets
            n100=score["n100"],
            n50=score["n50"],
            n_misses=score["nmiss"],
        )
        # Получаем max_combo карты из базы данных
        map_info = await ctx.database.fetch_one(
            "SELECT max_combo FROM maps WHERE id = :map_id",
            {"map_id": score["map_id"]},
        )
        map_max_combo = map_info["max_combo"] if map_info else score["max_combo"]
        
        attrs = calculator.performance(beatmap)
        
        new_pp: float
        # Используем наш RX калькулятор для режима relax
        if score["mode"] == 4:  # rx!std
            new_pp = calculate_rx_performance(
                base_pp=attrs.pp,
                max_combo=score["max_combo"],
                map_max_combo=map_max_combo,
                stars=attrs.difficulty.stars,
                aim_stars=attrs.difficulty.aim,
                speed_stars=attrs.difficulty.speed,
                nmiss=score["nmiss"],
            )
        else:
            new_pp = attrs.pp
            
        if math.isnan(new_pp) or math.isinf(new_pp):
            new_pp = 0.0

        await ctx.database.execute(
            "UPDATE scores SET pp = :new_pp WHERE id = :id",
            {"new_pp": new_pp, "id": score["id"]},
        )

        if debug_mode_enabled:
            print(
                f"Recalculated score ID {score['id']} ({score['pp']:.3f}pp -> {new_pp:.3f}pp)",
            )
            
    except Exception as e:
        # Log the error and continue processing other scores
        print(f"Failed to recalculate score ID {score['id']}: {e}")


async def process_score_chunk(
    chunk: list[dict[str, Any]],
    ctx: Context,
) -> None:
    tasks: list[Awaitable[None]] = []
    for score in chunk:
        osu_file_available = await ensure_osu_file_is_available(
            score["map_id"],
            expected_md5=score["map_md5"],
        )
        if osu_file_available:
            tasks.append(
                recalculate_score(
                    score,
                    BEATMAPS_PATH / f"{score['map_id']}.osu",
                    ctx,
                ),
            )

    await asyncio.gather(*tasks)


async def recalculate_user(
    id: int,
    game_mode: GameMode,
    ctx: Context,
) -> None:
    # Получаем старое значение PP
    old_stats = await ctx.database.fetch_one(
        "SELECT pp, acc FROM stats WHERE id = :id AND mode = :mode",
        {"id": id, "mode": game_mode},
    )
    old_pp = old_stats["pp"] if old_stats else 0

    best_scores = await ctx.database.fetch_all(
        "SELECT s.pp, s.acc FROM scores s "
        "INNER JOIN maps m ON s.map_md5 = m.md5 "
        "WHERE s.userid = :user_id AND s.mode = :mode "
        "AND s.status = 2 AND m.status IN (2, 3) "  # ranked, approved
        "ORDER BY s.pp DESC",
        {"user_id": id, "mode": game_mode},
    )

    total_scores = len(best_scores)
    if not total_scores:
        return

    # calculate new total weighted accuracy
    weighted_acc = sum(row["acc"] * 0.95**i for i, row in enumerate(best_scores))
    bonus_acc = 100.0 / (20 * (1 - 0.95**total_scores))
    acc = (weighted_acc * bonus_acc) / 100

    # calculate new total weighted pp
    weighted_pp = sum(row["pp"] * 0.95**i for i, row in enumerate(best_scores))
    bonus_pp = 416.6667 * (1 - 0.9994**total_scores)
    pp = round(weighted_pp + bonus_pp)

    # Получаем имя пользователя
    user_info = await ctx.database.fetch_one(
        "SELECT name FROM users WHERE id = :id",
        {"id": id},
    )
    username = user_info["name"] if user_info else f"User {id}"

    # Сохраняем изменение PP для отчета
    pp_change = {
        "user_id": id,
        "username": username,
        "mode": game_mode.value,
        "old_pp": old_pp,
        "new_pp": pp,
        "pp_change": pp - old_pp,
        "pp_change_percent": ((pp - old_pp) / old_pp * 100) if old_pp > 0 else 0
    }
    ctx.pp_changes.append(pp_change)

    await ctx.database.execute(
        "UPDATE stats SET pp = :pp, acc = :acc WHERE id = :id AND mode = :mode",
        {"pp": pp, "acc": acc, "id": id, "mode": game_mode},
    )

    user_info = await ctx.database.fetch_one(
        "SELECT country, priv FROM users WHERE id = :id",
        {"id": id},
    )
    if user_info is None:
        raise Exception(f"Unknown user ID {id}?")

    if user_info["priv"] & Privileges.UNRESTRICTED:
        await ctx.redis.zadd(
            f"bancho:leaderboard:{game_mode.value}",
            {str(id): pp},
        )

        await ctx.redis.zadd(
            f"bancho:leaderboard:{game_mode.value}:{user_info['country']}",
            {str(id): pp},
        )
        
    if debug_mode_enabled:
        print(f"Recalculated user ID {id} ({pp:.3f}pp, {acc:.3f}%)")

async def process_user_chunk(
    chunk: list[int],
    game_mode: GameMode,
    ctx: Context,
) -> None:
    tasks: list[Awaitable[None]] = []
    for id in chunk:
        tasks.append(recalculate_user(id, game_mode, ctx))

    await asyncio.gather(*tasks)


async def recalculate_mode_users(mode: GameMode, ctx: Context) -> None:
    user_ids = [
        row["id"] for row in await ctx.database.fetch_all("SELECT id FROM users")
    ]

    for id_chunk in divide_chunks(user_ids, 100):
        await process_user_chunk(id_chunk, mode, ctx)


async def recalculate_mode_scores(mode: GameMode, ctx: Context) -> None:
    scores = [
        dict(row)
        for row in await ctx.database.fetch_all(
            """\
            SELECT scores.id, scores.mode, scores.mods, scores.map_md5,
              scores.pp, scores.acc, scores.max_combo,
              scores.ngeki, scores.n300, scores.nkatu, scores.n100, scores.n50, scores.nmiss,
              maps.id as `map_id`
            FROM scores
            INNER JOIN maps ON scores.map_md5 = maps.md5
            WHERE scores.status = 2
              AND scores.mode = :mode
            ORDER BY scores.pp DESC
            """,
            {"mode": mode},
        )
    ]

    for score_chunk in divide_chunks(scores, 100):
        await process_score_chunk(score_chunk, ctx)


def generate_report(pp_changes: list[dict[str, Any]], mode: int) -> None:
    """Генерирует HTML отчет с изменениями PP."""
    # Подготовка статистики
    filtered_changes = [c for c in pp_changes if c["mode"] == mode]
    if not filtered_changes:
        return

    stats = {
        "total_users": len(filtered_changes),
        "avg_pp_change": sum(c["pp_change"] for c in filtered_changes) / len(filtered_changes),
        "max_pp_gain": max(c["pp_change"] for c in filtered_changes),
        "max_pp_loss": min(c["pp_change"] for c in filtered_changes),
    }

    # Сортировка по абсолютному значению изменения PP
    filtered_changes.sort(key=lambda x: abs(x["pp_change"]), reverse=True)

    # Загрузка шаблона и генерация отчета
    template_loader = jinja2.FileSystemLoader("tools/templates")
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template("pp_changes.html")

    # Генерация HTML
    output = template.render(
        pp_changes=filtered_changes,
        total_users=stats["total_users"],
        avg_pp_change=f"{stats['avg_pp_change']:.2f}",
        max_pp_gain=f"{stats['max_pp_gain']:.2f}",
        max_pp_loss=f"{stats['max_pp_loss']:.2f}"
    )

    # Сохранение отчета
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"tools/reports/pp_changes_mode{mode}_{timestamp}.html"
    os.makedirs("tools/reports", exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    
    print(f"\nReport generated: {output_path}")

async def main(argv: Sequence[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Recalculate performance for scores and/or stats",
    )

    parser.add_argument(
        "-d",
        "--debug",
        help="Enable debug logging",
        action="store_true",
    )
    parser.add_argument(
        "--no-scores",
        help="Disable recalculating scores",
        action="store_true",
    )
    parser.add_argument(
        "--no-stats",
        help="Disable recalculating user stats",
        action="store_true",
    )
    parser.add_argument(
        "--no-report",
        help="Disable generating HTML report",
        action="store_true",
    )

    parser.add_argument(
        "-m",
        "--mode",
        nargs=argparse.ONE_OR_MORE,
        required=False,
        default=["0", "1", "2", "3", "4", "5", "6", "8"],
        # would love to do things like "vn!std", but "!" will break interpretation
        choices=["0", "1", "2", "3", "4", "5", "6", "8"],
    )
    args = parser.parse_args(argv)

    global debug_mode_enabled
    debug_mode_enabled = args.debug

    db = databases.Database(app.settings.DB_DSN)
    await db.connect()

    redis = await aioredis.from_url(app.settings.REDIS_DSN)  # type: ignore[no-untyped-call]

    ctx = Context(db, redis)

    for mode in args.mode:
        mode = GameMode(int(mode))

        if not args.no_scores:
            await recalculate_mode_scores(mode, ctx)

        if not args.no_stats:
            await recalculate_mode_users(mode, ctx)

    # Генерация отчета для каждого режима
    if not args.no_report:
        for mode in map(int, args.mode):
            generate_report(ctx.pp_changes, mode)

    await app.state.services.http_client.aclose()
    await db.disconnect()
    await redis.aclose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
