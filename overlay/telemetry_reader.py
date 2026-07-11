from __future__ import annotations

import struct
import mmap
import time
from dataclasses import dataclass
from typing import Optional

SHM_NAME = "HaulHUDSharedMemory"
SCHEMA_VERSION_SUPPORTED = 1

STRUCT_FORMAT = (
    "<"
    "II"
    "BBBB"
    "f"
    "II"
    "i"
    "fff"
    "I"
    "fff"
    "64s64s64s64s64s"
    "32s"
    "Q"
    "B"
    "7x"
)
STRUCT_SIZE = struct.calcsize(STRUCT_FORMAT)

def _decode(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

@dataclass
class TelemetryFrame:
    game_connected: bool
    game_paused: bool
    job_active: bool

    local_scale: float
    game_time_minutes: int
    delivery_time_minutes: int
    rest_stop_minutes: int

    nav_distance_m: float
    nav_time_s: float
    nav_speed_limit_ms: float

    planned_distance_km: int
    truck_speed_ms: float
    cargo_damage_pct: float
    cargo_mass_kg: float

    cargo_name: str
    source_city: str
    destination_city: str
    source_company: str
    destination_company: str
    job_market: str

    income: int
    is_special_job: bool

    @staticmethod
    def empty() -> "TelemetryFrame":
        return TelemetryFrame(
            game_connected=False, game_paused=True, job_active=False,
            local_scale=19.0, game_time_minutes=0, delivery_time_minutes=0,
            rest_stop_minutes=-1, nav_distance_m=-1, nav_time_s=-1,
            nav_speed_limit_ms=0, planned_distance_km=0, truck_speed_ms=0,
            cargo_damage_pct=0, cargo_mass_kg=0, cargo_name="", source_city="",
            destination_city="", source_company="", destination_company="",
            job_market="", income=0, is_special_job=False,
        )

class TelemetryReader:

    def __init__(self) -> None:
        self._mmap: Optional[mmap.mmap] = None
        self._connect_attempted_and_failed = False

    def _try_open(self) -> bool:
        if self._mmap is not None:
            return True
        try:
            self._mmap = mmap.mmap(-1, STRUCT_SIZE, tagname=SHM_NAME, access=mmap.ACCESS_READ)
            return True
        except OSError:
            self._mmap = None
            return False

    def close(self) -> None:
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None

    def read(self) -> TelemetryFrame:
        if not self._try_open():
            return TelemetryFrame.empty()

        assert self._mmap is not None
        for _ in range(8):
            self._mmap.seek(0)
            raw = self._mmap.read(STRUCT_SIZE)
            if len(raw) != STRUCT_SIZE:
                return TelemetryFrame.empty()

            seq1 = struct.unpack_from("<I", raw, 4)[0]
            if seq1 % 2 == 1:
                time.sleep(0.0005)
                continue

            unpacked = struct.unpack(STRUCT_FORMAT, raw)
            seq2_offset_check = unpacked[1]
            if seq2_offset_check != seq1:
                continue

            (
                schema_version, seq,
                game_connected, game_paused, job_active, _pad0,
                local_scale,
                game_time_minutes, delivery_time_minutes,
                rest_stop_minutes,
                nav_distance_m, nav_time_s, nav_speed_limit_ms,
                planned_distance_km,
                truck_speed_ms, cargo_damage_pct, cargo_mass_kg,
                cargo_name, source_city, destination_city, source_company, destination_company,
                job_market,
                income, is_special_job,
            ) = unpacked

            if schema_version != SCHEMA_VERSION_SUPPORTED:
                return TelemetryFrame.empty()

            return TelemetryFrame(
                game_connected=bool(game_connected),
                game_paused=bool(game_paused),
                job_active=bool(job_active),
                local_scale=local_scale if local_scale > 0 else 19.0,
                game_time_minutes=game_time_minutes,
                delivery_time_minutes=delivery_time_minutes,
                rest_stop_minutes=rest_stop_minutes,
                nav_distance_m=nav_distance_m,
                nav_time_s=nav_time_s,
                nav_speed_limit_ms=nav_speed_limit_ms,
                planned_distance_km=planned_distance_km,
                truck_speed_ms=truck_speed_ms,
                cargo_damage_pct=cargo_damage_pct,
                cargo_mass_kg=cargo_mass_kg,
                cargo_name=_decode(cargo_name),
                source_city=_decode(source_city),
                destination_city=_decode(destination_city),
                source_company=_decode(source_company),
                destination_company=_decode(destination_company),
                job_market=_decode(job_market),
                income=income,
                is_special_job=bool(is_special_job),
            )

        return TelemetryFrame.empty()
