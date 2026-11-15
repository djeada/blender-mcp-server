# Native Windows setup, launch, scene check and shutdown for Blender MCP.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Setup', 'Start', 'Status', 'Stop')][string]$Action,
    [string]$Blender = $env:BLENDER_BIN,
    [string]$Python = $env:PYTHON_BIN,
    [ValidateRange(1024, 65535)][int]$Port,
    [string]$TokenFile = $env:BLENDER_MCP_TOKEN_FILE,
    [switch]$SkipAddon
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Server = Join-Path $Venv 'Scripts\blender-mcp-server.exe'
$Config = Join-Path $Venv 'blender-windows.json'
$PidFile = Join-Path $Venv 'blender-windows-process.json'
$AppDir = Join-Path $env:LOCALAPPDATA 'BlenderMCP'
$UserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$Utf8 = [Text.UTF8Encoding]::new($false)

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable exited with code $LASTEXITCODE."
    }
}

function Get-Executable([string]$Candidate, [string]$Hint) {
    $command = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { throw $Hint }
    $command.Source
}

function Find-Blender {
    if ($Blender) { return Get-Executable $Blender 'Blender executable not found. Set -Blender to blender.exe.' }
    $onPath = Get-Command blender -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($onPath) { return $onPath.Source }
    $installRoot = Join-Path $env:ProgramFiles 'Blender Foundation'
    $candidate = Get-ChildItem -LiteralPath $installRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^Blender (\d+(\.\d+)+)$' -and (Test-Path (Join-Path $_.FullName 'blender.exe')) } |
        Sort-Object { [version]($_.Name -replace '^Blender ', '') } -Descending |
        Select-Object -First 1
    if (-not $candidate) { throw 'Install Blender 3.6 or newer, or pass -Blender C:\path\to\blender.exe.' }
    Join-Path $candidate.FullName 'blender.exe'
}

function Get-BlenderVersion([string]$Executable) {
    $header = (Invoke-Checked $Executable @('--version') | Select-Object -First 1)
    if ($header -notmatch '^Blender (\d+\.\d+\.\d+)') { throw 'Could not determine the Blender version.' }
    $version = [version]$Matches[1]
    if ($version -lt [version]'3.6') { throw 'Blender 3.6 or newer is required for this add-on.' }
    $version
}

function Protect-Path([string]$Path, [bool]$Directory, [bool]$Created) {
    $entry = Get-Item -LiteralPath $Path -Force
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $entry.LinkType -eq 'HardLink') {
        throw "Token storage must use a regular local path. Inspect $Path."
    }
    $acl = Get-Acl -LiteralPath $Path
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]) -ne $UserSid) {
        if (-not $Created) { throw "Run setup as the user who owns $Path." }
        $acl.SetOwner($UserSid)
    }
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in $acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier])) {
        $acl.RemoveAccessRuleSpecific($rule)
    }
    $flags = [Security.AccessControl.InheritanceFlags]::None
    if ($Directory) {
        $flags = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    }
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $UserSid, 'FullControl', $flags, 'None', 'Allow'
    )
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Initialize-Token([string]$Path) {
    $existed = Test-Path -LiteralPath $Path -PathType Leaf
    if (-not $existed) {
        $file = [IO.File]::Open($Path, 'CreateNew', 'Write', 'None')
        $file.Dispose()
    }
    Protect-Path $Path $false (-not $existed)
    if (-not $existed) {
        $bytes = [byte[]]::new(32)
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [IO.File]::WriteAllText($Path, [Convert]::ToBase64String($bytes), $Utf8)
    }
    if ([string]::IsNullOrWhiteSpace([IO.File]::ReadAllText($Path))) {
        throw 'The token file is empty. Remove it and run Setup again to regenerate it.'
    }
}

function Get-LaunchedBlender {
    if (-not (Test-Path -LiteralPath $PidFile)) { return }
    $saved = Get-Content -Raw -LiteralPath $PidFile | ConvertFrom-Json
    $process = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq $saved.path -and
        $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $saved.started) {
        return $process
    }
    Remove-Item -LiteralPath $PidFile
}

if ($Action -eq 'Stop') {
    $process = Get-LaunchedBlender
    if (-not $process) { Write-Output 'No running Blender instance from this launcher.'; return }
    if (-not $process.CloseMainWindow()) {
        throw 'Blender has no responsive main window. Close it from Blender or Windows Task Manager.'
    }
    Write-Output 'Requested Blender shutdown. Respond to any save prompt in Blender.'
    return
}

$savedConfig = if (Test-Path -LiteralPath $Config) { Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json }
if (-not $Blender -and $savedConfig) { $Blender = $savedConfig.blender }
if ($savedConfig) {
    if (-not $env:BLENDER_MCP_POLICY_FILE) { $env:BLENDER_MCP_POLICY_FILE = $savedConfig.policy }
    if (-not $env:BLENDER_USER_RESOURCES) { $env:BLENDER_USER_RESOURCES = $savedConfig.profile }
}
if (-not $PSBoundParameters.ContainsKey('Port')) {
    if ($env:BLENDER_MCP_PORT) { $Port = [int]$env:BLENDER_MCP_PORT }
    elseif ($savedConfig) { $Port = $savedConfig.port }
    else { $Port = 9876 }
}
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'BLENDER_MCP_PORT must be between 1024 and 65535.' }
if (-not $TokenFile) {
    if ($savedConfig) { $TokenFile = $savedConfig.tokenFile }
    else { $TokenFile = Join-Path $AppDir 'token' }
}
$TokenFile = [IO.Path]::GetFullPath($TokenFile)
$env:BLENDER_MCP_PORT = [string]$Port
$env:BLENDER_MCP_TOKEN_FILE = $TokenFile
Remove-Item Env:BLENDER_MCP_TOKEN -ErrorAction SilentlyContinue

