# deployme.ps1 - Deploy FastAPI to Posit Connect on Windows PowerShell
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

$ArgsList = @("deploy", "fastapi", "--entrypoint", "app:app")
if ($Server) { $ArgsList += @("--server", $Server) }
if ($ApiKey) { $ArgsList += @("--api-key", $ApiKey) }
$ArgsList += "."

Write-Host "Deploying to Posit Connect ($Server)..."
& python -m rsconnect @ArgsList
