from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import sqlite3
from datetime import datetime

app = FastAPI(title="Optimised Parking System")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
DB_PATH = Path(__file__).resolve().parent.parent / "parking_history.db"

GPS_API_KEY = "change-this-demo-key"


# ---------------- SQLITE DATABASE ----------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def current_time():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def initialize_database():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS parking_slots (
            slot_number TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            vehicle_number TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS parking_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_number TEXT NOT NULL,
            slot_number TEXT NOT NULL,
            allocated_at TEXT NOT NULL,
            released_at TEXT,
            status TEXT NOT NULL
        )
    """)

    for i in range(1, 11):
        conn.execute("""
            INSERT OR IGNORE INTO parking_slots
            (slot_number, status, vehicle_number)
            VALUES (?, 'Available', NULL)
        """, (f"P{i}",))

    conn.commit()
    conn.close()


initialize_database()


# ---------------- VEHICLE GPS DATABASE ----------------

vehicles = {
    "TN-38-AB-1234": {
        "vehicle_number": "TN-38-AB-1234",
        "latitude": 11.0168,
        "longitude": 76.9558,
        "location": "Coimbatore",
        "status": "Simulated GPS"
    },
    "TN-38-CD-5678": {
        "vehicle_number": "TN-38-CD-5678",
        "latitude": 11.0250,
        "longitude": 76.9670,
        "location": "Coimbatore",
        "status": "Simulated GPS"
    }
}


# ---------------- REQUEST MODELS ----------------

class GPSData(BaseModel):
    vehicle_number: str
    latitude: float
    longitude: float
    location: str = "GPS location received"


class ParkingRequest(BaseModel):
    vehicle_number: str


# ---------------- HOME PAGE ----------------

@app.get("/")
def home():
    return FileResponse(FRONTEND / "index.html")


# ---------------- PARKING STATUS ----------------

@app.get("/parking")
def parking_status():
    conn = get_db()

    occupied = conn.execute("""
        SELECT COUNT(*) FROM parking_slots
        WHERE status = 'Occupied'
    """).fetchone()[0]

    total = conn.execute("""
        SELECT COUNT(*) FROM parking_slots
    """).fetchone()[0]

    conn.close()

    return {
        "total_slots": total,
        "occupied_slots": occupied,
        "available_slots": total - occupied
    }


# ---------------- PARKING SLOT DETAILS ----------------

@app.get("/parking/slots")
def get_parking_slots():
    conn = get_db()

    rows = conn.execute("""
        SELECT * FROM parking_slots
        ORDER BY slot_number
    """).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# ---------------- AUTOMATIC SLOT ALLOCATION ----------------

@app.post("/parking/allocate")
def allocate_parking(data: ParkingRequest):

    number = data.vehicle_number.upper().strip()

    if not number:
        raise HTTPException(
            status_code=400,
            detail="Enter a vehicle number"
        )

    conn = get_db()

    try:
        existing = conn.execute("""
            SELECT * FROM parking_slots
            WHERE vehicle_number = ?
        """, (number,)).fetchone()

        if existing:
            return {
                "message": "Vehicle already has a parking slot",
                "parking_slot": dict(existing)
            }

        slot = conn.execute("""
            SELECT * FROM parking_slots
            WHERE status = 'Available'
            ORDER BY slot_number
            LIMIT 1
        """).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=400,
                detail="Sorry! No parking slots available"
            )

        slot_number = slot["slot_number"]
        allocated_at = current_time()

        conn.execute("""
            UPDATE parking_slots
            SET status = 'Occupied', vehicle_number = ?
            WHERE slot_number = ?
        """, (number, slot_number))

        conn.execute("""
            INSERT INTO parking_history
            (vehicle_number, slot_number, allocated_at, released_at, status)
            VALUES (?, ?, ?, NULL, 'Occupied')
        """, (number, slot_number, allocated_at))

        conn.commit()

        updated_slot = conn.execute("""
            SELECT * FROM parking_slots
            WHERE slot_number = ?
        """, (slot_number,)).fetchone()

        return {
            "message": "Parking slot allocated successfully",
            "parking_slot": dict(updated_slot)
        }

    finally:
        conn.close()


# ---------------- RELEASE PARKING SLOT ----------------

@app.post("/parking/release")
def release_parking(data: ParkingRequest):

    number = data.vehicle_number.upper().strip()

    conn = get_db()

    try:
        slot = conn.execute("""
            SELECT * FROM parking_slots
            WHERE vehicle_number = ?
        """, (number,)).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=404,
                detail="No parking slot found for this vehicle"
            )

        released_at = current_time()
        slot_number = slot["slot_number"]

        conn.execute("""
            UPDATE parking_slots
            SET status = 'Available', vehicle_number = NULL
            WHERE slot_number = ?
        """, (slot_number,))

        conn.execute("""
            UPDATE parking_history
            SET status = 'Released', released_at = ?
            WHERE vehicle_number = ?
            AND slot_number = ?
            AND status = 'Occupied'
        """, (released_at, number, slot_number))

        conn.commit()

        updated_slot = conn.execute("""
            SELECT * FROM parking_slots
            WHERE slot_number = ?
        """, (slot_number,)).fetchone()

        return {
            "message": "Parking slot released successfully",
            "parking_slot": dict(updated_slot)
        }

    finally:
        conn.close()


# ---------------- PARKING HISTORY ----------------

@app.get("/parking/history")
def get_parking_history():

    conn = get_db()

    rows = conn.execute("""
        SELECT * FROM parking_history
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# ---------------- VEHICLE-SPECIFIC HISTORY ----------------

