from __future__ import annotations

import asyncio
import time
from datetime import datetime
from datetime import timedelta
from typing import Any

import app.packets
import app.settings
import app.state
from app.constants.privileges import Privileges
from app.logging import Ansi
from app.logging import log

OSU_CLIENT_MIN_PING_INTERVAL = 300000 // 1000  # defined by osu!


async def initialize_housekeeping_tasks() -> None:
    """Create tasks for each housekeeping tasks."""
    log("Initializing housekeeping tasks.", Ansi.LCYAN)

    loop = asyncio.get_running_loop()

    app.state.sessions.housekeeping_tasks.update(
        {
            loop.create_task(task)
            for task in (
                _remove_expired_donation_privileges(interval=30 * 60),
                _update_bot_status(interval=5 * 60),
                _disconnect_ghosts(interval=OSU_CLIENT_MIN_PING_INTERVAL // 3),
                daily_challenge_loop(),
            )
        },
    )


async def _remove_expired_donation_privileges(interval: int) -> None:
    """Remove donation privileges from users with expired sessions."""
    while True:
        if app.settings.DEBUG:
            log("Removing expired donation privileges.", Ansi.LMAGENTA)

        expired_donors = await app.state.services.database.fetch_all(
            "SELECT id FROM users "
            "WHERE donor_end <= UNIX_TIMESTAMP() "
            "AND priv & :donor_priv",
            {"donor_priv": Privileges.DONATOR.value},
        )

        for expired_donor in expired_donors:
            player = await app.state.sessions.players.from_cache_or_sql(
                id=expired_donor["id"],
            )

            assert player is not None

            # TODO: perhaps make a `revoke_donor` method?
            await player.remove_privs(Privileges.DONATOR)
            player.donor_end = 0
            await app.state.services.database.execute(
                "UPDATE users SET donor_end = 0 WHERE id = :id",
                {"id": player.id},
            )

            if player.is_online:
                player.enqueue(
                    app.packets.notification("Your supporter status has expired."),
                )

            log(f"{player}'s supporter status has expired.", Ansi.LMAGENTA)

        await asyncio.sleep(interval)


async def _disconnect_ghosts(interval: int) -> None:
    """Actively disconnect users above the
    disconnection time threshold on the osu! server."""
    while True:
        await asyncio.sleep(interval)
        current_time = time.time()

        for player in app.state.sessions.players:
            if current_time - player.last_recv_time > OSU_CLIENT_MIN_PING_INTERVAL:
                log(f"Auto-dced {player}.", Ansi.LMAGENTA)
                player.logout()


async def _update_bot_status(interval: int) -> None:
    """Re roll the bot status, every `interval`."""
    while True:
        await asyncio.sleep(interval)
        app.packets.bot_stats.cache_clear()


async def daily_challenge_loop() -> None:
    """Main loop for managing daily challenges."""
    while True:
        try:
            await _check_and_update_challenges()
        except Exception as e:
            log(f"Daily Challenge: Error in loop: {e}", Ansi.LRED)

        # Check every 60 seconds
        await asyncio.sleep(60)


async def _check_and_update_challenges() -> None:
    """Check current challenge status and create new ones if needed."""
    # First, deactivate any expired challenges
    await _deactivate_expired_challenges()

    # Then check if we need to create a new one
    active_challenge = await _get_active_challenge()

    if active_challenge:
        end_time = active_challenge["end_time"]
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time)
        
        # Get current time from database to ensure timezone consistency
        db_now = await app.state.services.database.fetch_one("SELECT NOW() as now")
        now = db_now["now"]
        
        time_remaining = (end_time - now).total_seconds() / 3600

        log(
            f"Daily Challenge: end_time={end_time}, now={now}, diff={time_remaining:.1f}h",
            Ansi.LYELLOW,
        )
        log(
            f"Daily Challenge: Active challenge for map MD5 "
            f"{active_challenge['map_md5'][:8]}..., "
            f"{time_remaining:.1f} hours left",
            Ansi.LYELLOW,
        )
    else:
        log("Daily Challenge: No active challenge found, creating new one", Ansi.LCYAN)
        await _create_new_challenge()


async def _get_active_challenge() -> dict[str, Any] | None:
    """Get current active challenge if it exists."""
    result = await app.state.services.database.fetch_one(
        """
        SELECT id, map_md5, start_time, end_time, mode
        FROM daily_challenges
        WHERE active = 1
        AND start_time <= NOW()
        AND end_time > NOW()
        ORDER BY start_time DESC
        LIMIT 1
        """,
    )
    return result


async def _deactivate_expired_challenges() -> None:
    """Mark expired challenges as inactive."""
    await app.state.services.database.execute(
        """
        UPDATE daily_challenges
        SET active = 0
        WHERE active = 1
        AND end_time <= NOW()
        """,
    )


async def _create_new_challenge() -> None:
    """Create a new daily challenge with a random ranked beatmap."""
    # Get a random ranked beatmap that wasn't used recently
    beatmap = await _get_random_ranked_map()

    if not beatmap:
        log("Daily Challenge: No eligible ranked maps found!", Ansi.LRED)
        return

    # Get current time from database (ensures timezone consistency)
    db_now = await app.state.services.database.fetch_one("SELECT NOW() as now")
    now = db_now["now"]
    
    # Calculate end time as exactly 24 hours from now
    end_time = now + timedelta(days=1)

    try:
        challenge_id = await app.state.services.database.execute(
            """
            INSERT INTO daily_challenges
            (map_md5, start_time, end_time, mode, active)
            VALUES (:map_md5, :start_time, :end_time, :mode, 1)
            """,
            {
                "map_md5": beatmap["md5"],
                "start_time": now,
                "end_time": end_time,
                "mode": 0,  # std mode
            },
        )

        log(
            f"Daily Challenge: Created new challenge for map "
            f"'{beatmap['artist']} - {beatmap['title']} [{beatmap['version']}]' "
            f"start={now}, end={end_time}",
            Ansi.LGREEN,
        )
    except Exception as e:
        log(
            f"Daily Challenge: Failed to create new challenge: {e}",
            Ansi.LRED,
        )


async def _get_random_ranked_map() -> dict[str, Any] | None:
    """Get a random ranked beatmap that hasn't been used in daily challenges recently.

    Selects from:
    - Ranked or approved beatmaps (status 2 or 3)
    - Standard mode (mode 0)
    - Difficulty between 2.0 and 8.0 stars
    - Not used in the last 30 days
    """
    result = await app.state.services.database.fetch_one(
        """
        SELECT m.md5, m.id, m.set_id, m.title, m.artist, m.version, m.creator, m.diff, m.mode
        FROM maps m
        WHERE m.status IN (2, 3)
        AND m.mode = 0
        AND m.diff >= 2.0
        AND m.diff <= 8.0
        AND m.md5 NOT IN (
            SELECT DISTINCT map_md5
            FROM daily_challenges
            WHERE start_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        )
        ORDER BY RAND()
        LIMIT 1
        """,
    )
    return result
