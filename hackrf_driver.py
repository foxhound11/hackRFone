"""
hackrf_driver.py — Native Python HackRF driver using pyhackrf2.
Replaces subprocess calls to hackrf_sweep.exe and hackrf_transfer.exe.
Supports three modes: SWEEP, CAPTURE, REPLAY.
"""
import numpy as np
import threading
import time
from collections import deque

# Try to import pyhackrf2 — fall back gracefully
try:
    from pyhackrf2 import HackRF
    PYHACKRF_AVAILABLE = True
except Exception as e:
    print(f"[DRIVER] pyhackrf2 not available: {e}")
    PYHACKRF_AVAILABLE = False


class RFDriver:
    """Unified HackRF controller: sweep, capture, and replay through one device."""

    def __init__(self):
        if not PYHACKRF_AVAILABLE:
            raise RuntimeError("pyhackrf2 not available")
        
        self.hackrf = HackRF()
        self.mode = "IDLE"          # IDLE | SWEEP | CAPTURE | REPLAY
        self._sweep_queue = deque(maxlen=50)  # Thread-safe sweep results
        self._capture_buffer = None
        self._capture_done = threading.Event()
        self._sweep_lock = threading.Lock()
        self._stop_sweep = False
        
        # Default gains (match current hackrf_sweep settings)
        self.hackrf.lna_gain = 32
        self.hackrf.vga_gain = 20
        print(f"[DRIVER] HackRF initialized. Serial: {self.hackrf.get_serial_no()}")

    def start_sweep(self, freq_range_mhz=(300, 500)):
        """Start continuous frequency sweep. Results go into _sweep_queue."""
        if self.mode != "IDLE":
            self.stop_current()
        
        self.mode = "SWEEP"
        self._stop_sweep = False
        self.hackrf.sample_rate = 20e6
        
        # Accumulate partial sweeps into a complete pass
        self._current_sweep = []
        self._last_freq = 0.0
        
        def on_sweep(data):
            """Called from C thread with {freq_hz_tuple: bytes} dict per block."""
            if self._stop_sweep:
                return True  # Stop sweep
            
            try:
                for freq_tuple, raw_bytes in data.items():
                    freq_hz = freq_tuple[0] if isinstance(freq_tuple, tuple) else freq_tuple
                    freq_mhz = freq_hz / 1e6
                    
                    # Detect new sweep pass: frequency dropped significantly
                    if freq_mhz < self._last_freq - 10 and len(self._current_sweep) > 50:
                        # Complete sweep — sort and queue it
                        sweep_copy = sorted(self._current_sweep, key=lambda x: x[0])
                        self._sweep_queue.append(sweep_copy)
                        self._current_sweep = []
                    
                    self._last_freq = freq_mhz
                    
                    # In sweep mode, HackRF returns uint8 power bins directly, NOT raw IQ samples!
                    # The values are already log amplitudes (0-255).
                    bins = np.frombuffer(bytes(raw_bytes), dtype=np.uint8).astype(np.float64)
                    if len(bins) == 0:
                        continue
                    
                    # Take the mean power of the bins for this frequency step
                    mean_bin_val = np.mean(bins)
                    
                    # Hackrf_sweep roughly maps these uint8 values to dBm using a scale and offset
                    # A typical empirical mapping is: (val * 0.5) - 100 roughly matches hackrf_sweep dBm
                    # Adjusting offset until it matches the -60 to -20 dBm range the dashboard expects
                    power_db = (mean_bin_val * 0.5) - 100.0
                    
                    self._current_sweep.append((freq_mhz, power_db))
            except Exception as e:
                print(f"[DRIVER] Sweep callback error: {e}")
            
            return False  # Keep sweeping
        
        print(f"[DRIVER] Starting sweep: {freq_range_mhz[0]}-{freq_range_mhz[1]} MHz")
        try:
            self.hackrf.start_sweep(
                [freq_range_mhz],
                pipe_function=on_sweep,
                step_width=100000,  # 100kHz steps (match current config)
            )
        except Exception as e:
            print(f"[DRIVER] Sweep start error: {e}")
            self.mode = "IDLE"

    def get_sweep_data(self):
        """Get the latest sweep result from the queue. Returns list of (freq_mhz, power_db) or None."""
        if self._sweep_queue:
            return self._sweep_queue.pop()
        return None

    def start_capture(self, freq_hz, duration_sec=2.0, sample_rate=2e6):
        """Stop sweep, tune to freq, capture IQ for duration_sec."""
        self.stop_current()
        time.sleep(0.5)  # Let hardware settle
        
        self.mode = "CAPTURE"
        self._capture_done.clear()
        
        self.hackrf.sample_rate = int(sample_rate)
        self.hackrf.center_freq = int(freq_hz)
        self.hackrf.lna_gain = 32
        self.hackrf.vga_gain = 20
        
        self.hackrf.start_rx()
        
        def _stop_after():
            time.sleep(duration_sec)
            try:
                self.hackrf.stop_rx()
            except Exception:
                pass
            self._capture_buffer = bytes(self.hackrf.buffer)
            self.mode = "CAPTURED"
            self._capture_done.set()
            print(f"[DRIVER] Capture complete: {len(self._capture_buffer)} bytes")
        
        threading.Thread(target=_stop_after, daemon=True).start()
        print(f"[DRIVER] Capturing at {freq_hz/1e6:.3f} MHz for {duration_sec}s...")

    def wait_capture(self, timeout=10):
        """Block until capture is done."""
        return self._capture_done.wait(timeout=timeout)

    def get_capture_buffer(self):
        """Return the captured IQ bytes."""
        return self._capture_buffer

    def start_replay(self, freq_hz=None):
        """Replay captured buffer. Optionally set a different TX frequency."""
        if not self.hackrf.buffer:
            print("[DRIVER] No data in buffer to replay")
            return False
        
        self.stop_current()
        time.sleep(0.5)
        
        self.mode = "REPLAY"
        if freq_hz:
            self.hackrf.center_freq = int(freq_hz)
        self.hackrf.txvga_gain = 47
        self.hackrf.start_tx()
        print(f"[DRIVER] Replaying {len(self.hackrf.buffer)} bytes...")
        return True

    def stop_replay(self):
        """Stop transmitting."""
        try:
            self.hackrf.stop_tx()
        except Exception:
            pass
        self.mode = "IDLE"

    def stop_current(self):
        """Stop whatever mode is currently active."""
        self._stop_sweep = True
        try:
            if self.mode == "SWEEP":
                self.hackrf.stop_rx()
            elif self.mode == "CAPTURE":
                self.hackrf.stop_rx()
            elif self.mode == "REPLAY":
                self.hackrf.stop_tx()
        except Exception:
            pass
        self.mode = "IDLE"
        time.sleep(0.3)

    def resume_sweep(self, freq_range_mhz=(300, 500)):
        """Convenience: stop current mode and restart sweep."""
        self.stop_current()
        self.start_sweep(freq_range_mhz)


# Quick test
if __name__ == "__main__":
    driver = RFDriver()
    driver.start_sweep((300, 500))
    
    for i in range(10):
        time.sleep(1)
        data = driver.get_sweep_data()
        if data:
            print(f"Got {len(data)} frequency points. Range: {data[0][0]:.1f} - {data[-1][0]:.1f} MHz")
        else:
            print("No data yet...")
    
    driver.stop_current()
    print("Done.")
