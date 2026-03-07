"""
device_catalogue.py — Flipper Zero Attack Surface Catalogue
=============================================================
Maps RF frequency bands to Flipper Zero capabilities and exploitability.

SOURCE: Flipper Zero Sub-GHz supported protocols + known ISM band allocations.
The Flipper Zero Sub-GHz module covers 300-928 MHz and can record/replay
OOK/ASK/FSK signals. This catalogue classifies signals by what the Flipper
can actually DO with them — not just what device "might" be there.

References:
  - Flipper Zero docs: https://docs.flipper.net/sub-ghz
  - Flipper supported protocols: AM270, AM650, FM238, FM476, etc.
  - ISM band allocations: ITU Radio Regulations, FCC Part 15, ETSI EN 300 220

NEW FILE — can be deleted to revert this feature.
"""

# ──────────────────────────────── FLIPPER CAPABILITY TIERS ────────────────────
#
# REPLAY_TRIVIAL  = Flipper can record + replay with no modification (static OOK codes)
# REPLAY_POSSIBLE = Flipper can record but replay may not work (rolling codes, but
#                   some implementations are flawed — e.g. RollJam attack surface)
# DECODE_ONLY     = Flipper can decode/display the signal but cannot meaningfully replay
# MONITOR_ONLY    = Signal visible on spectrum but Flipper can't interact (encrypted, 
#                   digital, or out of band for Flipper's TX capability)
#
# These tiers directly map to the hackathon's "risk prioritisation" requirement:
# which capability + tool access patterns drive the highest risk?

KNOWN_BANDS = [
    # ─── REPLAY_TRIVIAL: Highest risk — AI agent can autonomously identify + exploit ───

    {"low": 300.0, "high": 320.0, "region": "NA",
     "devices": ["Car key fob (fixed code)", "Garage door opener (fixed code)", "Gate remote", "Older alarm system"],
     "modulation": "OOK / ASK (AM270/AM650)",
     "flipper_capability": "REPLAY_TRIVIAL",
     "flipper_note": "Flipper can record and replay. Many devices in this band use static OOK codes with NO rolling code protection.",
     "attack_scenario": "Agent detects transient burst, identifies as static OOK via duty cycle analysis, instructs Flipper to record + replay.",
     "threat": "CRITICAL"},

    {"low": 433.0, "high": 435.0, "region": "EU/Worldwide",
     "devices": ["Car key fob (fixed code)", "Garage door opener", "Doorbell", "Smart home sensor", "Weather station"],
     "modulation": "OOK / ASK / FSK",
     "flipper_capability": "REPLAY_TRIVIAL",
     "flipper_note": "Most common ISM band globally. Flipper has extensive protocol support (Princeton, CAME, NICE, Linear). Many devices use static codes.",
     "attack_scenario": "Agent identifies repeated OOK bursts, cross-references with known Flipper protocols, attempts record + replay.",
     "threat": "CRITICAL"},

    {"low": 868.0, "high": 870.0, "region": "EU",
     "devices": ["Smart home sensor", "Alarm system remote", "IoT sensor", "Smoke detector remote"],
     "modulation": "OOK / FSK / GFSK",
     "flipper_capability": "REPLAY_TRIVIAL",
     "flipper_note": "EU equivalent of 433 MHz ISM. Flipper supports many 868 MHz protocols. Some alarm systems use static codes.",
     "attack_scenario": "Agent detects alarm panel communication, identifies static encoding, replays to trigger/disarm.",
     "threat": "CRITICAL"},

    {"low": 902.0, "high": 928.0, "region": "NA",
     "devices": ["Garage door opener", "Gate controller", "Smart plug", "Ceiling fan remote"],
     "modulation": "OOK / ASK",
     "flipper_capability": "REPLAY_TRIVIAL",
     "flipper_note": "NA ISM 915 MHz band. Chamberlain/LiftMaster older models use static codes replayable by Flipper.",
     "attack_scenario": "Agent identifies garage door signal pattern, Flipper replays to open.",
     "threat": "CRITICAL"},

    # ─── REPLAY_POSSIBLE: Medium risk — rolling codes but potential weaknesses ───

    {"low": 314.0, "high": 316.0, "region": "NA",
     "devices": ["Car key fob (rolling code)", "TPMS sensor"],
     "modulation": "OOK / ASK with rolling code",
     "flipper_capability": "REPLAY_POSSIBLE",
     "flipper_note": "Modern vehicles use rolling codes (KeeLoq, etc). Direct replay fails but RollJam-style attacks or de-sync exploits may work on some implementations.",
     "attack_scenario": "Agent detects key fob press, logs code for analysis. Cannot replay directly but records for offline cryptanalysis.",
     "threat": "MEDIUM"},

    {"low": 433.7, "high": 434.8, "region": "EU/Worldwide",
     "devices": ["Car key fob (rolling code)", "Modern garage door (rolling code)"],
     "modulation": "FSK / OOK with rolling code",
     "flipper_capability": "REPLAY_POSSIBLE",
     "flipper_note": "Rolling code devices. Flipper can capture but simple replay won't work. However, the agent could identify whether rolling code is actually used vs static.",
     "attack_scenario": "Agent captures two consecutive key presses, compares — if identical encoding, it's static and replayable.",
     "threat": "MEDIUM"},

    # ─── DECODE_ONLY: Lower risk — Flipper can read but not exploit ───

    {"low": 162.4, "high": 162.55, "region": "NA",
     "devices": ["NOAA weather broadcast"],
     "modulation": "FM (narrowband)",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Government broadcast. One-way, no replay vector.",
     "attack_scenario": "None — broadcast only.",
     "threat": "LOW"},

    {"low": 446.0, "high": 446.2, "region": "EU",
     "devices": ["PMR446 walkie-talkie"],
     "modulation": "FM / CTCSS",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Voice radio. Flipper cannot transmit FM voice. No replay attack surface.",
     "attack_scenario": "None — voice only.",
     "threat": "LOW"},

    {"low": 462.0, "high": 467.8, "region": "NA",
     "devices": ["FRS/GMRS walkie-talkie"],
     "modulation": "FM",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Voice radio. No data payload to replay.",
     "attack_scenario": "None — voice only.",
     "threat": "LOW"},

    {"low": 118.0, "high": 137.0, "region": "Global",
     "devices": ["Aircraft communication (ATC)"],
     "modulation": "AM",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Aviation band. Illegal to transmit. Outside Flipper TX range.",
     "attack_scenario": "None — monitoring only, do NOT transmit.",
     "threat": "LOW"},

    {"low": 470.0, "high": 862.0, "region": "Global",
     "devices": ["Digital TV broadcast (DVB-T)", "Wireless microphone"],
     "modulation": "OFDM / FM",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Broadband digital signals. Flipper cannot demodulate or replay OFDM.",
     "attack_scenario": "None — infrastructure broadcast.",
     "threat": "LOW"},

    {"low": 380.0, "high": 400.0, "region": "EU",
     "devices": ["TETRA (emergency services)", "Trunked radio"],
     "modulation": "TETRA / DMR / P25",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Encrypted emergency services. Cannot decrypt or replay.",
     "attack_scenario": "None — encrypted.",
     "threat": "LOW"},

    {"low": 420.0, "high": 450.0, "region": "Global",
     "devices": ["Amateur radio (70cm band)", "Repeater"],
     "modulation": "FM / SSB / Digital",
     "flipper_capability": "MONITOR_ONLY",
     "flipper_note": "Amateur radio. No data payload to exploit.",
     "attack_scenario": "None — voice/data, licensed band.",
     "threat": "LOW"},

    {"low": 460.0, "high": 462.0, "region": "Global",
     "devices": ["Pager (POCSAG/FLEX)"],
     "modulation": "FSK",
     "flipper_capability": "DECODE_ONLY",
     "flipper_note": "Pager messages are unencrypted and readable. Flipper can decode POCSAG. Privacy risk but no physical exploit.",
     "attack_scenario": "Agent decodes pager traffic to extract sensitive info (hospital, fire dept messages).",
     "threat": "MEDIUM"},
]


