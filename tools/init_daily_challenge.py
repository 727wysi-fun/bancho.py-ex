#!/usr/bin/env python3.11
"""Initialize the first daily challenge."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from datetime import timedelta
from pathlib import Path

# Setup path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root_dir)
sys.path.insert(0, root_dir)

import app.settings
import app.state


async def main() -> None:
    """Initialize database connection and create first challenge."""
    # Setup database
    await app.state.services.database.connect()

    try:
        # Check if there's already an active challenge
        existing = await app.state.services.database.fetch_one(
            """
            SELECT id FROM daily_challenges
            WHERE active = 1
            AND start_time <= NOW()
            AND end_time > NOW()
            LIMIT 1
            """,
        )

        if existing:
            print(f"✓ Active challenge already exists (ID: {existing['id']})")
            return

        # Get a random ranked beatmap
        beatmap = await app.state.services.database.fetch_one(
            """
            SELECT md5, id, set_id, title, artist, version, creator, diff
            FROM maps
            WHERE status IN (2, 3)
            AND mode = 0
            AND diff >= 2.0
            AND diff <= 8.0
            ORDER BY RAND()
            LIMIT 1
            """,
        )

        if not beatmap:
            print("✗ No eligible ranked beatmaps found in database!")
            print("  Make sure you have ranked/approved beatmaps with difficulty 2.0-8.0★")
            return

        # Create new challenge
        now = datetime.now()
        end_time = now + timedelta(days=1)

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
                "mode": 0,
            },
        )

        print(f"✓ Created initial daily challenge:")
        print(f"  Map: {beatmap['artist']} - {beatmap['title']} [{beatmap['version']}]")
        print(f"  Creator: {beatmap['creator']}")
        print(f"  Difficulty: {beatmap['diff']:.2f}★")
        print(f"  Mode: std")
        print(f"  Duration: {now.strftime('%Y-%m-%d %H:%M:%S')} → {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Challenge ID: {challenge_id}")

    finally:
        await app.state.services.database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
