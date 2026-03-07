import os
import asyncio
import websockets
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
WS_URI = "ws://localhost:8889"
LLM_INTERVAL = 5  # Call LLM every N sweeps
ACTION_LOG_FILE = "action_traces.json"

sweep_counter = 0
action_traces = []


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


# ──────────────────────────────── EMITTER MEMORY ────────────────────────────────

class EmitterMemory:
    def __init__(self):
        self.emitters = {}  # freq_key -> stats
        self.sweep_count = 0
    
    def process_sweep(self, current_peaks):
        self.sweep_count += 1
        current_freqs = set()
        events = []
        
        for p in current_peaks:
            # Group by 100kHz bins to avoid jitter
            freq_key = round(p['freq_mhz'], 1)
            current_freqs.add(freq_key)
            
            if freq_key not in self.emitters:
                # NEW signal appeared
                self.emitters[freq_key] = {
                    'first_seen': self.sweep_count,
                    'last_seen': self.sweep_count,
                    'hit_count': 1,
                    'max_snr': p['snr_db'],
                    'max_power': p['power_db'],
                    'freq_mhz': p['freq_mhz']
                }
                events.append({'type': 'APPEARED', 'freq_mhz': p['freq_mhz'], 'snr': p['snr_db'], 'hits': 1})
            else:
                e = self.emitters[freq_key]
                e['last_seen'] = self.sweep_count
                e['hit_count'] += 1
                e['max_snr'] = max(e['max_snr'], p['snr_db'])
                e['max_power'] = max(e['max_power'], p['power_db'])
                
        # Check for missing/persistent emitters
        dead_keys = []
        for freq_key, e in self.emitters.items():
            if freq_key not in current_freqs:
                time_since_last = self.sweep_count - e['last_seen']
                if time_since_last == 1:
                    # Just disappeared this sweep
                    if e['hit_count'] <= 3:
                        events.append({'type': 'TRANSIENT_BURST', 'freq_mhz': e['freq_mhz'], 'snr': e['max_snr'], 'hits': e['hit_count']})
                    else:
                        events.append({'type': 'DISAPPEARED', 'freq_mhz': e['freq_mhz'], 'snr': e['max_snr'], 'hits': e['hit_count']})
                if time_since_last > 10:
                    dead_keys.append(freq_key)
            else:
                # Still active
                time_active = self.sweep_count - e['first_seen'] + 1
                if time_active % 10 == 0:
                    events.append({'type': 'PERSISTENT', 'freq_mhz': e['freq_mhz'], 'snr': e['max_snr'], 'hits': e['hit_count']})
                    
        for k in dead_keys:
            del self.emitters[k]
            
        return events


# ──────────────────────────────── AGENT LOGIC ─────────────────────────────────