@app.get("/parking/history/{vehicle_number}")
def get_vehicle_history(vehicle_number: str):

    number = vehicle_number.upper().strip()

    conn = get_db()

    rows = conn.execute("""
        SELECT * FROM parking_history
        WHERE vehicle_number = ?
        ORDER BY id DESC
    """, (number,)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# ---------------- SMART PARKING ANALYTICS ----------------

@app.get("/parking/analytics")
def parking_analytics():

    conn = get_db()

    try:
        # Total number of parking allocations
        total_allocations = conn.execute("""
            SELECT COUNT(*) FROM parking_history
        """).fetchone()[0]

        # Number of different vehicles recorded
        unique_vehicles = conn.execute("""
            SELECT COUNT(DISTINCT vehicle_number)
            FROM parking_history
        """).fetchone()[0]

        # Vehicles currently parked
        currently_parked = conn.execute("""
            SELECT COUNT(*) FROM parking_slots
            WHERE status = 'Occupied'
        """).fetchone()[0]

        # Daily parking activity
        daily_rows = conn.execute("""
            SELECT
                date(allocated_at) AS parking_date,
                COUNT(*) AS vehicle_count
            FROM parking_history
            GROUP BY date(allocated_at)
            ORDER BY parking_date
        """).fetchall()

        daily_activity = [
            {
                "date": row["parking_date"],
                "vehicles": row["vehicle_count"]
            }
            for row in daily_rows
        ]

        # Most-used parking slots
        slot_rows = conn.execute("""
            SELECT
                slot_number,
                COUNT(*) AS usage_count
            FROM parking_history
            GROUP BY slot_number
            ORDER BY usage_count DESC, slot_number ASC
        """).fetchall()

        most_used_slots = [
            {
                "slot": row["slot_number"],
                "usage": row["usage_count"]
            }
            for row in slot_rows
        ]

        return {
            "total_allocations": total_allocations,
            "unique_vehicles": unique_vehicles,
            "currently_parked": currently_parked,
            "daily_activity": daily_activity,
            "most_used_slots": most_used_slots
        }

    finally:
        conn.close()


# ---------------- GPS TRACKING ----------------

@app.get("/gps")
def gps_tracking():
    return {
        "tracking_status": "Simulated GPS Active",
        "location": "Coimbatore"
    }


@app.get("/bus/{vehicle_number}")
def track_bus(vehicle_number: str):

    vehicle = vehicles.get(vehicle_number.upper())

    if vehicle is None:
        raise HTTPException(
            status_code=404,
            detail="Vehicle not registered"
        )

    return vehicle


# ---------------- GPS UPDATE ----------------

@app.post("/gps/update")
def update_gps(
    data: GPSData,
    x_gps_key: str = Header(default="")
):

    if x_gps_key != GPS_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid GPS key"
        )

    number = data.vehicle_number.upper()

    if number not in vehicles:
        raise HTTPException(
            status_code=404,
            detail="Vehicle not registered"
        )

    if not (-90 <= data.latitude <= 90):
        raise HTTPException(
            status_code=400,
            detail="Invalid latitude"
        )

    if not (-180 <= data.longitude <= 180):
        raise HTTPException(
            status_code=400,
            detail="Invalid longitude"
        )

    vehicles[number] = {
        "vehicle_number": number,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "location": data.location,
        "status": "GPS Data Received"
    }

    return {
        "message": "GPS updated successfully",
        "vehicle": vehicles[number]
    }