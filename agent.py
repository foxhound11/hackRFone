"""
agent.py — RECON-1 Autonomous RF Threat Assessment Agent
=========================================================
Connects to the dashboard via WebSocket, tracks emitters across sweeps,
sends temporal events to an LLM for analysis, and persists all data to SQLite.

CHANGES FROM ORIGINAL:
- Added EmitterMemory class (novelty/transient detection)
- Added emitter_db integration (persistent SQLite storage)
- Added device_catalogue integration (known RF band annotations)
- Added rolling LLM context (last 3 responses)
- Added --learn baseline mode
- Added desktop alert on CRITICAL threats
- Added AGENT_STATUS broadcasts to dashboard
"""
import os
import sys
import asyncio
import websockets
import json
import time
import argparse
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
WS_URI = "ws://localhost:8081"  # Default, can be overridden by --port
LLM_INTERVAL = 5  # Call LLM every N sweeps
ACTION_LOG_FILE = "action_traces.json"

sweep_counter = 0
action_traces = []
llm_history = []  # Rolling context: last 3 LLM responses

AGENT_CONFIG = {
    "llm_enabled": True,
    "rtl433_enabled": True,
    "fft_enabled": False,
    "alerts_enabled": True
}


# ──────────────────────────────── IMPORTS ────────────────────────────────────

import emitter_db
import device_catalogue
import rtl_433_integration

try:
    import signal_analysis
    HAS_SIGNAL_ANALYSIS = True
except ImportError:
    HAS_SIGNAL_ANALYSIS = False
    print("[AGENT] signal_analysis.py not found — IQ analysis disabled")


# ──────────────────────────────── UTILITIES ──────────────────────────────────

async def log_to_dash(ws, msg):
    """Send a log message that appears in the dashboard UI log panel."""
    safe_msg = msg.encode('ascii', 'replace').decode('ascii')
    print(f"[AGENT] {safe_msg}")
    await ws.send(json.dumps({"type": "LOG", "msg": safe_msg}))


async def send_threat_cards(ws, llm_response):
    """Send the full LLM threat analysis to the dashboard UI."""
    payload = {
        "type": "THREAT_ANALYSIS",
        "signals": llm_response.get("signals", []),
        "commentary": llm_response.get("commentary", ""),
        "recommendation": llm_response.get("recommendation", "")
    }
    await ws.send(json.dumps(payload))


async def send_agent_status(ws, mode, detail=""):
    """Broadcast current agent state to dashboard."""
    await ws.send(json.dumps({
        "type": "AGENT_STATUS",
        "mode": mode,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }))


async def send_emitter_table(ws):
    """Push full emitter table from DB to dashboard."""
    emitters = emitter_db.get_all_emitters()
    await ws.send(json.dumps({
        "type": "EMITTER_TABLE",
        "emitters": emitters,
        "total": len(emitters),
        "baseline_count": emitter_db.get_baseline_count()
    }))


async def send_timeline(ws):
    """Push recent timeline events to dashboard."""
    events = emitter_db.get_timeline(limit=100)
    await ws.send(json.dumps({
        "type": "TIMELINE_DATA",
        "events": events
    }))


def save_action_trace(sweep_num, peaks_sent, llm_response):
    """Log every LLM interaction for the technical report."""
    trace = {
        "timestamp": datetime.now().isoformat(),
        "sweep_number": sweep_num,
        "peaks_sent": peaks_sent,
        "llm_response": llm_response
    }
    action_traces.append(trace)
    try:
        with open(ACTION_LOG_FILE, "w") as f:
            json.dump(action_traces, f, indent=2)
    except Exception:
        pass


