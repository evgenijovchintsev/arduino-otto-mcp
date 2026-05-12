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
from fastapi_mcp import FastApiMCP

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
        self._write_with_response: bool = False
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

                    # Discover the TX characteristic and pick the correct write mode
                    tx_char = client.services.get_characteristic(HM10_CHAR_UUID)
                    if tx_char is None:
                        log.error("Characteristic %s not found. Available:", HM10_CHAR_UUID)
                        for svc in client.services:
                            for c in svc.characteristics:
                                log.error("  %s  props=%s", c.uuid, c.properties)
                        await client.disconnect()
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue

                    write_with_response = "write" in tx_char.properties
                    log.info(
                        "TX char %s  props=%s  → response=%s",
                        tx_char.uuid, tx_char.properties, write_with_response,
                    )

                    async with self._lock:
                        self.client = client
                        self.device_address = device.address
                        self._write_with_response = write_with_response
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
            data = char.encode("ascii")
            log.info("Sending 0x%s ('%s')  response=%s", data.hex().upper(), char, self._write_with_response)
            try:
                await self.client.write_gatt_char(HM10_CHAR_UUID, data, response=self._write_with_response)
            except Exception as exc:
                log.error("Write failed: %s", exc)
                raise HTTPException(status_code=502, detail=f"BLE write error: {exc}") from exc


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
        f"Automatically connects to `{DEVICE_NAME}` on startup.\n\n"
        "## Quick start\n\n"
        "Check connection status:\n"
        "```bash\n"
        "curl http://localhost:8000/status\n"
        "```\n\n"
        "Send a command:\n"
        "```bash\n"
        "curl -X POST http://localhost:8000/forward\n"
        "```"
    ),
    lifespan=lifespan,
)


@app.get(
    "/status",
    operation_id="get_status",
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "connected": {
                            "summary": "Device connected",
                            "value": {
                                "connected": True,
                                "device": "HMSoft",
                                "device_address": "AA:BB:CC:DD:EE:FF",
                            },
                        },
                        "connecting": {
                            "summary": "Still scanning / connecting",
                            "value": {
                                "connected": False,
                                "device": "HMSoft",
                                "device_address": None,
                            },
                        },
                    }
                }
            }
        }
    },
)
async def status():
    """
    Connection status and device address.

    ```bash
    curl http://localhost:8000/status
    ```
    """
    return {
        "connected": ble.is_connected,
        "device": DEVICE_NAME,
        "device_address": ble.device_address,
    }


_503 = {
    503: {
        "description": "Not yet connected to HMSoft",
        "content": {
            "application/json": {
                "example": {"detail": "Not connected to 'HMSoft' yet, please wait"}
            }
        },
    }
}


@app.post("/forward", operation_id="forward", tags=["Move"], responses=_503)
async def forward():
    """Make OTTO walk one step forward."""
    await ble.send("F")
    return {"command": "forward", "sent": "F"}


@app.post("/back", operation_id="back", tags=["Move"], responses=_503)
async def back():
    """Make OTTO walk one step backward."""
    await ble.send("B")
    return {"command": "back", "sent": "B"}


@app.post("/left", operation_id="left", tags=["Move"], responses=_503)
async def left():
    """Make OTTO turn left."""
    await ble.send("L")
    return {"command": "left", "sent": "L"}


@app.post("/right", operation_id="right", tags=["Move"], responses=_503)
async def right():
    """Make OTTO turn right."""
    await ble.send("R")
    return {"command": "right", "sent": "R"}


@app.post("/tiptoe", operation_id="tiptoe", tags=["Move"], responses=_503)
async def tiptoe():
    """Make OTTO do a tiptoe swing dance move."""
    await ble.send("T")
    return {"command": "tiptoe", "sent": "T"}


@app.post("/stop", operation_id="stop", tags=["Move"], responses=_503)
async def stop():
    """Stop OTTO and return to home position."""
    await ble.send("S")
    return {"command": "stop", "sent": "S"}


@app.get(
    "/commands",
    operation_id="list_commands",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "commands": {
                            "forward": "Sends 'F'",
                            "back": "Sends 'B'",
                            "left": "Sends 'L'",
                            "right": "Sends 'R'",
                            "tiptoe": "Sends 'T'",
                            "stop": "Sends 'S'",
                        }
                    }
                }
            }
        }
    },
)
async def list_commands():
    """
    List all available commands.

    ```bash
    curl http://localhost:8000/commands
    ```
    """
    return {"commands": {name: f"Sends '{char}'" for name, char in COMMANDS.items()}}


mcp = FastApiMCP(
    app,
    include_operations=["get_status", "forward", "back", "left", "right", "tiptoe", "stop"],
)
mcp.mount()
