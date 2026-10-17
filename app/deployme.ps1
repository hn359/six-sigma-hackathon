# deployme.ps1 - Deploy FastAPI to Posit Connect on Windows PowerShell using manifest.json
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# Optional: load CONNECT_SERVER and CONNECT_API_KEY from .env (in app/ or repo root)
$EnvFile = if (Test-Path ".env") { ".env" } elseif (Test-Path "..\.env") { "..\.env" } else { $null }
if ($EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

$Server = [System.Environment]::GetEnvironmentVariable("CONNECT_SERVER")
$ApiKey = [System.Environment]::GetEnvironmentVariable("CONNECT_API_KEY")
$AppId = [System.Environment]::GetEnvironmentVariable("CONNECT_APP_ID")
if (-not $AppId) {
    $AppId = "17ab3147-debc-48ae-8548-2d63bbba623d"
}

$ArgsList = @("deploy", "manifest")
if ($Server) { $ArgsList += @("--server", $Server) }
if ($ApiKey) { $ArgsList += @("--api-key", $ApiKey) }
if ($AppId) { $ArgsList += @("--app-id", $AppId) }
$ArgsList += "manifest.json"

Write-Host "Deploying app via manifest to Posit Connect ($Server) [App ID: $AppId]..."
& python -m rsconnect @ArgsList
