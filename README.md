# RECON-1: Autonomous RF Threat Assessment Agent

RECON-1 is an agentic spectrum surveillance system designed for the HackRF One. It uses `pyhackrf2` for native hardware control and an LLM-driven decision engine to identify and investigate suspicious RF activity.

## Core Features
- **Native Hardware Driver**: High-speed sweeping and focused IQ capture using `pyhackrf2`.
- **Temporal Novelty Detection**: Tracks signals over time to distinguish between persistent background noise and transient "bursts" (e.g., key fobs, garage door openers).
- **Agentic Decision Making**: LLM-based analysis of RF events with autonomous "Focus" recommendations.
- **Real-time Dashboard**: WebSocket-based visualization of the spectrum, detected peaks, and agent commentary.

## Setup

### 1. Prerequisites
- HackRF One SDR
- Python 3.8+
- [PothosSDR](https://github.com/pothosware/PothosSDR/wiki/Tutorial) (for `hackrf.dll` on Windows)

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
OPENROUTER_KEY=your_api_key_here
```

### 3. Install Dependencies
```bash
pip install pyhackrf2 websockets requests python-dotenv numpy
```

## Usage

### Start the Dashboard
```bash
python dashboard.py --native
```
The dashboard will be available at `http://localhost:8888`.

### Start the Brain (Agent)
```bash
python agent.py
```
RECON-1 will connect to the dashboard and start monitoring the 300-500 MHz range.

## Project Structure
- `agent.py`: The LLM decision engine and signal tracking logic.
- `dashboard.py`: WebSocket server and spectrum visualization frontend.
- `hackrf_driver.py`: Native `pyhackrf2` wrapper for sweep/capture/replay.
- `start_dashboard.bat`: Quick-start batch file.
