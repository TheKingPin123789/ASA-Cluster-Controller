"""
maps.py — Canonical ARK map definitions shared by all controller modules.

To add a map: add one entry to MAP_DEFS and its aliases to MAP_ALIASES /
MAP_SHORT_NAMES. No other file needs changing.
"""

# key → (display_name, map_name, game_port, query_port, rcon_port)
MAP_DEFS: dict[str, tuple] = {
    "ragnarok":      ("Ragnarok",       "Ragnarok_WP",      7777, 27015, 27020),
    "thecenter":     ("The Center",     "TheCenter_WP",     7787, 27025, 27021),
    "valguero":      ("Valguero",       "Valguero_WP",      7797, 27035, 27022),
    "theisland":     ("The Island",     "TheIsland_WP",     7807, 27045, 27023),
    "scorchedearth": ("Scorched Earth", "ScorchedEarth_WP", 7817, 27055, 27024),
    "aberration":    ("Aberration",     "Aberration_WP",    7827, 27065, 27029),
    "extinction":    ("Extinction",     "Extinction_WP",    7837, 27075, 27026),
    "lostcolony":    ("Lost Colony",    "LostColony_WP",    7847, 27085, 27027),
    "astraeos":      ("Astraeos",       "Astraeos_WP",      7857, 27095, 27028),
}

MAPS: list[str] = list(MAP_DEFS)  # ordered canonical keys

MAP_ALIASES: dict[str, str] = {
    "tc":            "thecenter",
    "center":        "thecenter",
    "thecenter":     "thecenter",
    "rag":           "ragnarok",
    "ragnarok":      "ragnarok",
    "val":           "valguero",
    "valguero":      "valguero",
    "ti":            "theisland",
    "island":        "theisland",
    "theisland":     "theisland",
    "se":            "scorchedearth",
    "scorched":      "scorchedearth",
    "scorchedearth": "scorchedearth",
    "ab":            "aberration",
    "abberation":    "aberration",  # common typo — kept intentionally
    "aberration":    "aberration",
    "ext":           "extinction",
    "extinction":    "extinction",
    "lost":          "lostcolony",
    "lostcolony":    "lostcolony",
    "astraeos":      "astraeos",
}

# Short names shown in help text (key → accepted short names, excluding the key itself)
MAP_SHORT_NAMES: dict[str, list[str]] = {
    "ragnarok":      ["rag"],
    "thecenter":     ["tc", "center"],
    "valguero":      ["val"],
    "theisland":     ["ti", "island"],
    "scorchedearth": ["se", "scorched"],
    "aberration":    ["ab"],
    "extinction":    ["ext"],
    "lostcolony":    ["lost"],
    "astraeos":      [],
}
