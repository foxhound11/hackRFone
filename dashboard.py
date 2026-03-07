#!/usr/bin/env python3
"""
RF RECON AGENT — Live Spectrum Dashboard v2.0
==============================================
Single-file dashboard that streams hackrf_sweep data to a web UI via websockets.

CHANGES FROM ORIGINAL:
- Complete UI overhaul: 4-panel grid layout
- Agent status bar (SCANNING/FOCUSING/LEARNING)
- Emitter database table (from SQLite)
- Alert flash overlay for critical threats
- New WebSocket message types: EMITTER_TABLE, AGENT_STATUS, TIMELINE_DATA, ALERT

Usage:
    python dashboard.py              # Real HackRF hardware
    python dashboard.py --fake       # Simulated data (no HackRF needed)
    python dashboard.py --native     # Use pyhackrf2 driver
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
    return (r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RF RECON AGENT</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#06070d;--panel:#0c0d16;--panel2:#10111c;--border:#1a1f2e;--border2:#252b3d;
  --green:#00ff88;--green-dim:#00ff8833;--cyan:#00e5ff;--red:#ff3355;--amber:#ffaa00;
  --text:#c8d0e0;--text-dim:#5a6478;--mono:'JetBrains Mono',monospace;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--mono);font-size:12px;overflow:hidden}
#app{display:grid;height:100vh;
  grid-template-rows:44px 1fr 200px 140px;
  grid-template-columns:1fr 340px;
  grid-template-areas:"topbar topbar" "spectrum sidebar" "emitters sidebar" "logpanel logpanel";
}
#topbar{grid-area:topbar;display:flex;align-items:center;justify-content:space-between;padding:0 16px;
  background:linear-gradient(90deg,#0a0c18,#0f1125);border-bottom:1px solid var(--border)}
#topbar h1{font-size:14px;letter-spacing:3px;color:var(--green);text-shadow:0 0 20px var(--green-dim)}
#topbar .meta{display:flex;gap:18px;font-size:10px;color:var(--text-dim);align-items:center}
#topbar .meta span.live{color:var(--red);animation:pulse 1.2s infinite}
#agent-mode{padding:3px 10px;border-radius:3px;font-size:9px;letter-spacing:1.5px;font-weight:700}
#agent-mode.scanning{background:#00ff8815;color:var(--green);border:1px solid #00ff8840}
#agent-mode.focusing{background:#ff335515;color:var(--red);border:1px solid #ff335540;animation:pulse 0.8s infinite}
#agent-mode.analyzing{background:#ffaa0015;color:var(--amber);border:1px solid #ffaa0040}
#agent-mode.learning{background:#00e5ff15;color:var(--cyan);border:1px solid #00e5ff40;animation:pulse 1.5s infinite}
#spectrum-panel{grid-area:spectrum;padding:10px 14px;position:relative;overflow:hidden;background:var(--panel)}
#spectrum-panel canvas{width:100%!important;height:100%!important}
#sidebar{grid-area:sidebar;border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;background:var(--panel)}
#sidebar-header{padding:10px 14px;font-size:11px;letter-spacing:2px;color:var(--cyan);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;background:var(--panel2)}
#ai-panel{flex:1;overflow-y:auto;padding:8px 10px}
#ai-panel .ai-card{background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-bottom:6px;transition:all 0.3s ease}
#ai-panel .ai-card:hover{border-color:var(--border2);transform:translateX(2px)}
#ai-panel .ai-card.critical{border-color:#ff3355;background:#ff335508}
#ai-panel .ai-card.medium{border-color:var(--amber);background:#ffaa0008}
#ai-panel .ai-card.low{border-color:var(--green);background:#00ff8808}
.threat-badge{display:inline-block;font-size:8px;padding:2px 7px;border-radius:3px;font-weight:700;letter-spacing:1px}
.threat-badge.critical{background:#ff335525;color:#ff3355}
.threat-badge.medium{background:#ffaa0025;color:var(--amber)}
.threat-badge.low{background:#00ff8825;color:var(--green)}
#ai-panel .ai-commentary{font-size:10px;color:var(--green);margin:6px 0;padding:6px 8px;background:#00ff8806;
  border-left:2px solid var(--green);line-height:1.5;border-radius:0 4px 4px 0}
#ai-panel .ai-rec{font-size:10px;color:var(--amber);margin:4px 0;padding:6px 8px;background:#ffaa0006;
  border-left:2px solid var(--amber);line-height:1.5;border-radius:0 4px 4px 0}
#emitter-panel{grid-area:emitters;border-top:1px solid var(--border);overflow:hidden;display:flex;flex-direction:column;background:var(--panel2)}
#emitter-header{padding:8px 14px;font-size:10px;letter-spacing:2px;color:var(--cyan);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between}
#emitter-table-wrap{flex:1;overflow-y:auto}
#emitter-table{width:100%;border-collapse:collapse;font-size:10px}
#emitter-table th{position:sticky;top:0;background:var(--panel2);color:var(--text-dim);text-align:left;
  padding:5px 8px;border-bottom:1px solid var(--border);font-weight:400;letter-spacing:1px;font-size:9px}
#emitter-table td{padding:4px 8px;border-bottom:1px solid #0f1018}
#emitter-table tr:hover{background:#ffffff05}
#emitter-table .baseline{opacity:0.45}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:5px}
.dot-green{background:var(--green);box-shadow:0 0 6px var(--green)}
.dot-red{background:var(--red);box-shadow:0 0 6px var(--red)}
.dot-amber{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.dot-dim{background:#444}
#logpanel{grid-area:logpanel;border-top:1px solid var(--border);padding:6px 14px;overflow-y:auto;
  font-size:10px;line-height:1.6;background:#060710}
#logpanel .log-line{white-space:nowrap}
#logpanel .ts{color:var(--text-dim)}
#logpanel .scan{color:var(--cyan)}
#logpanel .peak{color:var(--red);font-weight:700}
#logpanel .ai{color:var(--green);font-weight:700}
#logpanel .ai-rec{color:var(--amber);font-weight:700}
#logpanel .alert{color:#ff3355;font-weight:700;animation:flash 0.5s 3}
#alert-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;z-index:999;pointer-events:none;
  background:radial-gradient(ellipse at center, #ff335520 0%, transparent 70%);animation:flash 0.5s 3}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes flash{0%,100%{opacity:0}50%{opacity:1}}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#1f2535;border-radius:4px}
</style>
</head>
<body>
<div id="alert-overlay"></div>
<div id="app">
  <div id="topbar">
    <h1>&#9654; RECON-1</h1>
    <div class="meta">
      <span id="agent-mode" class="scanning">SCANNING</span>
      <span id="agent-detail" style="color:var(--text-dim);font-size:9px"></span>
      <span id="clock">00:00:00</span>
      <span>SWEEPS <span id="sweep-count">0</span></span>
      <span>DB <span id="db-count" style="color:var(--green)">0</span></span>
      <span class="live">&#9679; LIVE</span>
    </div>
  </div>
  <div id="spectrum-panel"><canvas id="spectrumChart"></canvas></div>
  <div id="sidebar">
    <div id="sidebar-header">AI INTELLIGENCE <span id="target-count" style="color:var(--green)">0</span></div>
    <div id="ai-panel"><div style="color:var(--text-dim);font-size:10px;padding:12px">Waiting for RECON-1 analysis...</div></div>
  </div>
  <div id="emitter-panel">
    <div id="emitter-header">EMITTER DATABASE <span id="emitter-stats" style="color:var(--text-dim);font-size:9px">0 total / 0 baseline</span></div>
    <div id="emitter-table-wrap">
      <table id="emitter-table">
        <thead><tr><th></th><th>FREQ</th><th>LABEL</th><th>HITS</th><th>SNR</th><th>THREAT</th><th>LAST SEEN</th></tr></thead>
        <tbody id="emitter-tbody"></tbody>
      </table>
    </div>
  </div>
  <div id="logpanel"></div>
</div>
<script>
var sweepCount=0;
setInterval(function(){document.getElementById('clock').textContent=new Date().toTimeString().split(' ')[0]},1000);

var ctx=document.getElementById('spectrumChart').getContext('2d');
var chart=new Chart(ctx,{
  type:'line',
  data:{labels:[],datasets:[
    {label:'Power (dB)',data:[],borderColor:'#00ff88',backgroundColor:'rgba(0,255,136,0.05)',borderWidth:1.2,pointRadius:0,fill:true,tension:0.2},
    {label:'Noise Floor',data:[],borderColor:'#ff335566',borderDash:[6,4],borderWidth:1,pointRadius:0,fill:false}
  ]},
  options:{
    responsive:true,maintainAspectRatio:false,animation:{duration:150},
    scales:{
      x:{title:{display:true,text:'Frequency (MHz)',color:'#5a6478',font:{family:"'JetBrains Mono',monospace",size:9}},
        ticks:{color:'#3a4458',font:{size:8},maxTicksLimit:25},grid:{color:'#0f1420'}},
      y:{title:{display:true,text:'Power (dB)',color:'#5a6478',font:{family:"'JetBrains Mono',monospace",size:9}},
        ticks:{color:'#3a4458',font:{size:8}},grid:{color:'#0f1420'},suggestedMin:-90,suggestedMax:-10}
    },
    plugins:{legend:{display:false},tooltip:{enabled:true,mode:'index',intersect:false,
      backgroundColor:'#0c0d16ee',borderColor:'#1a1f2e',borderWidth:1,titleFont:{size:10},bodyFont:{size:9}}}
  }
});
var peakPlugin={
  id:'peakMarkers',
  afterDatasetsDraw:function(ci){
    var meta=ci.getDatasetMeta(0);
    if(!meta||!window.__peaks)return;
    var c=ci.ctx;
    window.__peaks.forEach(function(p){
      var label=p.freq_mhz.toFixed(2);
      var idx=ci.data.labels.indexOf(label);
      if(idx<0)return;
      var pt=meta.data[idx];
      if(!pt)return;
      c.save();c.beginPath();c.arc(pt.x,pt.y,4,0,Math.PI*2);
      c.fillStyle='#ff3355';c.shadowColor='#ff3355';c.shadowBlur=10;c.fill();c.restore();
      c.save();c.fillStyle='#ff3355';c.font='bold 8px JetBrains Mono,monospace';c.textAlign='center';
      c.fillText(p.freq_mhz.toFixed(1)+' MHz',pt.x,pt.y-10);c.restore();
    });
  }
};
Chart.register(peakPlugin);

function addLog(msg,cls){
  cls=cls||'scan';
  var panel=document.getElementById('logpanel');
  var ts=new Date().toTimeString().split(' ')[0];
  var div=document.createElement('div');
  div.className='log-line';
  div.innerHTML='<span class="ts">['+ts+']<\/span> <span class="'+cls+'">'+msg+'<\/span>';
  panel.appendChild(div);panel.scrollTop=panel.scrollHeight;
  while(panel.children.length>150)panel.removeChild(panel.firstChild);
}

function handleSweep(data){
  sweepCount++;
  document.getElementById('sweep-count').textContent=sweepCount;
  chart.data.labels=data.spectrum.map(function(s){return s.freq_mhz.toFixed(2)});
  chart.data.datasets[0].data=data.spectrum.map(function(s){return s.power_db});
  chart.data.datasets[1].data=data.spectrum.map(function(){return data.noise_floor_db});
  window.__peaks=data.peaks;
  chart.update('none');
}

function renderAIPanel(data){
  var panel=document.getElementById('ai-panel');
  var html='';
  var signals=data.signals||[];
  document.getElementById('target-count').textContent=signals.length;
  for(var i=0;i<signals.length;i++){
    var s=signals[i];
    var lvl=(s.threat_level||s.threat||'LOW').toLowerCase();
    html+='<div class="ai-card '+lvl+'">';
    html+='<span style="font-size:12px;font-weight:700;color:var(--green)">'+(s.freq_mhz||0).toFixed(3)+' MHz<\/span> ';
    html+='<span class="threat-badge '+lvl+'">'+(s.threat_level||s.threat||'?').toUpperCase()+'<\/span>';
    html+='<div style="font-size:9px;color:var(--text-dim);margin-top:3px">'+(s.device_type||s.device||'Unknown')+'<\/div>';
    html+='<div style="font-size:9px;color:var(--text);margin-top:3px;line-height:1.4">'+(s.assessment||'')+'<\/div>';
    html+='<\/div>';
  }
  if(data.commentary) html+='<div class="ai-commentary">'+data.commentary+'<\/div>';
  if(data.recommendation) html+='<div class="ai-rec">'+data.recommendation+'<\/div>';
  panel.innerHTML=html;
}

function renderEmitterTable(data){
  var tbody=document.getElementById('emitter-tbody');
  document.getElementById('emitter-stats').textContent=data.total+' total / '+data.baseline_count+' baseline';
  document.getElementById('db-count').textContent=data.total;
  var html='';
  var emitters=(data.emitters||[]).slice(0,50);
  for(var i=0;i<emitters.length;i++){
    var e=emitters[i];
    var isBase=e.is_baseline?'baseline':'';
    var threat=(e.threat_level||'').toLowerCase();
    var dotClass=threat==='critical'?'dot-red':(threat==='medium'?'dot-amber':(e.is_baseline?'dot-dim':'dot-green'));
    var label=e.agent_label||e.user_label||'';
    var lastSeen=e.last_seen?new Date(e.last_seen).toLocaleTimeString():'';
    html+='<tr class="'+isBase+'"><td><span class="dot '+dotClass+'"><\/span><\/td>';
    html+='<td style="color:var(--green);font-weight:700">'+e.freq_mhz.toFixed(1)+'<\/td>';
    html+='<td>'+label+'<\/td><td>'+e.total_hits+'<\/td><td>'+e.max_snr.toFixed(1)+'<\/td>';
    html+='<td><span class="threat-badge '+threat+'">'+(e.threat_level||'').toUpperCase()+'<\/span><\/td>';
    html+='<td style="color:var(--text-dim)">'+lastSeen+'<\/td><\/tr>';
  }
  tbody.innerHTML=html;
}

function handleAgentStatus(data){
  var el=document.getElementById('agent-mode');
  var detail=document.getElementById('agent-detail');
  var mode=(data.mode||'SCANNING').toUpperCase();
  el.textContent=mode;
  el.className=mode.toLowerCase();
  detail.textContent=data.detail||'';
}

function handleAlert(data){
  addLog('ALERT: '+data.message,'alert');
  var overlay=document.getElementById('alert-overlay');
  overlay.style.display='block';
  setTimeout(function(){overlay.style.display='none'},1500);
}

var WS_PORT=__WS_PORT__;
var ws;
function connect(){
  ws=new WebSocket('ws://'+location.hostname+':'+WS_PORT);
  ws.onopen=function(){addLog('WEBSOCKET CONNECTED','scan')};
  ws.onclose=function(){addLog('DISCONNECTED','peak');setTimeout(connect,2000)};
  ws.onerror=function(){};
  ws.onmessage=function(evt){
    var d=JSON.parse(evt.data);
    if(d.type==='sweep') handleSweep(d);
    else if(d.type==='LOG') addLog(d.msg, d.msg.indexOf('RECON-1')>=0?'ai':(d.msg.indexOf('ACTION')>=0?'ai-rec':'scan'));
    else if(d.type==='THREAT_ANALYSIS') renderAIPanel(d);
    else if(d.type==='EMITTER_TABLE') renderEmitterTable(d);
    else if(d.type==='AGENT_STATUS') handleAgentStatus(d);
    else if(d.type==='ALERT') handleAlert(d);
  };
}
addLog('RECON-1 v2.0','scan');
connect();
</script>
</body>
</html>""").replace("__WS_PORT__", str(ws_port))


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
                if ctype in ("LOG", "THREAT_ANALYSIS", "EMITTER_TABLE", "AGENT_STATUS", "TIMELINE_DATA", "ALERT"):
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
    print(f"  RF RECON AGENT — Dashboard v2.0")
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
