param(
    [Parameter(Mandatory = $true)]
    [string]$BackupSet
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $RepositoryRoot "deploy\compose.yaml"
$EnvironmentFile = Join-Path $RepositoryRoot "deploy\.env"
$ResolvedBackup = (Resolve-Path $BackupSet).Path
$BackupRoot = (Resolve-Path (Join-Path $RepositoryRoot ".backups")).Path
if (-not $ResolvedBackup.StartsWith($BackupRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "BackupSet must be a child of the repository .backups directory."
}
$BackupName = Split-Path $ResolvedBackup -Leaf
$ProjectName = "aicontent-ai-restore-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
$ComposeArguments = @("--project-name", $ProjectName, "--env-file", $EnvironmentFile, "-f", $ComposeFile)

Push-Location $RepositoryRoot
try {
    docker compose @ComposeArguments up --detach postgres rabbitmq object-storage
    if ($LASTEXITCODE -ne 0) { throw "Could not start the clean restore dependencies." }
    docker compose @ComposeArguments --profile tools run --rm maintenance restore `
        --backup-set "/backups/$BackupName"
    if ($LASTEXITCODE -ne 0) { throw "Restore failed." }
    docker compose @ComposeArguments run --rm migrate
    if ($LASTEXITCODE -ne 0) { throw "Could not migrate the restored database." }
    docker compose @ComposeArguments --profile tools run --rm maintenance recover-execution `
        --backup-set "/backups/$BackupName"
    if ($LASTEXITCODE -ne 0) { throw "Could not recover restored execution commands." }
    docker compose @ComposeArguments up --detach api outbox-publisher worker
    if ($LASTEXITCODE -ne 0) { throw "Could not start the restored application." }
    docker compose @ComposeArguments --profile tools run --rm maintenance verify-http `
        --backup-set "/backups/$BackupName" `
        --base-url http://api:8000
    if ($LASTEXITCODE -ne 0) { throw "Restored HTTP verification failed." }
}
finally {
    docker compose @ComposeArguments down --volumes --remove-orphans
    Pop-Location
}
