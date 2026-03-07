#!/usr/bin/env python3
"""
RF RECON AGENT — Live Spectrum Dashboard MVP
=============================================
Single-file dashboard that streams hackrf_sweep data to a web UI via websockets.

Usage:
    python dashboard.py              # Real HackRF hardware
    python dashboard.py --fake       # Simulated data (no HackRF needed)
    python dashboard.py --port 8080  # Custom port (default 8080)

Dependencies:  pip install websockets
"""

import argparse
import asyncio
import json
import random
import signal
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from io import BytesIO

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' package required.  Install with:  pip install websockets")
    sys.exit(1)

# ──────────────────────────────── Configuration ────────────────────────────────
DEFAULT_PORT = 8080
WS_PORT_OFFSET = 1  # websocket runs on port+1
SWEEP_CMD = r"C:\Program Files\PothosSDR\bin\hackrf_sweep.exe"
SWEEP_ARGS = ["-f", "300:500", "-l", "32", "-g", "20", "-w", "100000"]
PEAK_THRESHOLD_DB = 10  # dB above noise floor to count as peak

# ──────────────────────────────── HTML / JS / CSS ──────────────────────────────

def get_html(ws_port):
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RF RECON AGENT</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a0f;--panel:#10111a;--border:#1a1f2e;
  --green:#00ff88;--green-dim:#00ff8833;--cyan:#00e5ff;--red:#ff3355;
  --text:#c8d0e0;--text-dim:#5a6478;--mono:'JetBrains Mono','Fira Code','Courier New',monospace;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--mono);font-size:13px;overflow:hidden}
