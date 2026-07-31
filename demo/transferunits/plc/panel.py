"""Panel — FastAPI web interface for the TransferUnit PLC.

This module provides the HTTP interface for operators to view and control the PLC.
It has no MQTT logic and no asyncio imports — those belong in transfer_unit.py.

The panel polls /api/state every 500ms and displays:
- Actual belt speeds (from PLC speeds)
- Commanded speeds (from PLC setpoints) — shown ONLY when divergent from actual
- Light barrier states (occupied/clear)

Tooltips name the backend files (transfer_unit.py set_speed(), etc.)
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .transfer_unit import TransferUnit

app = FastAPI()
plc: TransferUnit | None = None


def get_plc() -> TransferUnit:
    """Get the PLC instance, raising if not configured."""
    if plc is None:
        raise RuntimeError("PLC not configured. Call configure_plc() first.")
    return plc


def configure_plc(instance: TransferUnit) -> None:
    """Configure the PLC instance for the panel."""
    global plc
    plc = instance


@app.get("/api/state")
async def state() -> JSONResponse:
    """Return the current PLC state snapshot."""
    return JSONResponse(get_plc().snapshot())


@app.post("/api/speed/{position}")
async def set_speed(position: str, request: Request) -> JSONResponse:
    """Set the speed for a belt position."""
    if position not in ("left", "right"):
        raise HTTPException(status_code=404, detail=f"Unknown position: {position}")

    try:
        body = await request.json()
        value = float(body["value"])
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid value: {e}")

    await get_plc().set_speed(position, value)
    return JSONResponse(get_plc().snapshot())


@app.post("/api/barrier/{position}")
async def set_barrier(position: str, request: Request) -> JSONResponse:
    """Set the occupancy state for a light barrier."""
    if position not in ("front", "back"):
        raise HTTPException(status_code=404, detail=f"Unknown position: {position}")

    try:
        body = await request.json()
        occupied = bool(body["occupied"])
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid value: {e}")

    await get_plc().set_occupied(position, occupied)
    return JSONResponse(get_plc().snapshot())


@app.get("/", response_class=HTMLResponse)
async def panel() -> HTMLResponse:
    """Serve the panel HTML page."""
    from pathlib import Path
    template_path = Path(__file__).parent / "templates" / "panel.html"
    html_content = template_path.read_text(encoding="utf-8")
    return HTMLResponse(html_content)