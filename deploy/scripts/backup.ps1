$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $RepositoryRoot "deploy\compose.yaml"
$EnvironmentFile = Join-Path $RepositoryRoot "deploy\.env"
$BackupId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$SourceRevision = (git -C $RepositoryRoot rev-parse HEAD).Trim()
$SourceDirty = if (git -C $RepositoryRoot status --porcelain) { "true" } else { "false" }
$ComposeArguments = @("--env-file", $EnvironmentFile, "-f", $ComposeFile)

Push-Location $RepositoryRoot
try {
    docker compose @ComposeArguments stop frontend api
    if ($LASTEXITCODE -ne 0) { throw "Could not stop frontend and API." }
    docker compose @ComposeArguments stop outbox-publisher worker
    if ($LASTEXITCODE -ne 0) { throw "Could not stop outbox publisher and worker." }
    docker compose @ComposeArguments --profile tools run --rm maintenance create `
        --destination /backups `
        --backup-id $BackupId `
        --source-revision $SourceRevision `
        --source-dirty $SourceDirty
    if ($LASTEXITCODE -ne 0) { throw "Backup creation failed." }
}
finally {
    docker compose @ComposeArguments start outbox-publisher worker api frontend
    if ($LASTEXITCODE -ne 0) { Write-Error "Could not restart the application stack." }
    Pop-Location
}

docker compose @ComposeArguments --profile tools run --rm maintenance `
    upload-offsite `
    --backup-set "/backups/$BackupId"
if ($LASTEXITCODE -ne 0) { throw "Off-site backup upload failed." }

Write-Output (Join-Path $RepositoryRoot ".backups\$BackupId")
