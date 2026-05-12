"""FastAPI server for controlling OTTO robot via Bluetooth (HM-10 BLE module).

On startup, automatically scans for a device named HMSoft and connects to it.
Reconnects automatically if the connection drops.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from bleak import BleakClient, BleakScanner
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HM10_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "HMSoft"
SCAN_TIMEOUT = 10.0       # seconds per scan attempt
RECONNECT_DELAY = 5.0     # seconds between reconnect attempts

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
        self._task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def _connect_loop(self) -> None:
        while True:
            try:
                if not self.is_connected:
                    log.info("Scanning for '%s'...", DEVICE_NAME)
                    device = await BleakScanner.find_device_by_name(
                        DEVICE_NAME, timeout=SCAN_TIMEOUT
                    )
                    if device is None:
                        log.warning("'%s' not found, retrying in %.0fs", DEVICE_NAME, RECONNECT_DELAY)
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue

                    log.info("Connecting to %s (%s)...", device.name, device.address)
                    client = BleakClient(device)
                    await client.connect()
                    async with self._lock:
                        self.client = client
                        self.device_address = device.address
                    log.info("Connected to %s", device.address)

                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("BLE error: %s", exc)
                async with self._lock:
                    self.client = None
                    self.device_address = None
                await asyncio.sleep(RECONNECT_DELAY)

    def start(self) -> None:
        self._task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def send(self, char: str) -> None:
        async with self._lock:
            if not self.is_connected:
                raise HTTPException(
                    status_code=503,
                    detail=f"Not connected to '{DEVICE_NAME}' yet, please wait",
                )
            await self.client.write_gatt_char(
                HM10_CHAR_UUID, char.encode("ascii"), response=False
            )


ble = BLEConnection()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ble.start()
    yield
    await ble.stop()


app = FastAPI(
    title="OTTO Robot BLE API",
    description=(
        f"Controls OTTO robot via Bluetooth HM-10 module. "
        f"Automatically connects to '{DEVICE_NAME}' on startup."
    ),
    lifespan=lifespan,
)


@app.get("/status")
async def status():
    """Connection status and device address."""
    return {
        "connected": ble.is_connected,
        "device": DEVICE_NAME,
        "device_address": ble.device_address,
    }


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
    """List all available commands."""
    return {"commands": {name: f"Sends '{char}'" for name, char in COMMANDS.items()}}
