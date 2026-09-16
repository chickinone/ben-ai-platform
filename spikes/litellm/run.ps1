# Chạy thử nghiệm LiteLLM: dựng môi trường, chạy 6 nhóm test, lưu kết quả vào results/.
# Dùng:  .\spikes\litellm\run.ps1 [-Down]
[CmdletBinding()]
param([switch]$Down)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $Root
$ComposeFile = 'spikes/litellm/docker-compose.yml'
$Results = Join-Path $PSScriptRoot 'results'
New-Item -ItemType Directory -Force $Results | Out-Null

if ($Down) {
    docker compose -f $ComposeFile down -v
    return
}

docker compose -f $ComposeFile up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw 'Không dựng được môi trường thử nghiệm' }

# Không đi qua pipeline PowerShell: từng làm pytest treo trên máy này
$pytest = Start-Process -FilePath '.\.venv\Scripts\python.exe' -NoNewWindow -PassThru -Wait `
    -ArgumentList @('-m', 'pytest', 'spikes/litellm/tests', '-v', '-p', 'no:warnings',
        '-o', 'faulthandler_timeout=120', '-o', 'testpaths=spikes/litellm/tests',
        "--junitxml=$Results\junit.xml") `
    -RedirectStandardOutput "$Results\pytest.log" -RedirectStandardError "$Results\pytest.err.log"

Get-Content "$Results\pytest.log" -Tail 40
docker compose -f $ComposeFile logs litellm --no-log-prefix *> "$Results\litellm.log"
Write-Host "Kết quả chi tiết: $Results\findings.json"
