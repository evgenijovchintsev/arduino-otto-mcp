"""FastAPI server for controlling OTTO robot via Bluetooth (HM-10 BLE module)."""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# HM-10 BLE serial service/characteristic UUIDs (standard for HM-10)
HM10_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
HM10_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

COMMANDS = {
    "forward": "F",
    "back": "B",
    "left": "L",
    "right": "R",
    "tiptoe": "T",
    "stop": "S",
}


class BLEConnection:
    def __init__(self) -> None:
        self.client: Optional[BleakClient] = None
        self.device_address: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def connect(self, address: str) -> None:
        async with self._lock:
            if self.is_connected:
                await self._disconnect()
            self.client = BleakClient(address)
            await self.client.connect()
            self.device_address = address

    async def _disconnect(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.client = None
            self.device_address = None

    async def disconnect(self) -> None:
        async with self._lock:
            await self._disconnect()

    async def send(self, char: str) -> None:
        async with self._lock:
            if not self.is_connected:
                raise HTTPException(status_code=503, detail="Not connected to device")
            data = char.encode("ascii")
            await self.client.write_gatt_char(HM10_CHAR_UUID, data, response=False)


ble = BLEConnection()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await ble.disconnect()


app = FastAPI(
    title="OTTO Robot BLE API",
    description="Control OTTO robot via Bluetooth HM-10 module",
    lifespan=lifespan,
)


# --- Models ---

class ConnectRequest(BaseModel):
    address: str


class ScanResult(BaseModel):
    address: str
    name: Optional[str]
    rssi: Optional[int]


# --- Endpoints ---

@app.get("/status")
async def status():
    return {
        "connected": ble.is_connected,
        "device_address": ble.device_address,
    }


@app.get("/scan", response_model=list[ScanResult])
async def scan(timeout: float = 5.0):
    """Scan for nearby BLE devices. Increase timeout for better discovery."""
    devices: list[BLEDevice] = await BleakScanner.discover(timeout=timeout)
    return [
        ScanResult(address=d.address, name=d.name, rssi=d.rssi)
        for d in sorted(devices, key=lambda d: d.rssi or -999, reverse=True)
    ]


@app.post("/connect")
async def connect(req: ConnectRequest):
    """Connect to HM-10 BLE module by MAC address."""
    try:
        await ble.connect(req.address)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Connection failed: {exc}") from exc
    return {"connected": True, "device_address": ble.device_address}


@app.post("/disconnect")
async def disconnect():
    await ble.disconnect()
    return {"connected": False}


@app.post("/command/{name}")
async def command(name: str):
    """
    Send a named command to OTTO.

    Available commands: forward, back, left, right, tiptoe, stop
    """
    char = COMMANDS.get(name)
    if char is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown command '{name}'. Available: {list(COMMANDS)}",
        )
    await ble.send(char)
    return {"command": name, "sent": char}


@app.get("/commands")
async def list_commands():
    return {"commands": {name: f"Sends '{char}'" for name, char in COMMANDS.items()}}
