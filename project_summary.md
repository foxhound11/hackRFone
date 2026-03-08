# RECON-1: Autonomous RF Threat Assessment Agent
## Comprehensive Project Summary & Feature Catalog

### 1. Executive Technical Summary
RECON-1 is a closed-loop, autonomous Radio Frequency (RF) threat intelligence system designed to detect, classify, and weaponize wireless vulnerabilities in the physical environment. Operating primarily in the 300-500 MHz ISM bands, the system utilizes a HackRF Software Defined Radio (SDR) to continuously sweep the spectrum. It employs a rolling-baseline novelty detection algorithm to filter out constant background noise and isolate anomalous transient bursts (e.g., human-actuated key fob presses). 

When an anomaly is detected, the agent queries a local device catalogue to probabilistically map the frequency to known device types and hardware capabilities (specifically assessing Flipper Zero exploitability). This context is fed into a Large Language Model (LLM) that acts as the tactical decision engine. If the LLM deems the signal a critical threat, it commands the SDR to halt sweeping and focus on the target frequency. During this "Focus" phase, RECON-1 captures the raw Baseband IQ data and routes it through dual-diagnostic pipelines: `rtl_433` for deterministic protocol decoding and data payload extraction, and a custom Fast Fourier Transform (FFT) analysis module to mathematically prove the analog modulation scheme (OOK vs. FSK). The entire multi-layered analysis is streamed in real-time to a local WebSocket-powered dashboard, providing operators with actionable cyber-physical intelligence without requiring deep RF expertise.

---

### 2. Feature Implementation History (The "Last Hour" Additions)

We iteratively transformed the system from a noisy, reactive scanner into an intelligent, analytical offensive agent. Here is the exact breakdown of what was added and why:

#### The 7 Core Enhancement Strategies
1. **Persistent Emitter Database (`emitter_db.py`)**: 
   * *What it is:* A SQLite database replacing volatile RAM storage.
   * *Why:* So the agent remembers devices across restarts and can track long-term patterns (e.g., "I saw this gate opener yesterday at 5 PM").
2. **Device Catalogue with Flipper Mapping (`device_catalogue.py`)**:
   * *What it is:* A lookup table mapping frequencies (e.g., 433.92 MHz) to likely devices and explicitly grading them by Flipper Zero capabilities (`REPLAY_TRIVIAL`, `REPLAY_POSSIBLE`, `DECODE_ONLY`).
   * *Why:* To fulfill Hackathon Challenge 3 requirements and give the LLM concrete hardware limits to base its threat assessments on.
3. **Novelty Detection (Baseline Subtraction)**:
   * *What it is:* Logic in `agent.py`'s `EmitterMemory` that ignores frequencies that are always broadcasting.
   * *Why:* To stop the LLM from spamming API calls about boring, continuous TV/telemetry signals, focusing only on *new* or *bursty* events.
4. **Learn Mode (`--learn` flag)**:
   * *What it is:* A startup flag that makes the agent sit quietly for 30 sweeps, learning the environment's background noise, and marking all current signals as "safe".
   * *Why:* Because taking this to a noisy hackathon venue would immediately overwhelm the naive peak detector.
5. **Rolling LLM Context**:
   * *What it is:* Passing the last 3 LLM thoughts back into the prompt.
   * *Why:* So the AI has memory and doesn't repeat the exact same analysis every 5 seconds.
6. **Desktop Notifications (CTypes)**:
   * *What it is:* Triggering standard Windows alert sounds/popups.
   * *Why:* So the operator doesn't need to stare at the dashboard continuously.
7. **Complete UX/UI Overhaul (`dashboard.py`)**:
   * *What it is:* Moving from a raw text log to a 4-panel grid with a live spectrum chart, an AI threat card sidebar, a searchable Emitter Table, and Agent Status states.
   * *Why:* To make the agent's complex multi-step reasoning visually impressive and understandable to a hackathon judge.

#### The "Deep Physics" Upgrades
8. **Deterministic Protocol Decoding (`rtl_433_integration.py`)**:
   * *What it is:* A subprocess wrapper for the industry-standard `rtl_433` tool.
   * *Why:* Frequency matching is a guess (e.g., "315 MHz might be a car"). `rtl_433` actually reads the data payload and provides Ground Truth (e.g., "This is specifically a Honda Key Fob, ID: 45A2"). It stops the AI from hallucinating.
9. **FFT Frequency Domain Analysis (`signal_analysis.py`)**:
   * *What it is:* Replacing naive loudness tracking (amplitude variance) with Fast Fourier Transforms to look for multiple distinct radio carrier spikes.
   * *Why:* Loudness tracking fails if someone walks in front of the antenna. FFT mathematically proves if a signal is On-Off Keying (OOK) or Frequency Shift Keying (FSK), which dictates if a Flipper Zero can replay it trivially.
