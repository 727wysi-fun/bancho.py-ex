#!/usr/bin/env python3
"""Generate realistic-looking bot names based on real osu! players"""

import random
import sys

# Real osu! player names as base - extended list of real players
REAL_NAMES = [
    # Top players
    "Cookiezi", "Rafis", "hvick225", "Adamqs", "Aricin", "Toy", "Mithew", "yoyo",
    "Happystick", "Rohulk", "Karthy", "Ceptin", "Bikko", "alacat", "Recia", "Exarch",
    "Shigetora", "Shadowless", "freddie benson", "Natsu", "Monstrata", "Sotarks",
    "Pishifat", "Hobbes2", "xexxar", "Pancake", "Emiru", "Angeli", "Mathi",
    "Bubbleman", "fieryrage", "Vaxei", "nik1", "RyuK", "Ayaya", "Abysmal",
    # More players
    "Andros", "Asaiga", "Axarious", "Base", "Barrier", "Behonkiss", "Benka",
    "Bluefalcon", "BluexDragons", "Boost", "BriefcaseNA", "BrokenAngel", "Buddha",
    "Calzone", "Camellia", "Candystars", "CapHeadCap", "Carnaval", "Catmosphere",
    "Celektus", "Centizen", "Cerulean", "Chaoslite", "Charlock", "Chata",
    "Chaud", "Chelly", "Cheq", "Cheri", "Chestnut", "Chiao", "Chida",
    "Chiisana", "Chiku", "Chinatown", "Chingling", "Chino", "Chintan",
    # Additional players with natural names
    "C00LIN", "C9", "Kert", "Milo", "Roxy", "Doomsday", "Ceptin",
    "idke", "Umbre", "Ekoro", "Reimu", "Ekoro", "index", "Amin",
    "Rizer", "Milo", "natsume rin", "Reimu", "Dreezy", "Varvalian",
    "peppalt", "Apraxia", "Cero", "Petal", "Karthy", "Atena",
    "akane", "Ascendance", "Macaroni", "mismagius", "Jatoro",
    "Azer", "ztrot", "TrolloCat", "mouse_AUN", "mouse",
    # Mappers and streamer names
    "Aspire", "Blue Dragon", "Brena", "fanzhen0019", "Fiddle",
    "galkan", "Gero", "Halfslashed", "Harmonizer", "Hollow Wings",
    "ibuki", "iljaaz", "Jemzuu", "JieN", "Jieusieu",
    "KittyAdventure", "Krisom", "KKipster", "Kyonko", "Kyuuun",
    "LittleDealer", "Lunako", "Macaroni", "Makari", "Mathemouse",
    # Streamers and content creators
    "Toy", "fieryrage", "Bubbleman", "Milo", "Vaxei",
    "Trey", "theviper", "Loli", "twofold", "TS_Abysmal",
    # Bot-like realistic names (numbers/variations)
]

COUNTRIES = ["ru", "id", "ua", "ro", "fi", "nl", "ie", "br", "fr", "de", "gb", "us", 
             "jp", "kr", "cn", "au", "ca", "mx", "ar", "se"]

SUFFIXES = [
    "_", "1", "2", "3", "x", "X", "HD", "DT", "NF", "EZ", "FL",
    "Pro", "Pro2", "Alt", "Alt2", "Side", "Main", "New", "Old",
    "99", "420", "lol", "xd", "owo", "ala", "san", "chan", "kun",
]

PREFIXES = [
    "", "the", "real", "fake", "ok", "pro", "semi", "ultra", "mega",
    "noob", "tryhard", "casual", "legend", "godlike", "i", "mr", "ms",
    "captain", "lord", "lady", "sir", "dame", "prof", "dr", "gen",
]

def generate_bot_names(count=250):
    """Generate realistic-looking bot names"""
    names = []
    used = set()
    
    # Strategy: use real names, then add variations
    # First, use base names up to a certain count
    base_count = min(len(REAL_NAMES), int(count * 0.4))
    for name in REAL_NAMES[:base_count]:
        if name not in used:
            names.append(name)
            used.add(name)
    
    # Fill remaining with variations
    while len(names) < count:
        base = random.choice(REAL_NAMES)
        
        # Decide how to modify the name
        choice = random.random()
        
        if choice < 0.25:
            # Add numeric suffix (most natural looking)
            suffix_num = random.randint(1, 999)
            name = f"{base}{suffix_num}"
        elif choice < 0.5:
            # Add double letter or underscore variations
            name = f"{base}_{random.choice(['HD', 'DT', 'HR', 'EZ', 'FL', 'NC'])}"
        elif choice < 0.75:
            # Mix two real names
            second = random.choice(REAL_NAMES)
            name = f"{base}{second}"
        else:
            # Add prefix
            prefix = random.choice(['the', 'real', 'ok', 'pro', 'mr', 'no'])
            name = f"{prefix}{base}"
        
        # Ensure uniqueness
        if name not in used and len(name) <= 16:  # osu username limit
            names.append(name)
            used.add(name)
    
    return names[:count]

def generate_sql_insert(count=250):
    """Generate SQL INSERT statement for bots"""
    names = generate_bot_names(count)
    
    countries = COUNTRIES
    
    # Build the VALUES part
    values = []
    for i, name in enumerate(names):
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        email = f"bot{i+1}@bots.local"
        country = countries[i % len(countries)]
        timestamp = 1700000000 + i
        
        # Escape single quotes in name
        name_escaped = name.replace("'", "''")
        
        values.append(
            f"('{name_escaped}', '{safe_name}', '{email}', 1, "
            f"'_______________________my_cool_bcrypt_______________________', "
            f"'{country}', {timestamp}, {timestamp})"
        )
    
    sql = """INSERT INTO users (name, safe_name, email, priv, pw_bcrypt, country, creation_time, latest_activity)
VALUES
""" + ",\n".join(values) + ";"
    
    return sql, names

def generate_stats_sql(names):
    """Generate SQL to add stats for all new bots"""
    sql_parts = []
    
    # Get user IDs for the names we just added
    safe_names = [n.lower().replace(" ", "_").replace("-", "_") for n in names]
    
    sql = f"""INSERT INTO stats (id, mode, total_score, ranked_score, pp, plays, playtime, acc, max_combo, total_hits, replay_views, xh_count, x_count, sh_count, s_count, a_count)
SELECT u.id, mode_num, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
FROM (SELECT id FROM users WHERE safe_name IN ({','.join([f"'{name}'" for name in safe_names])})) u
CROSS JOIN (
    SELECT 0 as mode_num UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 
    UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 8
) modes
WHERE NOT EXISTS (
    SELECT 1 FROM stats WHERE stats.id = u.id AND stats.mode = mode_num
);"""
    
    return sql

if __name__ == "__main__":
    import io
    
    # Force UTF-8 output
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    else:
        count = 250
    
    sql_users, names = generate_sql_insert(count)
    sql_stats = generate_stats_sql(names)
    
    print("-- User INSERT statement")
    print(sql_users)
    print("\n-- Stats INSERT statement")
    print(sql_stats)
    print(f"\n-- Generated {len(names)} unique bot names")
    print(f"-- Examples: {', '.join(names[:10])}")
