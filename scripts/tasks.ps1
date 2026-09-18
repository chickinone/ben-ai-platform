# Tác vụ phát triển cho Windows (thay cho Makefile).
# Dùng:  .\scripts\tasks.ps1 <task> [tham số]
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'init', 'venv', 'lint', 'fmt', 'test', 'test-integration', 'seed-demo', 'config', 'up', 'up-core', 'down', 'ps', 'logs', 'migrate', 'pull-model')]
    [string]$Task = 'help',

    [Parameter(Position = 1)]
    [string]$Arg
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root '.venv\Scripts\python.exe'

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') thất bại (exit $LASTEXITCODE)" }
}

function Assert-Env {
    if (-not (Test-Path (Join-Path $Root '.env'))) { throw 'Chưa có .env — chạy: .\scripts\tasks.ps1 init' }
}

function Assert-Venv {
    if (-not (Test-Path $Py)) { throw 'Chưa có .venv — chạy: .\scripts\tasks.ps1 venv' }
}

function Invoke-Compose {
    param([switch]$Core, [string[]]$Arguments)
    Assert-Env
    $composeArgs = @('compose', '--env-file', '.env', '-f', 'deploy/compose/docker-compose.yml')
    if (-not $Core) { $composeArgs += @('-f', 'deploy/compose/docker-compose.observability.yml') }
    Invoke-Checked -Exe 'docker' -Arguments ($composeArgs + $Arguments)
}

switch ($Task) {
    'help' {
        @'
Tác vụ:
  init              Tạo .env với mật khẩu ngẫu nhiên
  venv              Tạo .venv và cài package ở chế độ editable
  lint | fmt | test Kiểm tra code, định dạng, chạy unit test
  test-integration  Test tích hợp với LiteLLM Proxy đang chạy
  seed-demo         Tạo idempotent tenant demo cskh, hr, finance và virtual key dev
  config            Kiểm tra cấu hình Docker Compose
  up                Chạy toàn bộ (gồm OTel Collector, Langfuse)
  up-core           Chạy phần lõi (không có observability)
  down | ps         Dừng / xem trạng thái
  logs [service]    Xem log
  migrate           Chạy migration schema
  pull-model [tên]  Tải model Ollama (mặc định qwen2.5:7b)
'@
    }
    'init' { Invoke-Checked -Exe 'python' -Arguments @('scripts/init_env.py') }
    'venv' {
        if (-not (Test-Path $Py)) { Invoke-Checked -Exe 'python' -Arguments @('-m', 'venv', '.venv') }
        Invoke-Checked -Exe $Py -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip')
        Invoke-Checked -Exe $Py -Arguments @('-m', 'pip', 'install',
            '-e', 'libs/ben_common', '-e', 'libs/ben_telemetry',
            '-e', 'services/gateway[dev]', '-e', 'services/control-plane[dev]', '-e', 'services/metering-worker[dev]',
            '-e', 'libs/ben_litellm_plugins[dev]', 'ruff', 'mypy', 'openai', 'anthropic')
    }
    'lint' {
        Assert-Venv
        Invoke-Checked -Exe $Py -Arguments @('-m', 'ruff', 'check', '.')
        Invoke-Checked -Exe $Py -Arguments @('-m', 'ruff', 'format', '--check', '.')
        Invoke-Checked -Exe $Py -Arguments @('-m', 'mypy')
    }
    'fmt' {
        Assert-Venv
        Invoke-Checked -Exe $Py -Arguments @('-m', 'ruff', 'check', '--fix', '.')
        Invoke-Checked -Exe $Py -Arguments @('-m', 'ruff', 'format', '.')
    }
    'test' { Assert-Venv; Invoke-Checked -Exe $Py -Arguments @('-m', 'pytest') }
    'test-integration' {
        Assert-Venv
        Invoke-Checked -Exe $Py -Arguments @('-m', 'pytest', 'tests/integration', '-v', '-o', 'testpaths=tests/integration')
    }
    'seed-demo' { Assert-Env; Assert-Venv; Invoke-Checked -Exe $Py -Arguments @('scripts/seed_demo_tenants.py') }
    'config' { Invoke-Compose -Arguments @('config', '--quiet'); Write-Host 'Cấu hình compose hợp lệ.' }
    'up' { Invoke-Compose -Arguments @('up', '-d', '--build') }
    'up-core' { Invoke-Compose -Core -Arguments @('up', '-d', '--build') }
    'down' { Invoke-Compose -Arguments @('down') }
    'ps' { Invoke-Compose -Arguments @('ps') }
    'logs' {
        $logArgs = @('logs', '-f', '--tail', '100')
        if ($Arg) { $logArgs += $Arg }
        Invoke-Compose -Arguments $logArgs
    }
    'migrate' { Invoke-Compose -Core -Arguments @('run', '--rm', 'migrate') }
    'pull-model' {
        $model = if ($Arg) { $Arg } else { 'qwen2.5:7b' }
        Invoke-Compose -Core -Arguments @('exec', 'ollama', 'ollama', 'pull', $model)
    }
}
