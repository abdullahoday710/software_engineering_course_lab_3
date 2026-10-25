"""SQLite persistence layer: schema creation and demo seed data.

All tables live in one SQLite file (``smartbrew.db`` by default). Passing
``":memory:"`` gives a throw-away database, which the unit tests use.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .security import hash_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    email            TEXT NOT NULL UNIQUE,
    pw_hash          TEXT NOT NULL,
    salt             TEXT NOT NULL,
    card_id          TEXT UNIQUE,
    default_milk     TEXT NOT NULL DEFAULT 'Whole milk',
    default_strength INTEGER NOT NULL DEFAULT 3,
    prepaid_balance  REAL NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredients (
    name      TEXT PRIMARY KEY,
    level     REAL NOT NULL,
    capacity  REAL NOT NULL,
    threshold REAL NOT NULL,
    unit      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drinks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL,
    base_price  REAL NOT NULL,
    calories    INTEGER NOT NULL,
    sugar_g     REAL NOT NULL,
    fat_g       REAL NOT NULL,
    caffeine_mg INTEGER NOT NULL,
    coffee_g    REAL NOT NULL,
    milk_ml     REAL NOT NULL,
    water_ml    REAL NOT NULL,
    cocoa_g     REAL NOT NULL,
    ice_g       REAL NOT NULL,
    is_cold     INTEGER NOT NULL,
    sweet       INTEGER NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    name        TEXT NOT NULL,
    drink_id    INTEGER NOT NULL REFERENCES drinks(id),
    milk        TEXT NOT NULL,
    strength    INTEGER NOT NULL,
    temperature TEXT NOT NULL,
    syrup       TEXT NOT NULL,
    syrup_shots INTEGER NOT NULL,
    extra_shot  INTEGER NOT NULL,
    UNIQUE (user_id, name)
);
CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER REFERENCES users(id),
    drink_id       INTEGER NOT NULL,
    drink_name     TEXT NOT NULL,
    milk           TEXT NOT NULL,
    strength       INTEGER NOT NULL,
    temperature    TEXT NOT NULL,
    syrup          TEXT NOT NULL,
    syrup_shots    INTEGER NOT NULL,
    extra_shot     INTEGER NOT NULL,
    price          REAL NOT NULL,
    payment_method TEXT NOT NULL,
    payment_ref    TEXT NOT NULL,
    offline        INTEGER NOT NULL DEFAULT 0,
    synced         INTEGER NOT NULL DEFAULT 1,
    timestamp      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bins (
    name     TEXT PRIMARY KEY,
    level    REAL NOT NULL,
    capacity REAL NOT NULL,
    unit     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level     TEXT NOT NULL,
    source    TEXT NOT NULL,
    message   TEXT NOT NULL,
    active    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# name, level, capacity, threshold, unit
SEED_INGREDIENTS = [
    ("Water", 4000, 4000, 400, "ml"),
    ("Coffee beans", 1000, 1000, 60, "g"),
    ("Whole milk", 2000, 2000, 250, "ml"),
    ("Skim milk", 1500, 1500, 250, "ml"),
    ("Oat milk", 1500, 1500, 250, "ml"),
    ("Almond milk", 1500, 1500, 250, "ml"),
    ("Cocoa", 500, 500, 40, "g"),
    ("Syrup", 750, 750, 50, "ml"),
    ("Ice", 2000, 2000, 300, "g"),
    ("Cups", 100, 100, 5, "pcs"),
]

# name, category, price, kcal, sugar, fat, caffeine, coffee_g, milk_ml,
# water_ml, cocoa_g, ice_g, is_cold, sweet, description
SEED_DRINKS = [
    ("Espresso", "Espresso", 25, 3, 0, 0.2, 63, 8, 0, 30, 0, 0, 0, 0,
     "A short, intense shot of coffee."),
    ("Double Espresso", "Espresso", 32, 5, 0, 0.4, 126, 16, 0, 60, 0, 0, 0, 0,
     "Two shots for a serious kick."),
    ("Americano", "Espresso", 30, 6, 0, 0.3, 95, 12, 0, 220, 0, 0, 0, 0,
     "Espresso lengthened with hot water."),
    ("Macchiato", "Espresso", 30, 15, 1.2, 0.8, 63, 8, 30, 30, 0, 0, 0, 0,
     "Espresso marked with a spoon of milk foam."),
    ("Cappuccino", "Milk coffee", 38, 20, 1.5, 0.9, 63, 8, 150, 30, 0, 0, 0, 0,
     "Equal parts espresso, steamed milk and foam."),
    ("Latte", "Milk coffee", 40, 25, 2.0, 1.0, 63, 8, 220, 30, 0, 0, 0, 0,
     "Espresso with plenty of silky steamed milk."),
    ("Flat White", "Milk coffee", 40, 20, 1.5, 0.8, 126, 16, 130, 40, 0, 0, 0, 0,
     "Double ristretto with velvety micro-foam."),
    ("Mocha", "Chocolate", 45, 120, 18.0, 4.0, 70, 8, 180, 30, 20, 0, 0, 1,
     "Espresso, chocolate and steamed milk."),
    ("Hot Chocolate", "Chocolate", 38, 150, 24.0, 5.0, 10, 0, 220, 0, 30, 0, 0, 1,
     "Rich cocoa with steamed milk. Caffeine-light."),
    ("Iced Latte", "Iced", 45, 25, 2.0, 1.0, 63, 8, 200, 30, 0, 150, 1, 0,
     "Espresso and cold milk over ice."),
    ("Iced Americano", "Iced", 38, 6, 0, 0.3, 95, 12, 0, 180, 0, 150, 1, 0,
     "Espresso and cold water over ice."),
    ("Caramel Frappe", "Iced", 52, 180, 32.0, 6.0, 70, 8, 160, 30, 0, 200, 1, 1,
     "Blended ice, coffee, milk and caramel."),
]

SEED_BINS = [
    ("Coffee grounds", 0, 600, "g"),
    ("Liquid waste", 0, 1500, "ml"),
]

DEMO_PIN = "1234"
DEMO_MASTER_CARD = "NFC-MASTER-0001"
DEMO_USER = ("Demo User", "demo@smartbrew.local", "demo1234", "NFC-EMP-1001", 150.0)


def now_iso() -> str:
    """Return the current local time as an ISO-8601 string.

    Returns:
        str: timestamp such as ``"2026-10-26T08:15:02"`` (seconds precision).
    """
    return datetime.now().replace(microsecond=0).isoformat()


def connect(path: str = "smartbrew.db") -> sqlite3.Connection:
    """Open the SQLite database, create the schema and seed it if empty.

    Args:
        path: file path of the database, or ``":memory:"`` for a temporary one.

    Returns:
        sqlite3.Connection: an open connection whose rows behave like dicts
        (``sqlite3.Row``), with foreign keys enabled.
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM drinks").fetchone()[0] == 0:
        seed(conn)
    return conn


