import asyncio
import os

HACKRF_TRANSFER = r"C:\Program Files\PothosSDR\bin\hackrf_transfer.exe"

async def record_signal(frequency_hz, duration_sec, filename, sample_rate_hz=2000000, rx_lna=32, rx_vga=20):
    """
    Records raw IQ data from the given frequency for a specific duration.
    """
    cmd = [
        HACKRF_TRANSFER,
        "-r", filename,
        "-f", str(int(frequency_hz)),
        "-s", str(int(sample_rate_hz)),
        "-l", str(int(rx_lna)),
        "-g", str(int(rx_vga))
    ]
    print(f"[TOOLS] Recording {frequency_hz/1e6} MHz to {filename} for {duration_sec}s...")
    await asyncio.sleep(2.0)  # Let HackRF fully release from any previous process
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Record for the desired duration
    await asyncio.sleep(duration_sec)
    
    # Stop the transfer
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
            
    print(f"[TOOLS] Recording complete: {filename}")
    size = os.path.getsize(filename) if os.path.exists(filename) else 0
    return {"status": "success", "file": filename, "size_bytes": size}

async def replay_signal(frequency_hz, filename, sample_rate_hz=2000000, tx_vga=40):
    """
    Transmits/replays raw IQ data from a file continuously until finished.
    """
    if not os.path.exists(filename):
        return {"status": "error", "message": f"File {filename} not found."}
        
    cmd = [
        HACKRF_TRANSFER,
        "-t", filename,
        "-f", str(int(frequency_hz)),
        "-s", str(int(sample_rate_hz)),
        "-x", str(int(tx_vga)),
        "-a", "1"  # Enable TX amplifier
    ]
    print(f"[TOOLS] Replaying {filename} at {frequency_hz/1e6} MHz...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Wait for the transmission to finish
    await proc.wait()
    print(f"[TOOLS] Replay complete.")
    return {"status": "success"}

# Quick standalone test block
if __name__ == "__main__":
    async def test():
        print("Testing tools.py...")
        # Will just print, won't actually execute unless called
    asyncio.run(test())