if ($Action -eq 'Setup') {
    if (-not $SkipAddon) {
        $Blender = Find-Blender
        $version = Get-BlenderVersion $Blender
    }
    if (-not $Python) { $Python = 'python.exe' }
    $Python = Get-Executable $Python 'Install Python 3.10+ and add it to PATH, or pass -Python C:\path\to\python.exe.'
    Invoke-Checked $Python @('-c', 'import sys; sys.exit("Python 3.10 or newer is required") if sys.version_info < (3, 10) else None')
    if (-not (Test-Path -LiteralPath $VenvPython)) { Invoke-Checked $Python @('-m', 'venv', $Venv) }
    Invoke-Checked $VenvPython @('-m', 'pip', 'install', '-e', $Root)
    if (-not (Test-Path -LiteralPath $Server)) { throw 'The MCP server executable is missing from .venv\Scripts.' }

    if ($TokenFile -eq (Join-Path $AppDir 'token')) {
        $created = -not (Test-Path -LiteralPath $AppDir)
        [IO.Directory]::CreateDirectory($AppDir) | Out-Null
        Protect-Path $AppDir $true $created
    }
    if (-not (Test-Path -LiteralPath (Split-Path -Parent $TokenFile) -PathType Container)) {
        throw 'Create a private directory for the custom token path, or omit -TokenFile for the default.'
    }
    Initialize-Token $TokenFile

    $archive = Join-Path $Root 'dist\blender_mcp_bridge.zip'
    Invoke-Checked $VenvPython @((Join-Path $PSScriptRoot 'build_addon_zip.py'), '--output', $archive)
    if (-not $SkipAddon) {
        $helper = Join-Path $PSScriptRoot 'lib\blender_addon_setup.py'
        $helperArgs = @('-b', '--python-exit-code', '1', '--python', $helper, '--')
        if ($version -ge [version]'4.2') {
            Invoke-Checked $Blender ($helperArgs + 'remove-legacy')
            Invoke-Checked $Blender @('-b', '--factory-startup', '--command', 'extension', 'install-file', '-r', 'user_default', '-e', $archive)
        } else {
            Invoke-Checked $Blender ($helperArgs + @('install-legacy', $archive))
        }
        $verification = Invoke-Checked $Blender ($helperArgs + 'verify')
        if (-not ($verification -match '^MCP_ADDON_OK ')) {
            throw "Blender did not enable the add-on. $($verification -join ' ')"
        }
    }

    $state = @{
        blender = $Blender; port = $Port; tokenFile = $TokenFile
        policy = $env:BLENDER_MCP_POLICY_FILE; profile = $env:BLENDER_USER_RESOURCES
    } | ConvertTo-Json
    [IO.File]::WriteAllText($Config, $state, $Utf8)
    $clientConfig = Join-Path $Venv 'blender-mcp.json'
    $pairs = @("BLENDER_MCP_PORT=$Port", "BLENDER_MCP_TOKEN_FILE=$TokenFile")
    foreach ($key in @('BLENDER_MCP_POLICY_FILE', 'BLENDER_MCP_HEADLESS', 'BLENDER_MCP_TIMEOUT', 'BLENDER_MCP_HEADLESS_TIMEOUT')) {
        $value = [Environment]::GetEnvironmentVariable($key)
        if ($value) { $pairs += "$key=$value" }
    }
    if ($Blender) { $pairs += "BLENDER_BIN=$Blender" }
    Invoke-Checked $VenvPython (@((Join-Path $PSScriptRoot 'lib\client_config.py'), 'claude-json', $clientConfig, $Server) + $pairs)
    Write-Output "MCP client configuration: $clientConfig"
    return
}

if (-not (Test-Path -LiteralPath $VenvPython) -or -not $savedConfig) {
    throw 'Run scripts\windows.ps1 Setup first.'
}
if ($Action -eq 'Status') {
    Invoke-Checked $VenvPython @((Join-Path $PSScriptRoot 'blender_scene_info.py'), '--port', $Port)
    return
}
if (Get-LaunchedBlender) { throw 'Blender is already running from this launcher.' }
if (-not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) { throw 'Token file is missing. Run Setup again.' }
$Blender = Find-Blender
$null = Get-BlenderVersion $Blender
$process = Start-Process -FilePath $Blender -PassThru
$processState = @{ id = $process.Id; path = $Blender; started = $process.StartTime.ToUniversalTime().Ticks.ToString() }
[IO.File]::WriteAllText($PidFile, ($processState | ConvertTo-Json), $Utf8)
Write-Output "Started Blender on bridge port $Port. Use Status after the MCP panel shows Listening."