def desktop_alert(title, message):
    """Fire a desktop notification for critical threats."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBeep(0x00000030)  # MB_ICONEXCLAMATION beep
        print(f"\n{'='*50}")
        print(f"  ALERT: {title}")
        print(f"  {message}")
        print(f"{'='*50}\n")
    except Exception:
        pass


# ──────────────────────────────── EMITTER MEMORY ────────────────────────────

class EmitterMemory:
    def __init__(self):
        self.emitters = {}  # freq_key -> stats
        self.sweep_count = 0
        self.baseline_freqs = emitter_db.get_baseline_freqs()
    
    def process_sweep(self, current_peaks):
        self.sweep_count += 1
        current_freqs = set()
        events = []
        
        for p in current_peaks:
            freq_key = round(p['freq_mhz'], 1)
            current_freqs.add(freq_key)
            
            # Persist to SQLite
            emitter_db.upsert_emitter(p['freq_mhz'], p['snr_db'], p['power_db'])
            
            if freq_key not in self.emitters:
                self.emitters[freq_key] = {
                    'first_seen': self.sweep_count,
                    'last_seen': self.sweep_count,
                    'hit_count': 1,
                    'max_snr': p['snr_db'],
                    'max_power': p['power_db'],
                    'freq_mhz': p['freq_mhz']
                }
                # Only fire APPEARED if not a known baseline signal
                is_baseline = str(freq_key) in self.baseline_freqs or f"{freq_key:.1f}" in self.baseline_freqs
                if not is_baseline:
                    event = {'type': 'APPEARED', 'freq_mhz': p['freq_mhz'], 'snr': p['snr_db'], 'hits': 1}
                    events.append(event)
                    emitter_db.log_timeline_event(p['freq_mhz'], 'APPEARED', p['snr_db'])
            else:
                e = self.emitters[freq_key]
                e['last_seen'] = self.sweep_count
                e['hit_count'] += 1
                e['max_snr'] = max(e['max_snr'], p['snr_db'])
                e['max_power'] = max(e['max_power'], p['power_db'])
                
        # Check for disappeared/persistent emitters
        dead_keys = []
        for freq_key, e in self.emitters.items():
            is_baseline = str(freq_key) in self.baseline_freqs or f"{freq_key:.1f}" in self.baseline_freqs
            if freq_key not in current_freqs:
                time_since_last = self.sweep_count - e['last_seen']
                if time_since_last == 1 and not is_baseline:
                    if e['hit_count'] <= 3:
                        event = {'type': 'TRANSIENT_BURST', 'freq_mhz': e['freq_mhz'], 'snr': e['max_snr'], 'hits': e['hit_count']}
                        events.append(event)
                        emitter_db.log_timeline_event(e['freq_mhz'], 'TRANSIENT_BURST', e['max_snr'])
                    else:
                        event = {'type': 'DISAPPEARED', 'freq_mhz': e['freq_mhz'], 'snr': e['max_snr'], 'hits': e['hit_count']}
                        events.append(event)
                        emitter_db.log_timeline_event(e['freq_mhz'], 'DISAPPEARED', e['max_snr'])
                if time_since_last > 10:
                    dead_keys.append(freq_key)
            else:
                time_active = self.sweep_count - e['first_seen'] + 1
                if time_active % 10 == 0 and not is_baseline:
                    events.append({'type': 'PERSISTENT', 'freq_mhz': e['freq_mhz'], 'snr': e['max_snr'], 'hits': e['hit_count']})
                    
        for k in dead_keys:
            del self.emitters[k]
            
        return events


# ──────────────────────────────── LLM DECISION ──────────────────────────────

async def ask_llm_decision(events, active_emitters):
    """Ask the LLM to analyze RF events with full context."""
    global llm_history
    
    # Annotate events with device catalogue info
    device_catalogue.annotate_events(events)
    
    interesting_events = [e for e in events if e['type'] in ('TRANSIENT_BURST', 'APPEARED')]
    if not interesting_events:
        interesting_events = [e for e in events if e['type'] == 'PERSISTENT']
        
    event_list = "\n".join([
        f"  - {e['type']} at {e['freq_mhz']:.3f} MHz | SNR: {e['snr']:.1f} dB"
        f" | Catalogue: {', '.join(e.get('catalogue', {}).get('likely_devices', ['Unknown'])[:2])}"
        f" | Decode: {e.get('rtl_decode', 'None')} | Modulation: {e.get('fft_mod', 'Unknown')}"
        for e in interesting_events[:15]
    ])

    # Rolling context from previous analyses
    context = ""
    if llm_history:
        context = "\n\nYour previous analyses (for context, do NOT repeat them):\n"
        for i, prev in enumerate(llm_history[-3:]):
            context += f"  [{i+1}] {prev.get('commentary', 'N/A')[:150]}...\n"

    # DB stats
    db_stats = f"Persistent DB: {emitter_db.get_emitter_count()} total emitters, {emitter_db.get_baseline_count()} baseline"

    prompt = f"""You are RECON-1, an autonomous RF threat assessment agent conducting live spectrum surveillance.

