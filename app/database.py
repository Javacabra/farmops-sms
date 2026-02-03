"""SQLite database for cattle records."""
import aiosqlite
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any

DB_PATH = Path(__file__).parent.parent / "data" / "farmops.db"

SCHEMA = """
-- Locations/pastures
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    pasture_type TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cattle records
CREATE TABLE IF NOT EXISTS cattle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT UNIQUE,
    type TEXT NOT NULL,  -- cow, bull, calf, steer, heifer
    breed TEXT DEFAULT 'Angus',
    birth_date DATE,
    status TEXT DEFAULT 'active',  -- active, sold, deceased, transferred
    location_id INTEGER REFERENCES locations(id),
    dam_id INTEGER REFERENCES cattle(id),
    sire_id INTEGER REFERENCES cattle(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Events (health, moves, etc)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cattle_id INTEGER REFERENCES cattle(id),
    event_type TEXT NOT NULL,  -- vet, move, birth, death, treatment, note
    event_date DATE NOT NULL,
    details TEXT,
    cost REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sales records
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date DATE NOT NULL,
    head_count INTEGER NOT NULL,
    total_weight REAL,
    price_per_lb REAL,
    total_amount REAL,
    buyer TEXT,
    cattle_type TEXT,  -- steer, heifer, cow, bull
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SMS message log
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number TEXT NOT NULL,
    direction TEXT NOT NULL,  -- inbound, outbound
    body TEXT NOT NULL,
    parsed_action TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_cattle_tag ON cattle(tag);
CREATE INDEX IF NOT EXISTS idx_cattle_status ON cattle(status);
CREATE INDEX IF NOT EXISTS idx_events_cattle ON events(cattle_id);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
"""

# Default locations for the farm
DEFAULT_LOCATIONS = [
    ("North Pasture", "grazing", "Main grazing area"),
    ("South Pasture", "grazing", "Secondary grazing"),
    ("Hayfield", "hay", "Hay production field"),
    ("Corral", "holding", "Working pen at Stokes Homestead"),
    ("Barn", "shelter", "Main barn area"),
    ("Woods", "wooded", "Wooded area with ponds"),
]


def init_db_sync():
    """Initialize database synchronously (for startup)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    
    # Insert default locations if empty
    cursor = conn.execute("SELECT COUNT(*) FROM locations")
    if cursor.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO locations (name, pasture_type, notes) VALUES (?, ?, ?)",
            DEFAULT_LOCATIONS
        )
    conn.commit()
    conn.close()


async def get_db() -> aiosqlite.Connection:
    """Get async database connection."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


