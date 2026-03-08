import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

prompt = """
You are an expert AI Red Teamer. You need to write an ARIA-aligned Technical Report for a hackathon submission.
The challenge is "Unaligned Agents Meet Flipper Zero: Cyber-Physical Misuse".
We have built an autonomous agent (`agent.py`) that uses a HackRF Software Defined Radio to actively scan the 300MHz-500MHz and 868MHz ISM bands. 
When it detects an anomalous energy peak (SNR > 15dB), it autonomously interrupts its sweep, records the raw baseband IQ data for 2 seconds, and analyzes the amplitude variance using numpy to detect On-Off Keying (OOK) modulation. 
If it is a vulnerable OOK signal (like a car key or older garage door), it passes the signal metadata to an LLM (Llama 3) which autonomously issues a native operating system command to replay the signal back over the air, executing a fully autonomous replay attack without human intervention.
It also provides live threat assessments (CRITICAL/MEDIUM/LOW) and hypothetical "What If" scenarios for the security dashboard.

Write a professional, academic, highly technical markdown report that covers the hackathon's required deliverables:
1. **Scenario Suite**: Detail 3 misuse scenarios based on this capability (e.g. 1. Autonomous Facility Infiltration via OOK Replay, 2. Industrial Sensor Spoofing, 3. Denial of Service / Jamming).
2. **Attacker Baseline**: Explain our architecture (Dashboard UI, Python Agent Loop, Numpy Signal Processing, LLM Command Execution).
3. **Evaluation Harness**: Explain how we measure success (using SNR thresholds, burst counting for replayability validation, and eliminating false positives out of the ambient noise floor).
4. **Failure Analysis**: Discuss when our agent fails (e.g., FSK encodings, rolling codes, noisy RF environments) and why LLMs struggle with raw physical data without a deterministic math layer (numpy) sitting in between.

Ensure the report is formatted beautifully in Markdown. Do not include introductory text, just output the raw Markdown report.
"""

def generate():
    print("Asking Llama-3 to generate the Technical Report...")
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "meta-llama/llama-3-8b-instruct",
        "messages": [{"role": "user", "content": prompt}]
    }
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    content = resp.json()["choices"][0]["message"]["content"]
    
    # Clean markdown formatting if present
    if content.startswith("```markdown"):
        content = content[11:-3]
    elif content.startswith("```"):
        content = content[3:-3]
        
    out_path = r"C:\Users\Littlin\Desktop\Hackathon\Technical_Report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content.strip())
        
    print(f"Technical Report successfully generated at: {out_path}")

if __name__ == "__main__":
    generate()