async def ask_llm_decision(events, active_emitters):
    """Ask the LLM to analyze RF events and decide what to focus on."""
    
    # Filter for the most interesting events (transients and new appearances)
    interesting_events = [e for e in events if e['type'] in ('TRANSIENT_BURST', 'APPEARED')]
    if not interesting_events:
        # If nothing new/transient, just summarize the persistent ones
        interesting_events = [e for e in events if e['type'] == 'PERSISTENT']
        
    event_list = "\n".join([
        f"  - {e['type']} at {e['freq_mhz']:.3f} MHz | SNR: {e['snr']:.1f} dB | Hits: {e['hits']}"
        for e in interesting_events[:15]
    ])

    prompt = f"""You are RECON-1, an autonomous RF threat assessment agent conducting live spectrum surveillance.

You are monitoring 300-500 MHz. Instead of raw peaks, you are now receiving temporal EVENT logs. 
A "TRANSIENT_BURST" is a short transmission (like a key fob). An "APPEARED" is a new signal. A "PERSISTENT" is a continuous carrier (like a TV station or steady telemetry, usually boring).

Recent Events:
{event_list}

Total active emitters tracked in background: {len(active_emitters)}

For EACH interesting event, determine:
1. What device likely produces this signal
2. Threat level: CRITICAL (simple OOK/static codes, trivially replayable), MEDIUM (FSK or unknown modulation), LOW (encrypted, rolling codes, or infrastructure)
3. Tactical assessment

Then give your RECOMMENDATION: If there is a suspicious TRANSIENT or APPEARED event (like a potential key fob at 433.9 MHz), you should recommend a FOCUS action on that frequency. If everything is just stable background noise, recommend continuing to scan.

Respond ONLY with this JSON (no markdown):
{{
  "signals": [
    {{"freq_mhz": 433.92, "device_type": "...", "threat_level": "CRITICAL|MEDIUM|LOW", "assessment": "..."}}
  ],
  "commentary": "Your first-person tactical narrative. Focus on transients vs background.",
  "action": "FOCUS" or "SCAN",
  "focus_freq_mhz": 433.92  // ONLY include if action is FOCUS
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

        return json.loads(text.strip())
    except Exception as e:
        print(f"[LLM ERROR] {e}")
        return None


async def agent_loop():
    global sweep_counter
    memory = EmitterMemory()
    event_buffer = []

    print(f"Connecting to dashboard at {WS_URI}...")
    try:
        async with websockets.connect(WS_URI, ping_interval=None, ping_timeout=None) as ws:
            await log_to_dash(ws, "RECON-1 online. Temporal novelty detection active.")

            async for message in ws:
                data = json.loads(message)

                if data.get("type") != "sweep":
                    continue

                sweep_counter += 1
                peaks = data.get("peaks", [])

                # Process novelty and accumulate events
                new_events = memory.process_sweep(peaks)
                event_buffer.extend(new_events)

                # Every N sweeps, send accumulated events to LLM
                if sweep_counter % LLM_INTERVAL == 0:
                    if not event_buffer:
                        continue

                    await log_to_dash(ws, f"Sweep #{sweep_counter} | {len(memory.emitters)} emitters tracked. Analyzing {len(event_buffer)} recent events...")

                    try:
                        result = await asyncio.wait_for(ask_llm_decision(event_buffer, memory.emitters), timeout=30)
                    except asyncio.TimeoutError:
                        await log_to_dash(ws, "LLM timeout. Will retry next cycle.")
                        event_buffer = []
                        continue

                    if result:
                        save_action_trace(sweep_counter, event_buffer, result)
                        
                        # Fix the signals format for the dashboard Threat Cards
                        out_signals = []
                        for s in result.get("signals", []):
                            out_signals.append({
                                "freq_mhz": s.get("freq_mhz", 0),
                                "max_snr": 0, # Placeholder since we didn't pass it back
                                "device": s.get("device_type", "Unknown"),
                                "threat": s.get("threat_level", "LOW")
                            })
                        result["signals"] = out_signals
                        
                        await send_threat_cards(ws, result)

                        commentary = result.get("commentary", "")
                        if commentary:
                            await log_to_dash(ws, f"RECON-1: {commentary}")

                        action = result.get("action", "SCAN")
                        if action == "FOCUS":
                            freq = result.get("focus_freq_mhz")
                            if freq:
                                await log_to_dash(ws, f"ACTION PRESCRIBED: FOCUS on {freq} MHz")
                                await ws.send(json.dumps({"type": "CMD", "action": "CAPTURE", "freq_hz": int(freq*1e6)}))
                        else:
                            await log_to_dash(ws, "ACTION PRESCRIBED: Continue SCAN")

                    else:
                        await log_to_dash(ws, "LLM returned empty response. Retrying next cycle.")

                    event_buffer = []

    except Exception as e:
        print(f"Connection error: {e}")
        await asyncio.sleep(2)


async def main():
    while True:
        await agent_loop()


if __name__ == "__main__":
    asyncio.run(main())
