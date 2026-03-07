"""
rtl_433_integration.py — rtl_433 Signal Decoder Integration
=============================================================
Wraps the rtl_433 command-line tool to provide actual signal identification.

rtl_433 decodes 200+ wireless protocols (weather stations, TPMS, key fobs,
doorbells, smoke detectors, etc.) and outputs structured JSON. This is the
ONLY way to confirm what a device actually is — frequency matching alone
cannot distinguish a key fob from a spoofed replay.

INSTALL rtl_433:
  Windows: Download from https://github.com/merbanan/rtl_433/releases
           Extract to C:\\Program Files\\rtl_433\\rtl_433.exe
  Linux:   apt install rtl-433  (or build from source)

This module can run rtl_433 in two modes:
  1. LIVE: Runs rtl_433 against the HackRF hardware for real-time decoding
  2. FILE: Runs rtl_433 against a captured IQ file for offline analysis

NEW FILE — can be deleted to revert this feature.
"""

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone

# Try common install locations
RTL_433_PATHS = [
    r"C:\Program Files\rtl_433\rtl_433.exe",
    r"C:\Program Files\PothosSDR\bin\rtl_433.exe",
    r"C:\PothosSDR\bin\rtl_433.exe",
    "rtl_433",  # If on PATH
]

def find_rtl_433():
    """Find the rtl_433 binary."""
    for path in RTL_433_PATHS:
        if os.path.isfile(path):
            return path
    # Try running it from PATH
    try:
        result = subprocess.run(["rtl_433", "-V"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "rtl_433"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


RTL_433_CMD = find_rtl_433()
IS_AVAILABLE = RTL_433_CMD is not None


def get_status():
    """Return status dict for dashboard/agent."""
    return {
        "available": IS_AVAILABLE,
        "path": RTL_433_CMD or "NOT FOUND",
        "note": "rtl_433 provides actual protocol decoding (200+ protocols)"
    }


async def decode_frequency_live(freq_hz, duration_sec=5, device_type="hackrf"):
    """Run rtl_433 in live mode, listening on a specific frequency.
    
    Returns a list of decoded protocol matches (or empty list if none/unavailable).
    
    Args:
        freq_hz: Center frequency in Hz (e.g. 433920000)
        duration_sec: How long to listen
        device_type: "hackrf" or "rtlsdr"
    """
    if not IS_AVAILABLE:
        return {"status": "rtl_433_not_installed", "decoded": [],
                "note": "Install rtl_433 for actual protocol identification"}
    
    cmd = [
        RTL_433_CMD,
        "-f", str(int(freq_hz)),
        "-F", "json",          # Output JSON
        "-T", str(duration_sec),  # Run for N seconds then exit
        "-M", "level",         # Include signal level
        "-M", "protocol",      # Include protocol info
    ]
    
    if device_type == "hackrf":
        cmd.extend(["-d", "driver=hackrf"])
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=duration_sec + 10
        )
        
        decoded = []
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            line = line.strip()
            if line and line.startswith("{"):
                try:
                    obj = json.loads(line)
                    decoded.append({
                        "protocol": obj.get("model", "Unknown"),
                        "id": obj.get("id", ""),
                        "channel": obj.get("channel", ""),
                        "data": {k: v for k, v in obj.items() 
                                 if k not in ("time", "model", "id", "channel")},
                        "raw_json": obj,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                except json.JSONDecodeError:
                    pass
        
        return {
            "status": "success",
            "decoded": decoded,
            "device_count": len(decoded),
            "freq_hz": freq_hz,
            "duration_sec": duration_sec,
            "note": f"rtl_433 decoded {len(decoded)} transmissions"
        }
        
    except asyncio.TimeoutError:
        return {"status": "timeout", "decoded": [], "note": "rtl_433 timed out"}
    except Exception as e:
        return {"status": "error", "decoded": [], "note": str(e)}


async def decode_iq_file(filepath, freq_hz=433920000, sample_rate=2000000):
    """Run rtl_433 against a previously captured IQ file.
    
    This is used after the HackRF captures a focused recording — we pipe
    the IQ data through rtl_433 for offline protocol identification.
    """
    if not IS_AVAILABLE:
        return {"status": "rtl_433_not_installed", "decoded": [],
                "note": "Install rtl_433 for actual protocol identification"}
    
    if not os.path.exists(filepath):
        return {"status": "file_not_found", "decoded": [], "note": f"File not found: {filepath}"}
    
    cmd = [
        RTL_433_CMD,
        "-r", filepath,           # Read from file
        "-F", "json",             # Output JSON
        "-s", str(sample_rate),   # Sample rate
        "-M", "level",
        "-M", "protocol",
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        
        decoded = []
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            line = line.strip()
            if line and line.startswith("{"):
                try:
                    obj = json.loads(line)
                    decoded.append({
                        "protocol": obj.get("model", "Unknown"),
                        "id": obj.get("id", ""),
                        "data": {k: v for k, v in obj.items()
                                 if k not in ("time", "model", "id")},
                        "raw_json": obj,
                    })
                except json.JSONDecodeError:
                    pass
        
        return {
            "status": "success",
            "decoded": decoded,
            "device_count": len(decoded),
            "filepath": filepath,
            "note": f"rtl_433 decoded {len(decoded)} transmissions from file"
        }
        
    except Exception as e:
        return {"status": "error", "decoded": [], "note": str(e)}


def format_decoded_for_llm(decode_result):
    """Format rtl_433 decoding results into a string for the LLM prompt."""
    if not decode_result or decode_result.get("status") != "success":
        return "  rtl_433: No decodings available (tool not installed or no signals decoded)"
    
    decoded = decode_result.get("decoded", [])
    if not decoded:
        return "  rtl_433: Listened but decoded 0 known protocols. Signal may use proprietary encoding."
    
    lines = []
    for d in decoded[:10]:  # Limit to 10
        proto = d.get("protocol", "Unknown")
        dev_id = d.get("id", "?")
        data_str = json.dumps(d.get("data", {}))[:100]
        lines.append(f"  CONFIRMED: {proto} (ID: {dev_id}) — {data_str}")
    
    return "\n".join(lines)


# Print status on import
if IS_AVAILABLE:
    print(f"[RTL_433] Found: {RTL_433_CMD}")
else:
    print("[RTL_433] Not installed. Install from https://github.com/merbanan/rtl_433/releases")
    print("[RTL_433] Without rtl_433, device identification is frequency-guessing only.")
