@echo off
title RF Recon Dashboard
echo ===================================================
echo Starting RF Recon Agent Dashboard (Native pyhackrf2)
echo Make sure your HackRF is plugged in and in HackRF mode!
echo ===================================================
echo.
start "RF Dashboard" cmd /k "python -u dashboard.py --port 8888 --native"
ping 127.0.0.1 -n 3 > nul
start "RF AI Brain" cmd /k "python -u agent.py"
echo Dashboard and Agent are running...
exit
