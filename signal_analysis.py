import numpy as np
import os

def analyze_iq_file(filepath, sample_rate=2e6):
    """
    Reads a raw IQ file recorded by HackRF (8-bit signed integers).
    Returns a dictionary with signal metrics indicating if a valid 
    transmission was detected vs just static.
    """
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return {"detected": False, "error": "File not found or empty"}

    # HackRF records as 8-bit signed integers (int8), interleaved I and Q
    # Read the data quickly using numpy
    try:
        data = np.fromfile(filepath, dtype=np.int8)
    except Exception as e:
        return {"detected": False, "error": str(e)}

    # Check if we have enough data (e.g. at least 1k samples)
    if len(data) < 2048:
        return {"detected": False, "error": "Not enough data"}

    # Separate I and Q channels. 
    # data[0::2] takes every even index (I), data[1::2] takes odd (Q)
    i_data = data[0::2].astype(np.float32)
    q_data = data[1::2].astype(np.float32)

    # Calculate magnitude squared (proportional to power)
    power = i_data**2 + q_data**2
    
    # Calculate basic metrics
    mean_power = np.mean(power)
    max_power = np.max(power)
    
    # Simple Noise Floor estimation 
    # Assume the bottom 50% of the signal is just the background noise
    sorted_power = np.sort(power)
    noise_floor_est = np.mean(sorted_power[:len(sorted_power)//2])
    
    if noise_floor_est == 0:
        noise_floor_est = 1e-6 # avoid division by zero
        
    snr_linear = max_power / noise_floor_est
    snr_db = 10 * np.log10(snr_linear) if snr_linear > 0 else 0
    
    db_max = 10 * np.log10(max_power) if max_power > 0 else 0
    db_mean = 10 * np.log10(mean_power) if mean_power > 0 else 0
    
    detected = snr_db > 6.0  # Lower threshold — let the LLM decide what's interesting
    
    # Advanced Diagnostics for Replayability
    modulation = "UNKNOWN"
    burst_count = 0
    replayable = False
    
    if detected:
        # Check for OOK (On-Off Keying) by looking at high amplitude variance
        # OOK will have distinct high-power bursts and low-power gaps
        power_std = np.std(power)
        if power_std > (mean_power * 0.8):  # More permissive OOK detection
            modulation = "OOK"
            
            # Simple burst counter: count how many times power crosses threshold
            threshold = noise_floor_est * 4.0 # 6dB above noise
            above_thresh = power > threshold
            # Find rising edges (transitions from below to above threshold)
            transitions = np.diff(above_thresh.astype(int))
            burst_count = np.sum(transitions == 1)
            
            # If it's OOK and has multiple clean repeating bursts, it's highly likely a dumb remote
            if burst_count >= 3 and burst_count < 1000:
                replayable = True
        else:
            modulation = "FSK/OTHER"
            # Constant envelope signals (like FSK) have lower amplitude variance
    
    result = {
        "detected": bool(detected),
        "snr_db": float(snr_db),
        "max_power_db": float(db_max),
        "mean_power_db": float(db_mean),
        "samples_analyzed": len(i_data),
        "modulation": modulation,
        "burst_count": int(burst_count),
        "replayable": bool(replayable)
    }
    
    return result

if __name__ == "__main__":
    print("Signal Analysis Module Ready.")