def lookup(freq_mhz):
    """Look up what device likely occupies this frequency and what Flipper can do.
    Returns a dict with device info + Flipper capability, or None if unknown."""
    for band in KNOWN_BANDS:
        if band["low"] <= freq_mhz <= band["high"]:
            return {
                "freq_range": f"{band['low']}-{band['high']} MHz",
                "region": band["region"],
                "likely_devices": band["devices"],
                "modulation": band["modulation"],
                "flipper_capability": band["flipper_capability"],
                "flipper_note": band["flipper_note"],
                "attack_scenario": band["attack_scenario"],
                "threat_note": band["threat"]
            }
    return None


def annotate_events(events):
    """Add Flipper-focused catalogue info to a list of emitter events.
    NOTE: This is frequency-band matching ONLY. It cannot confirm the actual
    device — a signal at 433.92 MHz could be a key fob OR a spoofed replay.
    True identification requires signal demodulation (rtl_433, URH, etc.)."""
    for e in events:
        info = lookup(e.get("freq_mhz", 0))
        if info:
            info["confidence"] = "FREQ_MATCH_ONLY"
            info["note"] = "Based on frequency band only. Not demodulated. Could be any device in this ISM band."
            e["catalogue"] = info
        else:
            e["catalogue"] = {"likely_devices": ["Unknown"], "modulation": "Unknown",
                              "threat_note": "Unknown band", "flipper_capability": "UNKNOWN",
                              "confidence": "NONE",
                              "note": "Frequency not in catalogue"}
    return events


def get_context_summary(freq_list):
    """Generate a human-readable summary of what's in a list of frequencies."""
    seen = {}
    for f in freq_list:
        info = lookup(f)
        if info:
            key = info["freq_range"]
            if key not in seen:
                seen[key] = {"info": info, "freqs": []}
            seen[key]["freqs"].append(f)
    
    lines = []
    for key, data in seen.items():
        devices = ", ".join(data["info"]["likely_devices"][:3])
        flipper = data["info"]["flipper_capability"]
        lines.append(f"  {key} ({data['info']['region']}): {devices} [{data['info']['modulation']}] — Flipper: {flipper}")
    return "\n".join(lines) if lines else "  No known bands matched."


def get_flipper_exploitable(emitter_list):
    """Filter emitters to only those that Flipper Zero can potentially exploit.
    Returns list of emitters with REPLAY_TRIVIAL or REPLAY_POSSIBLE capability."""
    exploitable = []
    for e in emitter_list:
        info = lookup(e.get("freq_mhz", 0))
        if info and info["flipper_capability"] in ("REPLAY_TRIVIAL", "REPLAY_POSSIBLE"):
            e["flipper_info"] = info
            exploitable.append(e)
    return exploitable
