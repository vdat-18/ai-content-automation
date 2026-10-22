$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (git -C $RepositoryRoot status --porcelain) {
    throw "Deployment checkout has uncommitted changes; aborting before backup or pull."
}

Push-Location $RepositoryRoot
try {
    & (Join-Path $PSScriptRoot "backup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Pre-deploy backup failed." }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "Git fast-forward pull failed." }
    just up
    if ($LASTEXITCODE -ne 0) { throw "Stack update failed." }
    just smoke
    if ($LASTEXITCODE -ne 0) { throw "Post-deploy smoke test failed." }
}
finally {
    Pop-Location
}
