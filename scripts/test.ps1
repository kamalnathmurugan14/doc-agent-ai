# Run every check on Windows PowerShell:  .\scripts\test.ps1
$ErrorActionPreference = "Stop"
Push-Location "$PSScriptRoot\..\backend"
ruff check .; black --check .; pytest --cov=app
Pop-Location
Push-Location "$PSScriptRoot\..\frontend"
npm run test:all
Pop-Location