You are monitoring 300-500 MHz.
IMPORTANT NEW CONTEXT: As soon as a signal appears, our hardware automatically captures it and attempts to decode it.
The event list below contains the CONCRETE CONFIRMED RESULTS of those captures under the "Decode" and "Modulation" fields.

- If "Decode" says something specific (e.g. "CONFIRMED: Nissan TPMS"), this is 100% ground truth. Do NOT guess the device type, use the confirmed decode.
- If "Modulation" is "OOK", understand that OOK is trivially vulnerable to replay attacks (unlike FSK).
- "Catalogue" is just a backup frequency-band guess. Ignore the catalogue if a "Decode" exists.

Recent Events:
{event_list}

Active emitters in session: {len(active_emitters)}
{db_stats}
{context}

For EACH interesting event:
1. What device produces this signal? (Use "CONFIRMED: [Decode]" if decode exists, otherwise use "Likely: [Catalogue]").
2. Threat level: CRITICAL (OOK/trivially replayable), MEDIUM (Unknown/potentially exploitable), LOW (noise/unexploitable).
3. Brief tactical assessment.

Respond ONLY with this JSON (no markdown):
{{
  "signals": [
    {{"freq_mhz": 433.92, "device_type": "...", "threat_level": "CRITICAL|MEDIUM|LOW", "assessment": "..."}}
  ],
  "commentary": "First-person tactical narrative focusing on the newly confirmed decoded data.",
  "action": "SCAN"
}}"""

    try:
        def _call():
            headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
            data = {
                "model": "meta-llama/llama-3-8b-instruct",
                "messages": [{"role": "user", "content": prompt}]
            }
            resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                 headers=headers, json=data, timeout=30)
            return resp.json()["choices"][0]["message"]["content"]

        text = await asyncio.to_thread(_call)

        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        result = json.loads(text.strip())
        
        # Store in rolling history
        llm_history.append(result)
        if len(llm_history) > 5:
            llm_history = llm_history[-3:]
        
        return result, prompt, text.strip()
    except Exception as e:
        print(f"[LLM ERROR] {e}")
        return None, None, None


# ──────────────────────────────── LEARN MODE ────────────────────────────────

async def learn_baseline(num_sweeps=30):
    """Run in passive mode for N sweeps, then mark everything as baseline."""
    print(f"\n{'='*50}")
    print(f"  BASELINE LEARNING MODE — {num_sweeps} sweeps")
    print(f"  All signals detected will be marked as 'known background'")
    print(f"{'='*50}\n")
    
    memory = EmitterMemory()
    count = 0
    
    try:
        async with websockets.connect(WS_URI, ping_interval=None, ping_timeout=None) as ws:
            await log_to_dash(ws, f"RECON-1 entering LEARN mode. Baselining for {num_sweeps} sweeps...")
            await send_agent_status(ws, "LEARNING", f"0/{num_sweeps} sweeps")
            
            async for message in ws:
                data = json.loads(message)
                if data.get("type") != "sweep":
                    continue
                
                count += 1
                peaks = data.get("peaks", [])
                memory.process_sweep(peaks)
                
                if count % 5 == 0:
                    await log_to_dash(ws, f"LEARN: {count}/{num_sweeps} sweeps — {len(memory.emitters)} emitters found")
                    await send_agent_status(ws, "LEARNING", f"{count}/{num_sweeps} sweeps")
                
                if count >= num_sweeps:
                    break
            
            # Mark everything as baseline
            emitter_db.mark_all_as_baseline()
            baseline_count = emitter_db.get_baseline_count()
            
            await log_to_dash(ws, f"BASELINE COMPLETE: {baseline_count} emitters marked as known background.")
            await send_agent_status(ws, "IDLE", "Baseline learning complete")
            print(f"\n[LEARN] Done. {baseline_count} emitters marked as baseline in emitters.db")
            
    except Exception as e:
        print(f"[LEARN] Error: {e}")


async def capture_and_analyze(ws, freq):
    """Pause sweep, capture IQ data, and run rtl_433 and signal_analysis."""
    await log_to_dash(ws, f"ACTION: AUTO-CAPTURE on {freq} MHz")
    await send_agent_status(ws, "CAPTURING", f"{freq} MHz")

    capture_file = os.path.join("captures", f"focus_{int(freq*1e6)}_hz.iq")
    os.makedirs("captures", exist_ok=True)
    hackrf_transfer = r"C:\Program Files\PothosSDR\bin\hackrf_transfer.exe"
    sample_rate = 2000000
    num_samples = sample_rate * 2  # 2 seconds

    await log_to_dash(ws, f"CAPTURE: Recording {freq} MHz for 2 seconds...")
    await ws.send(json.dumps({"type": "CMD", "action": "PAUSE_SWEEP"}))
    await asyncio.sleep(0.5)

    capture_ok = False
    try:
        proc = await asyncio.create_subprocess_exec(
            hackrf_transfer, "-r", capture_file, "-f", str(int(freq * 1e6)),
            "-s", str(sample_rate), "-n", str(num_samples), "-l", "32", "-g", "20",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=10)
        capture_ok = os.path.exists(capture_file) and os.path.getsize(capture_file) > 1000
        if capture_ok:
            await log_to_dash(ws, f"CAPTURE: Saved {os.path.getsize(capture_file)} bytes to {capture_file}")
        else:
            err = stderr_data.decode("utf-8", errors="replace").strip() if stderr_data else "unknown"
            await log_to_dash(ws, f"CAPTURE FAILED: {err}")
    except Exception as e:
        await log_to_dash(ws, f"CAPTURE ERROR: {e}")

    await ws.send(json.dumps({"type": "CMD", "action": "RESUME_SWEEP"}))

    decode_result = None
    iq_result = None
    proto = None

    if capture_ok and rtl_433_integration.IS_AVAILABLE and AGENT_CONFIG["rtl433_enabled"]:
        await send_agent_status(ws, "DECODING", f"rtl_433 on {freq} MHz")
        await log_to_dash(ws, f"RTL_433: Decoding captured IQ file...")
        decode_result = await rtl_433_integration.decode_iq_file(capture_file, freq_hz=int(freq * 1e6), sample_rate=sample_rate)
        if decode_result and decode_result.get("decoded"):
            d = decode_result["decoded"][0]
            proto = d.get("protocol", "Unknown")
            dev_id = d.get("id", "?")
            await log_to_dash(ws, f"RTL_433 CONFIRMED: {proto} (ID: {dev_id})")
            emitter_db.upsert_emitter(freq, 0, 0, agent_label=f"CONFIRMED: {proto}")
        else:
            await log_to_dash(ws, f"RTL_433: No known protocols decoded at {freq} MHz")

    if capture_ok and HAS_SIGNAL_ANALYSIS and AGENT_CONFIG["fft_enabled"]:
        await send_agent_status(ws, "FFT", f"Analyzing {freq} MHz")
        iq_result = signal_analysis.analyze_iq_file(capture_file, sample_rate=sample_rate)
        if iq_result and iq_result.get("detected"):
            mod = iq_result.get("modulation", "UNKNOWN")
            bursts = iq_result.get("burst_count", 0)
            await log_to_dash(ws, f"IQ ANALYSIS: {mod} modulation, {bursts} bursts")
            await ws.send(json.dumps({
                "type": "IQ_DIAGNOSTICS", "freq_mhz": freq, "modulation": mod,
                "bursts": bursts, "confidence": iq_result.get("confidence", 0),
                "fsk_dev": iq_result.get("fsk_deviation_khz", 0),
                "fft_peaks": iq_result.get("fft_peaks", [])
            }))
            
    await send_agent_status(ws, "SCANNING", "Passive monitoring")
    return proto, iq_result

# ──────────────────────────────── MAIN AGENT LOOP ───────────────────────────

async def agent_loop():
    global sweep_counter
    memory = EmitterMemory()
    event_buffer = []
    
    # Rate limiting for auto-capture
    last_capture_time = 0
    captured_freqs = set()

    print(f"Connecting to dashboard at {WS_URI}...")
    try:
        async with websockets.connect(WS_URI, ping_interval=None, ping_timeout=None) as ws:
            baseline_count = emitter_db.get_baseline_count()
            total_count = emitter_db.get_emitter_count()
            await log_to_dash(ws, f"RECON-1 online. DB: {total_count} emitters ({baseline_count} baseline). Novelty detection active.")
            await send_agent_status(ws, "SCANNING", "Passive monitoring")
            await send_emitter_table(ws)

            async for message in ws:
                data = json.loads(message)

                if data.get("type") == "SETTINGS":
                    global AGENT_CONFIG
                    AGENT_CONFIG["llm_enabled"] = data.get("llm_enabled", True)
                    AGENT_CONFIG["rtl433_enabled"] = data.get("rtl433_enabled", True)
                    AGENT_CONFIG["fft_enabled"] = data.get("fft_enabled", True)
                    AGENT_CONFIG["alerts_enabled"] = data.get("alerts_enabled", True)
                    await log_to_dash(ws, "SYSTEM: Agent Feature configuration securely updated via Dashboard.")
                    continue

                if data.get("type") != "sweep":
                    continue

                sweep_counter += 1
                peaks = data.get("peaks", [])

                new_events = memory.process_sweep(peaks)
                
                # --- AUTO-CAPTURE: DEMO MODE ---
                # ONLY capture in 433-434 MHz (ISM band where Flipper transmits)
                # Hard cap: 3 captures per session, 30s cooldown between captures
                CAPTURE_RANGE = (433.0, 434.0)
                MAX_CAPTURES = 3
                CAPTURE_COOLDOWN = 30
                
                now = time.time()
                best_candidate = None
                
                if len(captured_freqs) < MAX_CAPTURES and (now - last_capture_time > CAPTURE_COOLDOWN):
                    for event in new_events:
                        if event['type'] in ('TRANSIENT_BURST', 'APPEARED'):
                            f = event['freq_mhz']
                            if CAPTURE_RANGE[0] <= f <= CAPTURE_RANGE[1] and event.get('snr', 0) >= 12:
                                if best_candidate is None or event.get('snr', 0) > best_candidate.get('snr', 0):
                                    best_candidate = event
                
                if best_candidate:
                    freq = best_candidate['freq_mhz']
                    captured_freqs.add(round(freq, 1))
                    last_capture_time = time.time()
                    await log_to_dash(ws, f"⚡ DEMO CAPTURE #{len(captured_freqs)}/{MAX_CAPTURES} — targeting {freq:.3f} MHz")
                    
                    proto, iq_result = await capture_and_analyze(ws, freq)
                    
                    if proto:
                        best_candidate['rtl_decode'] = proto
                    if iq_result and iq_result.get('detected'):
                        best_candidate['fft_mod'] = iq_result.get('modulation', 'UNKNOWN')
                        best_candidate['fft_bursts'] = iq_result.get('burst_count', 0)
                
                event_buffer.extend(new_events)

                # Every N sweeps, send accumulated events to LLM
                if sweep_counter % LLM_INTERVAL == 0:
                    # Push updated emitter table and timeline to dashboard
                    await send_emitter_table(ws)
                    await send_timeline(ws)
                    
                    if not event_buffer:
                        await send_agent_status(ws, "SCANNING", "No new events")
                        continue

                    if not AGENT_CONFIG["llm_enabled"]:
                        await log_to_dash(ws, f"Sweep #{sweep_counter} | LLM Analysis disabled by dashboard override. Skipping {len(event_buffer)} events.")
                        event_buffer = []
                        continue

                    await log_to_dash(ws, f"Sweep #{sweep_counter} | {len(memory.emitters)} session / {emitter_db.get_emitter_count()} DB emitters. Analyzing {len(event_buffer)} events...")
                    await send_agent_status(ws, "EVALUATING", f"{len(event_buffer)} events")

                    try:
                        result, llm_prompt, llm_response = await asyncio.wait_for(ask_llm_decision(event_buffer, memory.emitters), timeout=30)
                    except asyncio.TimeoutError:
                        await log_to_dash(ws, "LLM timeout. Will retry next cycle.")
                        event_buffer = []
                        continue

                    if result:
                        await ws.send(json.dumps({
                            "type": "LLM_TRACE", 
                            "prompt": llm_prompt, 
                            "response": llm_response
                        }))
                        save_action_trace(sweep_counter, event_buffer, result)
                        
                        # Update DB with LLM labels
                        for s in result.get("signals", []):
                            emitter_db.upsert_emitter(
                                s.get("freq_mhz", 0), 0, 0,
                                agent_label=s.get("device_type", ""),
                                threat_level=s.get("threat_level", "")
                            )
                        
                        # Format for dashboard threat cards
                        out_signals = []
                        for s in result.get("signals", []):
                            out_signals.append({
                                "freq_mhz": s.get("freq_mhz", 0),
                                "max_snr": 0,
                                "device": s.get("device_type", "Unknown"),
                                "threat": s.get("threat_level", "LOW"),
                                "device_type": s.get("device_type", "Unknown"),
                                "threat_level": s.get("threat_level", "LOW"),
                                "assessment": s.get("assessment", "")
                            })
                        result["signals"] = out_signals
                        
                        await send_threat_cards(ws, result)

                        commentary = result.get("commentary", "")
                        if commentary:
                            await log_to_dash(ws, f"RECON-1: {commentary}")

                        # Desktop alert for critical threats
                        crits = [s for s in result.get("signals", []) if s.get("threat_level") == "CRITICAL" or s.get("threat") == "CRITICAL"]
                        if crits:
                            freq_str = ", ".join(f"{s.get('freq_mhz', 0):.1f} MHz" for s in crits)
                            if AGENT_CONFIG["alerts_enabled"]:
                                desktop_alert("CRITICAL RF THREAT", f"Detected at {freq_str}")
                            await ws.send(json.dumps({"type": "ALERT", "level": "CRITICAL", "message": f"Critical threat at {freq_str}"}))

                    else:
                        await log_to_dash(ws, "LLM returned empty response. Retrying next cycle.")

                    event_buffer = []

    except Exception as e:
        print(f"Connection error: {e}")
        await asyncio.sleep(2)


async def main():
    global WS_URI
    parser = argparse.ArgumentParser(description="RECON-1 RF Agent")
    parser.add_argument("--learn", type=int, default=0, help="Enter baseline learning mode for N sweeps")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard HTTP port (default 8080)")
    args = parser.parse_args()
    
    WS_URI = f"ws://localhost:{args.port + 1}"
    
    if args.learn > 0:
        await learn_baseline(args.learn)
    else:
        while True:
            await agent_loop()


if __name__ == "__main__":
    asyncio.run(main())