def seed(conn: sqlite3.Connection) -> None:
    """Insert the demo catalogue, inventory, bins, admin secrets and demo user.

    Args:
        conn: open connection with the schema already created.

    Returns:
        None. The data is committed to the database.
    """
    conn.executemany("INSERT INTO ingredients VALUES (?,?,?,?,?)", SEED_INGREDIENTS)
    conn.executemany(
        "INSERT INTO drinks (name, category, base_price, calories, sugar_g, fat_g,"
        " caffeine_mg, coffee_g, milk_ml, water_ml, cocoa_g, ice_g, is_cold, sweet,"
        " description) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        SEED_DRINKS,
    )
    conn.executemany("INSERT INTO bins VALUES (?,?,?,?)", SEED_BINS)

    pin_hash, pin_salt = hash_secret(DEMO_PIN)
    card_hash, card_salt = hash_secret(DEMO_MASTER_CARD)
    conn.executemany(
        "INSERT INTO settings VALUES (?,?)",
        [
            ("admin_pin_hash", pin_hash),
            ("admin_pin_salt", pin_salt),
            ("admin_card_hash", card_hash),
            ("admin_card_salt", card_salt),
        ],
    )

    name, email, password, card, balance = DEMO_USER
    pw_hash, salt = hash_secret(password)
    conn.execute(
        "INSERT INTO users (name, email, pw_hash, salt, card_id, default_milk,"
        " default_strength, prepaid_balance, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (name, email, pw_hash, salt, card, "Oat milk", 4, balance, now_iso()),
    )
    conn.commit()
