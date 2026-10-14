@echo off
title Car Visits Tracker - Traffic Benchmark Daemon
echo =====================================================================
echo 🚗 CAR VISITS TRACKER - TRAFFIC BENCHMARK DAEMON (10:00 AM - 12:00 PM)
echo =====================================================================
echo.
echo Starting benchmark daemon in background...
"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\venv\Scripts\python.exe" backend\traffic_benchmark.py
pause
