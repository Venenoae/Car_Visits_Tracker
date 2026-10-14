Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host " Syncing updated edge_tracker.py to Raspberry Pi (192.168.0.240)..." -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

scp -o StrictHostKeyChecking=accept-new "$PSScriptRoot\edge_tracker.py" admin@192.168.0.240:/home/admin/visits_tracker/edge/edge_tracker.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[INFO] Restarting gate-tracker service on Raspberry Pi..." -ForegroundColor Green
    ssh -o StrictHostKeyChecking=accept-new admin@192.168.0.240 "sudo systemctl restart gate-tracker.service && sudo systemctl status gate-tracker.service --no-pager"
    Write-Host "`n=====================================================================" -ForegroundColor Green
    Write-Host " Deployment complete! Gate tracker is active on the Raspberry Pi." -ForegroundColor Green
    Write-Host "=====================================================================" -ForegroundColor Green
} else {
    Write-Host "`n[ERROR] SCP transfer failed. Please check Raspberry Pi connection and credentials." -ForegroundColor Red
}