#app{display:grid;height:100vh;grid-template-rows:48px 1fr 160px;grid-template-columns:1fr 320px}
#topbar{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;padding:0 20px;
  background:linear-gradient(90deg,#0d0f18,#111425);border-bottom:1px solid var(--border)}
#topbar h1{font-size:15px;letter-spacing:3px;color:var(--green);text-shadow:0 0 12px var(--green-dim)}
#topbar .meta{display:flex;gap:24px;font-size:11px;color:var(--text-dim)}
#topbar .meta span.live{color:var(--red);animation:pulse 1.2s infinite}
#spectrum-panel{padding:12px 16px;position:relative;overflow:hidden}
#spectrum-panel canvas{width:100%!important;height:100%!important}
#sidebar{border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
#sidebar-header{padding:12px 16px;font-size:12px;letter-spacing:2px;color:var(--cyan);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between}
#targets{flex:1;overflow-y:auto;padding:8px 12px}
.target-card{background:#111420;border:1px solid var(--border);border-radius:6px;padding:10px 12px;margin-bottom:8px;transition:border-color .3s}
.target-card.active{border-color:var(--green)}
.target-card.stale{border-color:#333;opacity:.65}
.target-card .freq{font-size:14px;font-weight:700;color:var(--green)}
.target-card .details{font-size:10px;color:var(--text-dim);margin-top:4px;line-height:1.6}
.target-card .badge{display:inline-block;font-size:9px;padding:2px 6px;border-radius:3px;margin-left:6px;letter-spacing:1px}
.badge-active{background:#00ff8822;color:var(--green)}
.badge-stale{background:#ff335522;color:var(--red)}
#logpanel{grid-column:1/-1;border-top:1px solid var(--border);padding:8px 16px;overflow-y:auto;
  font-size:11px;line-height:1.7;background:#080810}
#logpanel .log-line{white-space:nowrap}
#logpanel .ts{color:var(--text-dim)}
#logpanel .scan{color:var(--cyan)}
#logpanel .peak{color:var(--red);font-weight:700}
#logpanel .ai{color:var(--green);font-weight:700}
#logpanel .ai-rec{color:orange;font-weight:700}
#ai-panel{padding:10px 12px;border-top:1px solid var(--border);overflow-y:auto;flex:1}
#ai-panel .ai-card{background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:10px 12px;margin-bottom:6px}
#ai-panel .ai-card.critical{border-color:#ff3355;background:#ff335510}
#ai-panel .ai-card.medium{border-color:orange;background:#ff990010}
#ai-panel .ai-card.low{border-color:var(--green);background:#00ff8810}
#ai-panel .ai-card .threat-badge{display:inline-block;font-size:9px;padding:2px 8px;border-radius:3px;font-weight:700;letter-spacing:1px}
#ai-panel .ai-card .threat-badge.critical{background:#ff335530;color:#ff3355}
#ai-panel .ai-card .threat-badge.medium{background:#ff990030;color:orange}
#ai-panel .ai-card .threat-badge.low{background:#00ff8830;color:var(--green)}
#ai-panel .ai-commentary{font-size:10px;color:var(--green);margin:8px 0;padding:8px;background:#00ff8808;border-left:2px solid var(--green);line-height:1.5}
#ai-panel .ai-rec{font-size:10px;color:orange;margin:4px 0;padding:8px;background:#ff990008;border-left:2px solid orange;line-height:1.5}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#1f2535;border-radius:4px}
</style>
</head>
<body>
<div id="app">
  <div id="topbar">
    <h1>▸ RF RECON AGENT</h1>
    <div class="meta">
      <span id="clock">00:00:00</span>
      <span>SWEEPS <span id="sweep-count">0</span></span>
      <span class="live">● LIVE</span>
    </div>
  </div>
  <div id="spectrum-panel"><canvas id="spectrumChart"></canvas></div>
  <div id="sidebar">
    <div id="sidebar-header">AI INTELLIGENCE <span id="target-count" style="color:var(--green)">0</span></div>
    <div id="ai-panel"><div style="color:var(--text-dim);font-size:10px;padding:12px">Waiting for RECON-1 AI analysis...</div></div>
    <div style="padding:8px 12px;font-size:10px;letter-spacing:2px;color:var(--cyan);border-top:1px solid var(--border)">DETECTED TARGETS</div>
    <div id="targets" style="max-height:160px;overflow-y:auto;padding:4px 12px"></div>
  </div>
  <div id="logpanel"></div>
</div>
<script>
let sweepCount=0;
const targets=new Map();
setInterval(()=>{document.getElementById('clock').textContent=new Date().toTimeString().split(' ')[0]},1000);

const ctx=document.getElementById('spectrumChart').getContext('2d');
const chart=new Chart(ctx,{
  type:'line',
  data:{labels:[],datasets:[
    {label:'Power (dB)',data:[],borderColor:'#00ff88',backgroundColor:'rgba(0,255,136,0.08)',borderWidth:1.5,pointRadius:0,fill:true,tension:0.2},
    {label:'Noise Floor',data:[],borderColor:'#ff3355',borderDash:[6,4],borderWidth:1,pointRadius:0,fill:false}
  ]},
  options:{
    responsive:true,maintainAspectRatio:false,animation:{duration:200},
    scales:{
      x:{title:{display:true,text:'Frequency (MHz)',color:'#5a6478',font:{family:"'JetBrains Mono',monospace",size:10}},
        ticks:{color:'#5a6478',font:{size:9},maxTicksLimit:20},grid:{color:'#141824'}},
      y:{title:{display:true,text:'Power (dB)',color:'#5a6478',font:{family:"'JetBrains Mono',monospace",size:10}},
        ticks:{color:'#5a6478',font:{size:9}},grid:{color:'#141824'},suggestedMin:-90,suggestedMax:-10}
    },
    plugins:{legend:{display:false},tooltip:{enabled:true,mode:'index',intersect:false}}
  }
});

const peakPlugin={
  id:'peakMarkers',
  afterDatasetsDraw(ci){
    const meta=ci.getDatasetMeta(0);
    if(!meta||!window.__peaks)return;
    const c=ci.ctx;
    window.__peaks.forEach(p=>{
      const label=p.freq_mhz.toFixed(2);
      const idx=ci.data.labels.indexOf(label);
      if(idx<0)return;
      const pt=meta.data[idx];
      if(!pt)return;
      c.save();c.beginPath();c.arc(pt.x,pt.y,5,0,Math.PI*2);
      c.fillStyle='#ff3355';c.shadowColor='#ff3355';c.shadowBlur=12;c.fill();c.restore();
      c.save();c.fillStyle='#ff3355';c.font='9px JetBrains Mono,monospace';c.textAlign='center';
      c.fillText(p.freq_mhz.toFixed(2)+' MHz',pt.x,pt.y-12);c.restore();
    });
  }
};
Chart.register(peakPlugin);

function addLog(msg,cls='scan'){
  const panel=document.getElementById('logpanel');
  const ts=new Date().toTimeString().split(' ')[0];
  const div=document.createElement('div');
  div.className='log-line';
  div.innerHTML=`<span class="ts">[${ts}]</span> <span class="${cls}">${msg}</span>`;
  panel.appendChild(div);panel.scrollTop=panel.scrollHeight;
  while(panel.children.length>200)panel.removeChild(panel.firstChild);
}

function renderTargets(){
  const container=document.getElementById('targets');
  container.innerHTML='';
  const now=Date.now();
  const sorted=[...targets.values()].sort((a,b)=>b.power_db-a.power_db);
  document.getElementById('target-count').textContent=sorted.length;
  sorted.forEach(t=>{
    const ago=((now-t.last_seen)/1000).toFixed(0);
    const card=document.createElement('div');
    card.className='target-card '+(t.active?'active':'stale');
    
    let threatHtml = '';
    if(t.threat_level) {
      const color = t.threat_level === 'CRITICAL' ? 'var(--red)' : (t.threat_level === 'MEDIUM' ? 'orange' : 'var(--green)');
      threatHtml = `<div style="margin-top:6px;padding-top:6px;border-top:1px dashed #333">
        <span style="color:${color};font-weight:bold;font-size:10px">THREAT: ${t.threat_level}</span>
        ${t.what_if ? `<div style="color:var(--text-dim);font-size:9px;margin-top:4px;font-style:italic">"${t.what_if}"</div>` : ''}
      </div>`;
    }

    card.innerHTML=`
      <span class="freq">${t.freq_mhz.toFixed(3)} MHz</span>
      <span class="badge ${t.active?'badge-active':'badge-stale'}">${t.active?'ACTIVE':'LAST SEEN '+ago+'s AGO'}</span>
      <div class="details">
        PWR ${t.power_db.toFixed(1)} dB &nbsp;|&nbsp; SNR ${t.snr_db.toFixed(1)} dB<br>
        First seen: ${new Date(t.first_seen).toLocaleTimeString()}
      </div>
      ${threatHtml}
    `;
    container.appendChild(card);
  });
}

function handleSweep(data){
  sweepCount++;
  document.getElementById('sweep-count').textContent=sweepCount;
  chart.data.labels=data.spectrum.map(s=>s.freq_mhz.toFixed(2));
  chart.data.datasets[0].data=data.spectrum.map(s=>s.power_db);
  chart.data.datasets[1].data=data.spectrum.map(()=>data.noise_floor_db);
  window.__peaks=data.peaks;
  chart.update('none');
  const now=Date.now();
  targets.forEach(t=>t.active=false);
  data.peaks.forEach(p=>{
    const key=p.freq_mhz.toFixed(1);
    if(targets.has(key)){const t=targets.get(key);t.power_db=p.power_db;t.snr_db=p.snr_db;t.last_seen=now;t.active=true;}
    else{targets.set(key,{freq_mhz:p.freq_mhz,power_db:p.power_db,snr_db:p.snr_db,first_seen:now,last_seen:now,active:true});
      addLog(`PEAK DETECTED AT ${p.freq_mhz.toFixed(3)} MHz  (${p.power_db.toFixed(1)} dB, SNR ${p.snr_db.toFixed(1)} dB)`,'peak');}
  });
  renderTargets();
  addLog(`SCANNING… sweep #${sweepCount}  |  noise floor ${data.noise_floor_db.toFixed(1)} dB  |  ${data.peaks.length} peak(s)`,'scan');
}

function sendCommand(cmd,params={}){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({command:cmd,...params}));}

function renderAIPanel(data){
  const panel=document.getElementById('ai-panel');
  let html='';
  const signals=data.signals||[];
  document.getElementById('target-count').textContent=signals.length;
  signals.forEach(s=>{
    const lvl=(s.threat_level||'LOW').toLowerCase();
    html+=`<div class="ai-card ${lvl}">
      <span style="font-size:13px;font-weight:700;color:var(--green)">${(s.freq_mhz||0).toFixed(3)} MHz</span>
      <span class="threat-badge ${lvl}">${(s.threat_level||'UNKNOWN').toUpperCase()}</span>
      <div style="font-size:10px;color:var(--text-dim);margin-top:4px">${s.device_type||'Unknown Device'}</div>
      <div style="font-size:10px;color:var(--text);margin-top:4px;line-height:1.4">${s.assessment||''}</div>
    </div>`;
  });
  if(data.commentary){
    html+=`<div class="ai-commentary">${data.commentary}</div>`;
  }
  if(data.recommendation){
    html+=`<div class="ai-rec">${data.recommendation}</div>`;
  }
  panel.innerHTML=html;
}

const WS_PORT=__WS_PORT__;
let ws;
function connect(){
  ws=new WebSocket(`ws://${location.hostname}:${WS_PORT}`);
  ws.onopen=()=>addLog('WEBSOCKET CONNECTED','scan');
  ws.onclose=()=>{addLog('WEBSOCKET DISCONNECTED — reconnecting…','peak');setTimeout(connect,2000);};
  ws.onerror=()=>{};
  ws.onmessage=(evt)=>{
    const d=JSON.parse(evt.data);
    if(d.type==='sweep') handleSweep(d);
    else if(d.type==='LOG') addLog(d.msg, d.msg.startsWith('RECON-1')?'ai':(d.msg.startsWith('RECOMMENDATION')?'ai-rec':'scan'));
    else if(d.type==='THREAT_ANALYSIS') renderAIPanel(d);
  };
}
addLog('RF RECON AGENT v1.0 — initialising…','scan');
connect();
</script>
</body>
</html>""".replace("__WS_PORT__", str(ws_port))


# ──────────────────────────────── Sweep Parsing ───────────────────────────────

def parse_sweep_line(line: str):
    parts = line.strip().split(",")
    if len(parts) < 7:
        return []
    try:
        hz_low = float(parts[2].strip())
        hz_bin_width = float(parts[4].strip())
        db_values = [float(v.strip()) for v in parts[6:] if v.strip()]
    except (ValueError, IndexError):
        return []
    result = []
    for i, db in enumerate(db_values):
        freq_hz = hz_low + i * hz_bin_width
        result.append((freq_hz / 1e6, db))
    return result


def compute_sweep(spectrum):
    if not spectrum:
        return -80.0, []
    powers = [p for _, p in spectrum]
    noise_floor = statistics.median(powers)
    peaks = []
    for freq, power in spectrum:
        snr = power - noise_floor
        if snr >= PEAK_THRESHOLD_DB:
            peaks.append({"freq_mhz": freq, "power_db": power, "snr_db": snr})
    return noise_floor, peaks


# ──────────────────────────────── Fake Data Generator ─────────────────────────

class FakeSweepGenerator:
    def __init__(self):
        self.tick = 0
        self.base_noise = -65.0
        self.signals = [
            {"freq": 433.92, "power_range": (-30, -20), "duty": 0.7},
            {"freq": 315.00, "power_range": (-40, -28), "duty": 0.4},
        ]

    def generate_sweep(self):
        self.tick += 1
        spectrum = []
        freq = 300.0
        while freq < 500.0:
            power = self.base_noise + random.gauss(0, 2.5)
            for sig in self.signals:
                dist = abs(freq - sig["freq"])
                if dist < 0.3:
                    if random.random() < sig["duty"]:
                        sig_power = random.uniform(*sig["power_range"])
                        attenuation = dist / 0.3 * 15
                        power = max(power, sig_power - attenuation)
            spectrum.append((round(freq, 2), round(power, 2)))
            freq += 0.1
        return spectrum


# ──────────────────────────────── HTTP Server (stdlib) ────────────────────────

class DashboardHTTPHandler(SimpleHTTPRequestHandler):
    """Serves the single HTML page for any request."""
    html_content = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.html_content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(self.html_content)

    def log_message(self, format, *args):
        pass  # silence access logs


def start_http_server(port, ws_port):
    html = get_html(ws_port)
    DashboardHTTPHandler.html_content = html.encode("utf-8")
    server = HTTPServer(("0.0.0.0", port), DashboardHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ──────────────────────────────── WebSocket Server ────────────────────────────

connected_clients: set = set()
running_flag = {"run": True}  # Global so ws_handler can pause/resume the sweep


async def do_native_capture(freq_hz):
    if not native_driver:
        return
    print(f"\n[>>>] INITIATING FOCUSED CAPTURE AT {freq_hz/1e6:.3f} MHz [<<<]\n")
    # This automatically pauses the current sweep
    native_driver.start_capture(freq_hz, duration_sec=2.0)
    # Wait in background thread so we don't block the asyncio loop
    await asyncio.to_thread(native_driver.wait_capture, 10.0)
    print(f"\n[>>>] CAPTURE COMPLETE. RESUMING SWEEP [<<<]\n")
    native_driver.resume_sweep((300, 500))

async def ws_handler(websocket):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                cmd = json.loads(message)
                ctype = cmd.get("type", "")
                if ctype in ("LOG", "THREAT_ANALYSIS"):
                    # Forward agent messages to all browser clients
                    await broadcast(cmd)
                elif ctype == "CMD":
                    action = cmd.get("action")
                    if action == "CAPTURE":
                        freq_hz = cmd.get("freq_hz")
                        asyncio.create_task(do_native_capture(freq_hz))
                else:
                    print(f"[WS] Received: {ctype}")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"[WS] Client disconnected: {e}")
    finally:
        connected_clients.discard(websocket)


async def broadcast(data: dict):
    if not connected_clients:
        return
    msg = json.dumps(data)
    stale = set()
    # Iterate over a copy to avoid "Set changed size during iteration"
    for ws in list(connected_clients):
        try:
            await ws.send(msg)
        except Exception:
            stale.add(ws)
    connected_clients.difference_update(stale)


# ──────────────────────────────── Sweep Loops ─────────────────────────────────

async def run_real_sweep(running_flag):
    sweep_count = 0
    while running_flag["run"]:
        cmd = [SWEEP_CMD] + SWEEP_ARGS
        print(f"[SWEEP] Starting: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        spectrum = []
        last_low = None

        while running_flag["run"]:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                # Check stderr if process died
                err_bytes = await proc.stderr.read()
                if err_bytes:
                    print(f"[SWEEP] ERR: {err_bytes.decode('utf-8', errors='replace')}")
                print("[SWEEP] Process exited, restarting in 1 second...")
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            points = parse_sweep_line(line)
            if not points:
                continue
            current_low = points[0][0]
            if last_low is not None and current_low < last_low - 10:
                if spectrum:
                    sweep_count += 1
                    await _process_sweep(spectrum, sweep_count, False)
                spectrum = []
            spectrum.extend(points)
            last_low = current_low

        if spectrum:
            sweep_count += 1
            await _process_sweep(spectrum, sweep_count, False)
        
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
                
        if running_flag["run"]:
            await asyncio.sleep(1.0)


async def run_fake_sweep(running_flag):
    gen = FakeSweepGenerator()
    sweep_count = 0
    while running_flag["run"]:
        spectrum = gen.generate_sweep()
        sweep_count += 1
        await _process_sweep(spectrum, sweep_count, True)
        await asyncio.sleep(0.8)


async def _process_sweep(spectrum, sweep_count, is_fake):
    noise_floor, peaks = compute_sweep(spectrum)
    payload = {
        "type": "sweep",
        "spectrum": [{"freq_mhz": f, "power_db": p} for f, p in spectrum],
        "peaks": peaks,
        "noise_floor_db": noise_floor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sweep_number": sweep_count,
    }
    await broadcast(payload)
    peak_str = ", ".join(f"{p['freq_mhz']:.2f} MHz" for p in peaks)
    mode = "FAKE" if is_fake else "LIVE"
    print(f"[{mode}] Sweep #{sweep_count}  NF={noise_floor:.1f} dB  Peaks: {peak_str or 'none'}")


# ──────────────────────────────── Native pyhackrf2 Sweep ──────────────────────

native_driver = None

async def run_native_sweep(running_flag):
    """Use pyhackrf2 native Python driver instead of hackrf_sweep subprocess."""
    global native_driver
    try:
        from hackrf_driver import RFDriver
    except ImportError:
        print("[SWEEP] hackrf_driver.py not found, falling back to subprocess sweep")
        await run_real_sweep(running_flag)
        return

    try:
        native_driver = RFDriver()
    except Exception as e:
        print(f"[SWEEP] Failed to init native driver: {e}, falling back to subprocess")
        await run_real_sweep(running_flag)
        return

    native_driver.start_sweep((300, 500))
    sweep_count = 0
    
    while running_flag["run"]:
        await asyncio.sleep(0.3)  # Poll interval
        data = native_driver.get_sweep_data()
        if data:
            sweep_count += 1
            await _process_sweep(data, sweep_count, False)
    
    native_driver.stop_current()


# ──────────────────────────────── Main ────────────────────────────────────────

async def main_async(http_port, ws_port, fake, native=False):
    # Start HTTP server in a thread
    http_server = start_http_server(http_port, ws_port)
    mode_str = 'SIMULATED (--fake)' if fake else ('NATIVE PYHACKRF2' if native else 'LIVE HACKRF (subprocess)')
    print(f"\n{'='*60}")
    print(f"  RF RECON AGENT — Dashboard v1.0")
    print(f"  Mode:  {mode_str}")
    print(f"  Web:   http://localhost:{http_port}")
    print(f"  WS:    ws://localhost:{ws_port}")
    print(f"{'='*60}\n")

    running_flag["run"] = True  # Reset on (re)start

    # Run websocket server — keep it alive permanently (NOT awaiting the sweep directly!)
    async with websockets.serve(ws_handler, "0.0.0.0", ws_port):
        if fake:
            asyncio.create_task(run_fake_sweep(running_flag))
        elif native:
            asyncio.create_task(run_native_sweep(running_flag))
        else:
            asyncio.create_task(run_real_sweep(running_flag))
        
        # Keep the server alive indefinitely — never await the sweep directly!
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description="RF Recon Agent — Live Spectrum Dashboard")
    parser.add_argument("--fake", action="store_true", help="Simulated sweep data (no HackRF needed)")
    parser.add_argument("--native", action="store_true", help="Use pyhackrf2 native driver (no subprocess)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port (default {DEFAULT_PORT})")
    args = parser.parse_args()

    ws_port = args.port + WS_PORT_OFFSET

    try:
        asyncio.run(main_async(args.port, ws_port, args.fake, args.native))
    except KeyboardInterrupt:
        print("\n[EXIT] Dashboard stopped.")


if __name__ == "__main__":
    main()