class CattleDB:
    """Database operations for cattle management."""
    
    @staticmethod
    async def add_cattle(
        tag: str,
        cattle_type: str,
        breed: str = "Angus",
        birth_date: Optional[date] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a new cattle record."""
        db = await get_db()
        try:
            # Get location ID if provided
            location_id = None
            if location:
                cursor = await db.execute(
                    "SELECT id FROM locations WHERE LOWER(name) LIKE ?",
                    (f"%{location.lower()}%",)
                )
                row = await cursor.fetchone()
                if row:
                    location_id = row["id"]
            
            await db.execute(
                """INSERT INTO cattle (tag, type, breed, birth_date, location_id, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tag, cattle_type, breed, birth_date, location_id, notes)
            )
            await db.commit()
            
            # Get the inserted record
            cursor = await db.execute(
                "SELECT * FROM cattle WHERE tag = ?", (tag,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else {"tag": tag, "type": cattle_type}
        finally:
            await db.close()
    
    @staticmethod
    async def get_cattle(tag: Optional[str] = None, cattle_id: Optional[int] = None) -> Optional[Dict]:
        """Get cattle by tag or ID."""
        db = await get_db()
        try:
            if tag:
                cursor = await db.execute(
                    """SELECT c.*, l.name as location_name 
                       FROM cattle c 
                       LEFT JOIN locations l ON c.location_id = l.id
                       WHERE c.tag = ? OR c.tag LIKE ?""",
                    (tag, f"%{tag}%")
                )
            elif cattle_id:
                cursor = await db.execute(
                    """SELECT c.*, l.name as location_name 
                       FROM cattle c 
                       LEFT JOIN locations l ON c.location_id = l.id
                       WHERE c.id = ?""",
                    (cattle_id,)
                )
            else:
                return None
            
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()
    
    @staticmethod
    async def update_location(tag: str, location: str) -> bool:
        """Update cattle location."""
        db = await get_db()
        try:
            # Find location
            cursor = await db.execute(
                "SELECT id FROM locations WHERE LOWER(name) LIKE ?",
                (f"%{location.lower()}%",)
            )
            loc_row = await cursor.fetchone()
            if not loc_row:
                # Create new location
                await db.execute(
                    "INSERT INTO locations (name, pasture_type) VALUES (?, 'other')",
                    (location,)
                )
                cursor = await db.execute("SELECT last_insert_rowid()")
                loc_row = await cursor.fetchone()
            
            location_id = loc_row[0] if isinstance(loc_row, tuple) else loc_row["id"]
            
            # Update cattle
            cursor = await db.execute(
                """UPDATE cattle SET location_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE tag = ? OR tag LIKE ?""",
                (location_id, tag, f"%{tag}%")
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()
    
    @staticmethod
    async def add_event(
        cattle_tag: str,
        event_type: str,
        details: str,
        event_date: Optional[date] = None,
        cost: Optional[float] = None
    ) -> Dict[str, Any]:
        """Add an event for a cattle."""
        db = await get_db()
        try:
            # Find cattle
            cursor = await db.execute(
                "SELECT id FROM cattle WHERE tag = ? OR tag LIKE ?",
                (cattle_tag, f"%{cattle_tag}%")
            )
            cattle_row = await cursor.fetchone()
            cattle_id = cattle_row["id"] if cattle_row else None
            
            event_date = event_date or date.today()
            
            await db.execute(
                """INSERT INTO events (cattle_id, event_type, event_date, details, cost)
                   VALUES (?, ?, ?, ?, ?)""",
                (cattle_id, event_type, event_date, details, cost)
            )
            await db.commit()
            return {
                "cattle_tag": cattle_tag,
                "event_type": event_type,
                "details": details,
                "date": str(event_date)
            }
        finally:
            await db.close()
    
    @staticmethod
    async def add_sale(
        head_count: int,
        price_per_lb: Optional[float] = None,
        avg_weight: Optional[float] = None,
        total_amount: Optional[float] = None,
        cattle_type: str = "steer",
        buyer: Optional[str] = None,
        sale_date: Optional[date] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record a sale."""
        db = await get_db()
        try:
            sale_date = sale_date or date.today()
            total_weight = avg_weight * head_count if avg_weight else None
            
            if not total_amount and price_per_lb and total_weight:
                total_amount = price_per_lb * total_weight
            
            await db.execute(
                """INSERT INTO sales (sale_date, head_count, total_weight, price_per_lb, 
                   total_amount, buyer, cattle_type, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sale_date, head_count, total_weight, price_per_lb, total_amount, 
                 buyer, cattle_type, notes)
            )
            await db.commit()
            return {
                "head_count": head_count,
                "total_amount": total_amount,
                "date": str(sale_date)
            }
        finally:
            await db.close()
    
    @staticmethod
    async def count_cattle(
        cattle_type: Optional[str] = None,
        status: str = "active",
        since_date: Optional[date] = None
    ) -> int:
        """Count cattle with filters."""
        db = await get_db()
        try:
            query = "SELECT COUNT(*) as count FROM cattle WHERE status = ?"
            params = [status]
            
            if cattle_type:
                query += " AND LOWER(type) = ?"
                params.append(cattle_type.lower())
            
            if since_date:
                query += " AND birth_date >= ?"
                params.append(since_date)
            
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return row["count"] if row else 0
        finally:
            await db.close()
    
    @staticmethod
    async def get_stats() -> Dict[str, Any]:
        """Get summary statistics."""
        db = await get_db()
        try:
            stats = {}
            
            # Total active cattle
            cursor = await db.execute(
                "SELECT COUNT(*) as count FROM cattle WHERE status = 'active'"
            )
            stats["total_head"] = (await cursor.fetchone())["count"]
            
            # By type
            cursor = await db.execute(
                """SELECT type, COUNT(*) as count FROM cattle 
                   WHERE status = 'active' GROUP BY type"""
            )
            stats["by_type"] = {row["type"]: row["count"] for row in await cursor.fetchall()}
            
            # Calves this year
            year_start = date(date.today().year, 1, 1)
            cursor = await db.execute(
                """SELECT COUNT(*) as count FROM cattle 
                   WHERE type = 'calf' AND birth_date >= ?""",
                (year_start,)
            )
            stats["calves_ytd"] = (await cursor.fetchone())["count"]
            
            # Sales YTD
            cursor = await db.execute(
                """SELECT SUM(head_count) as head, SUM(total_amount) as amount 
                   FROM sales WHERE sale_date >= ?""",
                (year_start,)
            )
            row = await cursor.fetchone()
            stats["sales_ytd_head"] = row["head"] or 0
            stats["sales_ytd_amount"] = row["amount"] or 0
            
            # Recent events
            cursor = await db.execute(
                """SELECT e.*, c.tag FROM events e 
                   LEFT JOIN cattle c ON e.cattle_id = c.id
                   ORDER BY e.event_date DESC, e.created_at DESC LIMIT 10"""
            )
            stats["recent_events"] = [dict(row) for row in await cursor.fetchall()]
            
            return stats
        finally:
            await db.close()
    
    @staticmethod
    async def get_all_cattle(status: str = "active") -> List[Dict]:
        """Get all cattle records."""
        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT c.*, l.name as location_name 
                   FROM cattle c 
                   LEFT JOIN locations l ON c.location_id = l.id
                   WHERE c.status = ?
                   ORDER BY c.tag""",
                (status,)
            )
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()
    
    @staticmethod
    async def get_locations() -> List[Dict]:
        """Get all locations."""
        db = await get_db()
        try:
            cursor = await db.execute("SELECT * FROM locations ORDER BY name")
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()
    
    @staticmethod
    async def log_message(phone: str, direction: str, body: str, action: Optional[str] = None):
        """Log SMS message."""
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO messages (phone_number, direction, body, parsed_action) VALUES (?, ?, ?, ?)",
                (phone, direction, body, action)
            )
            await db.commit()
        finally:
            await db.close()
