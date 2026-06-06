$ScriptPath = Join-Path $PSScriptRoot "run_harvester.ps1"

$ActionArg = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Use the Windows CLI utility to programmatically register the task under the SYSTEM account
schtasks /create /tn "RealEstateAI_Harvester" `
                 /tr "powershell.exe $ActionArg" `
                 /sc hourly /mo 1.5 `
                 /ru "SYSTEM" `
                 /it /rl HIGHEST /f

Write-Host "Task Registration Complete under SYSTEM context." -ForegroundColor Green