@echo off
title RF Recon Dashboard
echo ===================================================
echo Starting RF Recon Agent Dashboard (Native pyhackrf2)
echo Make sure your HackRF is plugged in and in HackRF mode!
echo ===================================================
echo.
start "RF Dashboard" cmd /k "python -u dashboard.py --port 8888"
ping 127.0.0.1 -n 3 > nul
start "RF AI Brain" cmd /k "python -u agent.py --port 8888"
ping 127.0.0.1 -n 3 > nul
start http://localhost:8888
echo Dashboard, Agent, and Browser are running...
exit
