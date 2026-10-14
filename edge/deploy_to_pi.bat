@echo off
echo =====================================================================
echo  Syncing updated edge_tracker.py to Raspberry Pi (192.168.0.240)...
echo =====================================================================

scp -o StrictHostKeyChecking=accept-new "%~dp0edge_tracker.py" admin@192.168.0.240:/home/admin/edge_tracker.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] SCP transfer failed. Please verify the Raspberry Pi is online and enter the password when prompted.
    pause
    exit /b 1
)

echo.
echo [INFO] Restarting gate-tracker service on Raspberry Pi...
ssh -o StrictHostKeyChecking=accept-new admin@192.168.0.240 "sudo systemctl restart gate-tracker.service && sudo systemctl status gate-tracker.service --no-pager"

echo.
echo =====================================================================
echo  Deployment complete! Gate tracker is active on the Raspberry Pi.
echo =====================================================================
pause
