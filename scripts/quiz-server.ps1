# Control The Lifelong Quiz on the cloud server from this PC.
#
#   .\scripts\quiz-server.ps1 status
#   .\scripts\quiz-server.ps1 start | stop | restart
#   .\scripts\quiz-server.ps1 logs            (live log, Ctrl+C to leave)
#   .\scripts\quiz-server.ps1 key             (paste the YouTube stream key, hidden)
#   .\scripts\quiz-server.ps1 schedule "13:00 18:00 01:00" 3h
#   .\scripts\quiz-server.ps1 set QUIZ_STREAM_HEIGHT 1080
#   .\scripts\quiz-server.ps1 shell           (open a terminal on the server)
#   .\scripts\quiz-server.ps1 youtube-client <downloaded client JSON>   (sent over ssh stdin)
#   .\scripts\quiz-server.ps1 youtube-auth    (shows a URL and a code to approve)
#   .\scripts\quiz-server.ps1 youtube-login <Desktop app client JSON>   (browser sign-in, picks a brand channel)
#   .\scripts\quiz-server.ps1 youtube-status
#   Setup: docs/youtube-api.md
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

# Windows SSH ignores a key file that other accounts may read, then falls back to a password
# prompt (there is no password). Keep the key readable by this user only.
if (Test-Path $sshKey) {
    icacls $sshKey /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
} else {
    Write-Error "SSH key not found: $sshKey"
}

if ($cmd[0] -eq "key" -and $cmd.Count -gt 1) {
    Write-Host "Type only: .\scripts\quiz-server.ps1 key"
    Write-Host "Then paste the stream key when it asks. Do not put the key on the command line."
    exit 1
}

if ($cmd[0] -eq "youtube-client") {
    if ($cmd.Count -ne 2 -or -not (Test-Path -LiteralPath $cmd[1] -PathType Leaf)) {
        Write-Host "Usage: .\scripts\quiz-server.ps1 youtube-client <path to the downloaded client JSON>"
        exit 1
    }
    # The file goes over ssh's stdin byte for byte, never on a command line.
    $file = (Resolve-Path -LiteralPath $cmd[1]).Path
    $p = Start-Process -FilePath "ssh" -NoNewWindow -Wait -PassThru -RedirectStandardInput $file `
        -ArgumentList @("-i", "`"$sshKey`"", "root@$server", "quizctl youtube-client")
    exit $p.ExitCode
}

if ($cmd[0] -eq "youtube-login") {
    # Browser sign-in on this PC with a "Desktop app" client: Google's web consent lets you pick a
    # brand-account channel, which the device code flow does not. Client and token then go to the
    # server over ssh stdin; the temporary token file is deleted afterwards.
    if ($cmd.Count -ne 2 -or -not (Test-Path -LiteralPath $cmd[1] -PathType Leaf)) {
        Write-Host "Usage: .\scripts\quiz-server.ps1 youtube-login <path to the Desktop app client JSON>"
        exit 1
    }
    $client = (Resolve-Path -LiteralPath $cmd[1]).Path
    $repo = Split-Path -Parent $PSScriptRoot
    $py = Join-Path $repo "venv\Scripts\python.exe"
    $tmp = Join-Path $env:TEMP ("yt_token_" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        $env:QUIZ_YT_CLIENT = $client
        $env:QUIZ_YT_TOKEN = $tmp
        Push-Location $repo
        & $py -m quiz.ytapi browser-auth
        $ok = $LASTEXITCODE
        Pop-Location
        if ($ok -ne 0 -or -not (Test-Path -LiteralPath $tmp)) { Write-Host "Sign-in did not finish."; exit 1 }
        $p = Start-Process -FilePath "ssh" -NoNewWindow -Wait -PassThru -RedirectStandardInput $client `
            -ArgumentList @("-i", "`"$sshKey`"", "root@$server", "quizctl youtube-client")
        if ($p.ExitCode -ne 0) { exit $p.ExitCode }
        $p = Start-Process -FilePath "ssh" -NoNewWindow -Wait -PassThru -RedirectStandardInput $tmp `
            -ArgumentList @("-i", "`"$sshKey`"", "root@$server", "quizctl youtube-token")
        exit $p.ExitCode
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
        Remove-Item Env:QUIZ_YT_CLIENT, Env:QUIZ_YT_TOKEN -ErrorAction SilentlyContinue
    }
}

if ($cmd[0] -eq "shell") {
    ssh -i $sshKey "root@$server"
    exit $LASTEXITCODE
}

# Quote every argument for the remote shell, so "18:00 01:00" stays one argument.
$quoted = ($cmd | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join " "
# -t gives a real terminal: needed for the hidden key prompt and the live log.
ssh -t -i $sshKey "root@$server" "quizctl $quoted"
exit $LASTEXITCODE
