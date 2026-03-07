import asyncio
import os
import json
from tools import record_signal, replay_signal
from signal_analysis import analyze_iq_file

SWEEP_CMD = r"C:\Program Files\PothosSDR\bin\hackrf_sweep.exe"

async def scan_band_for_peaks(start_mhz, end_mhz, duration_sec):
    print(f"\n[MISSION] Scanning {start_mhz}-{end_mhz} MHz for {duration_sec} seconds...")
    cmd = [
        SWEEP_CMD, 
        "-f", f"{start_mhz}:{end_mhz}", 
        "-l", "32", "-g", "20", "-w", "100000"
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    end_time = asyncio.get_event_loop().time() + duration_sec
    all_powers = []
    spectrum_accumulator = {}
    
    while asyncio.get_event_loop().time() < end_time:
        try:
            line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
                
            parts = line.split(", ")
            if len(parts) >= 6:
                hz_low = int(parts[2])
                hz_bin_width = float(parts[4])
                powers = [float(x) for x in parts[6:]]
                
                freq = hz_low
                for p in powers:
                    all_powers.append(p)
                    f_mhz = round((freq + (hz_bin_width/2)) / 1e6, 2)
                    if f_mhz not in spectrum_accumulator:
                        spectrum_accumulator[f_mhz] = p
                    else:
                        spectrum_accumulator[f_mhz] = max(spectrum_accumulator[f_mhz], p)
                    freq += hz_bin_width
        except asyncio.TimeoutError:
            pass

    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except:
        try:
            proc.kill()
        except:
            pass
            
    if not all_powers:
        return []
        
    sorted_powers = sorted(all_powers)
    noise_floor = sum(sorted_powers[:len(sorted_powers)//2]) / (len(sorted_powers)//2) if len(sorted_powers) > 0 else -60
    
    peaks = []
    for freq_mhz, power in spectrum_accumulator.items():
        if power > noise_floor + 15: # 15dB SNR threshold
            peaks.append((freq_mhz, power))
            
    peaks.sort(key=lambda x: x[1], reverse=True)
    
    # filter out duplicate hits right next to each other
    final_peaks = []
    for p in peaks:
        if not any(abs(p[0] - f) < 1.0 for f in final_peaks):
            final_peaks.append(p[0])
            if len(final_peaks) >= 5:
                break
                
    return final_peaks

async def execute_mission():
    print("==================================================")
    print("     AUTONOMOUS RF RECON MISSION INITIATED")
    print("==================================================")
    
    targets = []
    report = []
    
    # Phase 1: Scan bands
    targets.extend(await scan_band_for_peaks(860, 870, 60))
    targets.extend(await scan_band_for_peaks(430, 440, 60))
    
    if not targets:
        print("\n[MISSION] No distinct targets found in the specified bands.")
        return
        
    print(f"\n[MISSION] Discovered {len(targets)} distinct frequency targets. Commencing deep capture...")
    
    # Phase 2: Capture and Analyze
    for freq_mhz in targets:
        freq_hz = int(freq_mhz * 1e6)
        filename = f"capture_{freq_hz}_hz.iq"
        
        # Capture 5 seconds of raw baseband
        await record_signal(freq_hz, duration_sec=5, filename=filename)
        
        # Analyze the baseband
        analysis = analyze_iq_file(filename)
        
        if analysis.get("detected"):
            report.append({
                "freq_mhz": freq_mhz,
                "modulation": analysis["modulation"],
                "burst_count": analysis["burst_count"],
                "snr": analysis["snr_db"],
                "replayable": analysis["replayable"]
            })
            
            # Auto-cleanup non-replayable noise grabs to save space
            if not analysis["replayable"]:
                 os.remove(filename)

    # Phase 3: Print Actionable Summary
    print("\n==================================================")
    print("               MISSION SUMMARY REPORT")
    print("==================================================")
    if not report:
        print("No valid, structured transmissions detected during capture phase.")
    else:
        print(f"{'FREQ (MHz)':<12} | {'MODULATION':<12} | {'BURSTS':<8} | {'SNR (dB)':<10} | {'REPLAYABLE?'}")
        print("-" * 65)
        for r in report:
            rep_str = "YES (OOK Target)" if r["replayable"] else "No"
            print(f"{r['freq_mhz']:<12.2f} | {r['modulation']:<12} | {r['burst_count']:<8} | {r['snr']:<10.1f} | {rep_str}")
            
    print("\n[MISSION] Complete. Replayable targets are saved as .iq files in this directory.")
    print("Use tools.py replay_signal() on the corresponding file to transmit.")

if __name__ == "__main__":
    asyncio.run(execute_mission())
