# Control The Lifelong Quiz on the cloud server from this PC.
#
#   .\scripts\quiz-server.ps1 status
#   .\scripts\quiz-server.ps1 start | stop | restart
#   .\scripts\quiz-server.ps1 logs            (live log, Ctrl+C to leave)
#   .\scripts\quiz-server.ps1 key             (paste the YouTube stream key, hidden)
#   .\scripts\quiz-server.ps1 schedule "18:00 01:00" 3h
#   .\scripts\quiz-server.ps1 set QUIZ_STREAM_HEIGHT 1080
#   .\scripts\quiz-server.ps1 shell           (open a terminal on the server)
#
# Server address and SSH key come from the repo's .env (QUIZ_SERVER, QUIZ_SSH_KEY).
# Full guide: deploy/linux/SERVER.md

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$settings = @{}
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $settings[$Matches[1]] = $Matches[2].Trim() }
    }
}
$server = if ($env:QUIZ_SERVER) { $env:QUIZ_SERVER } else { $settings["QUIZ_SERVER"] }
$sshKey = if ($env:QUIZ_SSH_KEY) { $env:QUIZ_SSH_KEY } else { $settings["QUIZ_SSH_KEY"] }
if (-not $server -or -not $sshKey) {
    Write-Error "Set QUIZ_SERVER and QUIZ_SSH_KEY in $envFile"
}

if ($args.Count -eq 0) { $cmd = @("help") } else { $cmd = $args }

if ($cmd[0] -eq "shell") {
    ssh -i $sshKey "root@$server"
    exit $LASTEXITCODE
}

# Quote every argument for the remote shell, so "18:00 01:00" stays one argument.
$quoted = ($cmd | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join " "
# -t gives a real terminal: needed for the hidden key prompt and the live log.
ssh -t -i $sshKey "root@$server" "quizctl $quoted"
exit $LASTEXITCODE
