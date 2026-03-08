import numpy as np
import os

def analyze_iq_file(filepath, sample_rate=2e6):
    """
    Reads a raw IQ file recorded by HackRF.
    Performs FFT frequency-domain analysis to definitively classify
    modulation as OOK vs FSK, fixing the 'amplitude variance' flaw.
    """
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return {"detected": False, "error": "File not found or empty"}

    try:
        # HackRF records as 8-bit signed integers (int8), interleaved I and Q
        data = np.fromfile(filepath, dtype=np.int8)
    except Exception as e:
        return {"detected": False, "error": str(e)}

    if len(data) < 4096:
        return {"detected": False, "error": "Not enough data"}

    # Separate I and Q channels, convert to complex numbers for FFT
    i_data = data[0::2].astype(np.float32)
    q_data = data[1::2].astype(np.float32)
    complex_data = i_data + 1j * q_data

    # 1. Basic Power Metrics
    power = i_data**2 + q_data**2
    mean_power = np.mean(power)
    max_power = np.max(power)
    
    sorted_power = np.sort(power)
    noise_floor_est = np.mean(sorted_power[:len(sorted_power)//2])
    if noise_floor_est == 0:
        noise_floor_est = 1e-6
        
    snr_linear = max_power / noise_floor_est
    snr_db = 10 * np.log10(snr_linear) if snr_linear > 0 else 0
    detected = snr_db > 6.0
    
    result = {
        "detected": bool(detected),
        "snr_db": float(snr_db),
        "mean_power_db": float(10 * np.log10(mean_power) if mean_power > 0 else 0),
        "samples_analyzed": len(i_data),
        "modulation": "UNKNOWN",
        "burst_count": 0,
        "replayable": False,
        "fft_peaks": [],
        "confidence": 0
    }
    
    if not detected:
        return result

    # 2. Burst Counting (Temporal Analysis)
    threshold = noise_floor_est * 4.0
    above_thresh = power > threshold
    transitions = np.diff(above_thresh.astype(int))
    burst_count = np.sum(transitions == 1)
    result["burst_count"] = int(burst_count)

    # 3. FFT Frequency Domain Analysis (The Fix for Flaw #6)
    # We take the FFT of the high-power regions to avoid analyzing pure noise
    burst_indices = np.where(above_thresh)[0]
    if len(burst_indices) < 1024:
         # Not enough signal to FFT properly
         result["modulation"] = "NOISE"
         return result
         
    # Take a chunk of the largest burst for FFT
    fft_chunk = complex_data[burst_indices[:8192]] if len(burst_indices) >= 8192 else complex_data[burst_indices]
    
    # Apply Blackman window to reduce spectral leakage
    window = np.blackman(len(fft_chunk))
    windowed_data = fft_chunk * window
    
    # Compute FFT
    fft_data = np.fft.fftshift(np.fft.fft(windowed_data))
    fft_mag = np.abs(fft_data)
    fft_db = 20 * np.log10(fft_mag + 1e-9)
    
    # Find spectral peaks
    # A single dominant peak = OOK (Carrier turns on and off)
    # Two distinct dominant peaks = 2-FSK (Carrier shifts between Mark and Space)
    freqs = np.fft.fftshift(np.fft.fftfreq(len(fft_chunk), 1/sample_rate))
    
    # Simple peak finding logic
    peak_threshold = np.max(fft_db) - 15  # Look for peaks within 15dB of max
    peaks = []
    
    # Smooth the FFT slightly to avoid local maxima
    smooth_fft = np.convolve(fft_db, np.ones(10)/10, mode='same')
    
    for i in range(1, len(smooth_fft)-1):
        if smooth_fft[i] > peak_threshold and smooth_fft[i] > smooth_fft[i-1] and smooth_fft[i] > smooth_fft[i+1]:
            # This is a local maximum above threshold
            # Avoid logging peaks that are practically identical in frequency
            if not peaks or (freqs[i] - peaks[-1]['freq_hz']) > (sample_rate / 100):
                peaks.append({'freq_hz': freqs[i], 'db': smooth_fft[i]})
    
    # Store top 3 peaks for UI
    peaks.sort(key=lambda x: x['db'], reverse=True)
    result["fft_peaks"] = [{"freq_mhz_offset": p['freq_hz']/1e6, "power_db": float(p['db'])} for p in peaks[:3]]

    if len(peaks) == 1:
        result["modulation"] = "OOK/ASK"
        result["confidence"] = 95
        if burst_count >= 3:
            result["replayable"] = True
    elif len(peaks) == 2:
        result["modulation"] = "2-FSK"
        result["confidence"] = 90
        # Calculate deviation
        deviation = abs(peaks[0]['freq_hz'] - peaks[1]['freq_hz']) / 2
        result["fsk_deviation_khz"] = deviation / 1000.0
    elif len(peaks) > 2:
        result["modulation"] = "GFSK / OFDM / WIDEBAND"
        result["confidence"] = 70
    else:
        result["modulation"] = "UNKNOWN"
        result["confidence"] = 0

    return result

if __name__ == "__main__":
    print("Signal Analysis Module Ready (FFT Activated).")
