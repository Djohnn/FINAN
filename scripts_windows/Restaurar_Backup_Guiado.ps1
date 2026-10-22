param(
    [Parameter(Mandatory = $true)]
    [string]$Source
)

$ErrorActionPreference = 'Stop'

try {
    $RepositoryRoot = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '..')).FullName
    $Python = Join-Path $RepositoryRoot 'venv\Scripts\python.exe'
    $Manage = Join-Path $RepositoryRoot 'manage.py'
    $LiveDatabase = Join-Path $RepositoryRoot 'db.sqlite3'

    if (-not [System.IO.Path]::IsPathRooted($Source)) {
        throw 'A origem deve ser um caminho absoluto.'
    }
    if ($Source.StartsWith('\\')) {
        throw 'Origem de rede/UNC não é aceita.'
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'Interpretador canônico não encontrado em venv\Scripts\python.exe.'
    }
    if (-not (Test-Path -LiteralPath $Manage -PathType Leaf)) {
        throw 'manage.py não foi encontrado na raiz do repositório.'
    }
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw 'A origem informada não é um arquivo regular existente.'
    }

    $SourceItem = Get-Item -LiteralPath $Source
    if (($SourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Symlink ou reparse point não é aceito como origem.'
    }

    $Secret = $env:DJANGO_SECRET_KEY
    if (-not $Secret) {
        $Secret = [Environment]::GetEnvironmentVariable('DJANGO_SECRET_KEY', 'User')
    }
    if (-not $Secret) {
        $Secret = [Environment]::GetEnvironmentVariable('DJANGO_SECRET_KEY', 'Machine')
    }
    if ($Secret) {
        $env:DJANGO_SECRET_KEY = $Secret
    }

    $Runserver = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^python(\.exe)?$' -and
            $_.CommandLine -match 'manage\.py.*runserver'
        }
    if ($Runserver) {
        throw 'Um processo conhecido de runserver do FinanPE está ativo. Feche-o e tente novamente.'
    }

    Write-Host "Origem selecionada: $Source"
    Write-Host "Banco ativo: $LiveDatabase"
    Write-Host 'Executando pré-validação somente leitura...'
    & $Python $Manage restaurar_backup --source $Source --dry-run
    if ($LASTEXITCODE -ne 0) {
        throw "A pré-validação falhou com código $LASTEXITCODE."
    }

    $Confirmation = Read-Host 'Digite exatamente RESTAURAR FINANPE para confirmar'
    if ($Confirmation -cne 'RESTAURAR FINANPE') {
        throw 'Confirmação não reconhecida; nenhuma restauração foi executada.'
    }

    & $Python $Manage restaurar_backup --source $Source --confirm-restore --expected-live-db $LiveDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "A restauração falhou com código $LASTEXITCODE."
    }
    Write-Host 'Restauração concluída.'
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
