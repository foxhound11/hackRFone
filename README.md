# RECON-1: Autonomous RF Threat Assessment Agent

RECON-1 is an advanced, AI-augmented spectrum surveillance system designed for the HackRF One. It combines high-speed RF sweeping, Digital Signal Processing (DSP), offline protocol decoding, and Large Language Model (LLM) reasoning to autonomously identify, analyze, and assess suspicious radio frequency activity in real-time.

---

## 🚀 Key Capabilities

- **High-Speed Spectrum Sweeping**: Utilizes `hackrf_sweep` to rapidly scan the RF environment and identify transient anomalies.
- **Triple-Verified Intelligence**:
  1. **Persistent Memory (`emitter_db.py`)**: A local SQLite database learns the "baseline" of your RF environment to filter out normal background noise and flag novel emitters.
  2. **DSP Engine (`signal_analysis.py`)**: Automatically captures High-Res IQ data to calculate SNR, detect modulation schemes (FSK/OOK), and count burst intervals.
  3. **Digital Decoding (`rtl_433`)**: Offline analysis of captured IQ files to extract known civilian and industrial protocols (e.g., TPMS, weather stations, car fobs).
- **Agentic Assessment (`agent.py`)**: Packages the DSP metrics and digital decodes into a structured context window and sends it to an LLM (via OpenRouter) to determine the intent and threat level of the signal.
- **Live C2 Dashboard (`dashboard.py`)**: A non-blocking, responsive web interface featuring a live waterfall/spectrum graph, a Threat Ledger, and a dedicated "Raw LLM Trace" tab for complete transparency.

---

## 🛠️ System Architecture

- **`agent.py`** (The Brain): The core loop that orchestrates novelty detection, auto-captures (IQ recording), protocol decoding, and LLM API calls.
- **`dashboard.py`** (The Command Center): Serves the web UI and acts as a WebSocket broadcaster, ensuring the live graph stays buttery smooth even when the agent is performing heavy analysis.
- **`start_dashboard.bat`**: The launch sequence that synchronizes ports and opens the web view.

---

## ⚙️ Setup & Requirements

### 1. Hardware & Software Prerequisites
- **HackRF One** SDR
- **Windows OS** (optimized for Windows paths)
- **Python 3.8+**
- **[PothosSDR](https://github.com/pothosware/PothosSDR/wiki/Tutorial)** (Must be installed and in your PATH for `hackrf_sweep.exe`)
- **[rtl_433](https://github.com/merbanan/rtl_433)** (Compiled Windows binary placed in the project root)

### 2. Python Dependencies
```bash
pip install websockets requests python-dotenv numpy scipy
```

### 3. API Configuration
Create a `.env` file in the root directory:
```env
OPENROUTER_KEY=your_api_key_here
```

---

## 🎯 Usage (Demo Mode)

RECON-1 is currently tuned for a high-speed live demonstration, specifically monitoring the `420-450 MHz` band.

Simply double-click:
`start_dashboard.bat`

This will:
1. Launch the HTTP Server for the Dashboard.
2. Launch the AI Agent.
3. Automatically open `http://localhost:8888` in your default browser.
4. Begin tracking signals and streaming data to the UI.

To demonstrate a "Threat Capture", transmit a signal in the 433 MHz ISM band (e.g., using a Flipper Zero). RECON-1 will isolate the signal, capture 2 seconds of IQ data, decode it, and pass it to the LLM to generate a real-time Threat Card.
