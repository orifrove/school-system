# Run Django with the project's virtual environment, from any directory.
# Keep arguments unparsed so Django receives flags such as --limit unchanged.
$backendDirectory = Join-Path $PSScriptRoot 'backend'
$pythonExecutable = Join-Path $backendDirectory 'venv\Scripts\python.exe'
$managementScript = Join-Path $backendDirectory 'manage.py'

if (!(Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    Write-Error "Project Python not found: $pythonExecutable. Create backend\venv and install backend dependencies first."
    exit 1
}
if (!(Test-Path -LiteralPath $managementScript -PathType Leaf)) {
    Write-Error "Django entry point not found: $managementScript. Check the project checkout."
    exit 1
}

$commandExitCode = 1
Push-Location -LiteralPath $backendDirectory -ErrorAction Stop
try {
    & $pythonExecutable $managementScript @args
    $commandExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $commandExitCode
