$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $RepositoryRoot "deploy\compose.yaml"
$EnvironmentFile = Join-Path $RepositoryRoot "deploy\.env"
$ComposeArguments = @()
if (Test-Path $EnvironmentFile) {
    $ComposeArguments = @("--env-file", $EnvironmentFile)
}

Push-Location $RepositoryRoot
try {
    docker compose @ComposeArguments -f $ComposeFile up --build --detach
    docker compose @ComposeArguments -f $ComposeFile run --rm smoke
    docker compose @ComposeArguments -f $ComposeFile restart worker api
    docker compose @ComposeArguments -f $ComposeFile run --rm smoke
}
finally {
    Pop-Location
}
