param(
    [switch]$RuntimeOnly,
    [switch]$Verify,
    [ValidateSet('bf16','int8','nf4','all')][string]$Precision = '',
    [string]$RuntimeBaseUrl = '',
    [string]$DownloadDirectory = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$Work = Join-Path $Root '.install'
$EnvironmentPath = Join-Path $Root 'python_embeded'
$LockPath = Join-Path $Root 'manifests\runtime.lock.json'
$Lock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$Utf8 = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8

function Get-Digest([string]$Path) {
    $Stream = [IO.File]::OpenRead($Path)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($Hasher.ComputeHash($Stream)).Replace('-','').ToLowerInvariant() }
    finally { $Hasher.Dispose(); $Stream.Dispose() }
}
function Assert-WithinRoot([string]$Path) {
    $Resolved = [IO.Path]::GetFullPath($Path)
    if (-not $Resolved.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe installation path: $Resolved" }
    return $Resolved
}
function Test-Environment([string]$Path) {
    try {
        if ((Get-Digest (Join-Path $Path 'environment.files.json')) -ne $Lock.environment_manifest_sha256) { return $false }
        $Metadata = Get-Content -LiteralPath (Join-Path $Path 'environment.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($Metadata.runtime_id -ne $Lock.runtime_id) { return $false }
        foreach ($File in $Lock.critical_files) {
            $Target = [IO.Path]::GetFullPath((Join-Path $Path $File.path))
            if (-not $Target.StartsWith($Path.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { return $false }
            if (-not [IO.File]::Exists($Target)) { return $false }
            if ((Get-Item -LiteralPath $Target).Length -ne $File.bytes -or (Get-Digest $Target) -ne $File.sha256) { return $false }
        }
        return $true
    } catch { return $false }
}
function Confirm-AllFiles([string]$Path) {
    & (Join-Path $Path 'python.exe') -X utf8 -u (Join-Path $Root 'bootstrap\check_runtime.py') --environment $Path --lock $LockPath --full
    if ($LASTEXITCODE -ne 0) { throw 'Python runtime verification failed.' }
}
function Write-Receipt {
    $Receipt = @{ runtime_id=$Lock.runtime_id; manifest_sha256=$Lock.environment_manifest_sha256; full_verified=$true; utc=[DateTime]::UtcNow.ToString('o') }
    [IO.File]::WriteAllText((Join-Path $Work 'receipt.json'), ($Receipt | ConvertTo-Json), $Utf8)
}
function Get-Volume([object]$Part, [string]$Directory, [string]$BaseUrl) {
    if ([IO.Path]::GetFileName($Part.name) -ne $Part.name -or $Part.name -notmatch '\.7z\.\d{3}$') { throw 'Invalid volume name.' }
    $Target = Join-Path $Directory $Part.name
    if ([IO.File]::Exists($Target)) {
        if ((Get-Item -LiteralPath $Target).Length -eq $Part.bytes -and (Get-Digest $Target) -eq $Part.sha256) { return $Target }
        throw "Corrupt archive volume. Remove this file and retry: $Target"
    }
    if (-not $BaseUrl) { throw "No release URL is configured yet. Place all volumes in downloads or specify -RuntimeBaseUrl. Required file: $($Part.name)" }
    $Uri = [Uri]($BaseUrl.TrimEnd('/') + '/' + [Uri]::EscapeDataString($Part.name))
    if ($Uri.Scheme -ne 'https' -and -not ($Uri.Scheme -eq 'http' -and $Uri.IsLoopback)) { throw 'Downloads require HTTPS (local test servers may use HTTP).' }
    $Partial = $Target + '.partial'
    $Offset = 0L
    if ([IO.File]::Exists($Partial)) { $Offset = (Get-Item -LiteralPath $Partial).Length }
    if ($Offset -gt $Part.bytes) { throw "Partial volume is oversized: $Partial" }
    if ($Offset -lt $Part.bytes) {
        Write-Host "Downloading runtime: $($Part.name) (resume: $Offset bytes)"
        $Request = New-Object Net.Http.HttpRequestMessage([Net.Http.HttpMethod]::Get, $Uri)
        if ($Offset -gt 0) { $Request.Headers.Range = New-Object Net.Http.Headers.RangeHeaderValue($Offset, $null) }
        $Response = $null; $InputStream = $null; $OutputStream = $null
        try {
            $Response = $Client.SendAsync($Request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            $Response.EnsureSuccessStatusCode() | Out-Null
            if ([int]$Response.StatusCode -eq 206) {
                if ($Response.Content.Headers.ContentRange.From -ne $Offset) { throw 'Invalid download resume offset.' }
            } elseif ([int]$Response.StatusCode -eq 200) { $Offset = 0L }
            else { throw 'Unexpected download response.' }
            $InputStream = $Response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $Mode = if ($Offset -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = New-Object IO.FileStream($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None, 1048576)
            $Buffer = New-Object byte[] 1048576
            while (($Count = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Count)
                if ($OutputStream.Length -gt $Part.bytes) { throw 'Downloaded volume exceeds its expected size.' }
            }
        } finally {
            if ($OutputStream) { $OutputStream.Dispose() }; if ($InputStream) { $InputStream.Dispose() }
            if ($Response) { $Response.Dispose() }; $Request.Dispose()
        }
    }
    if ((Get-Item -LiteralPath $Partial).Length -ne $Part.bytes -or (Get-Digest $Partial) -ne $Part.sha256) { throw "Archive checksum failed. Remove this file and retry: $Partial" }
    Move-Item -LiteralPath $Partial -Destination $Target
    return $Target
}

$Guard = $null; $Client = $null
try {
    if ($Root.Contains(';')) { throw 'Installation paths cannot contain semicolons (;).' }
    [IO.Directory]::CreateDirectory($Work) | Out-Null
    $Guard = [IO.File]::Open((Join-Path $Work 'install.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $Valid = Test-Environment $EnvironmentPath
    if ($Valid) {
        $ReceiptOk = $false
        $ReceiptPath = Join-Path $Work 'receipt.json'
        if ([IO.File]::Exists($ReceiptPath)) {
            try {
                $Receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $ReceiptOk = $Receipt.full_verified -and $Receipt.runtime_id -eq $Lock.runtime_id -and $Receipt.manifest_sha256 -eq $Lock.environment_manifest_sha256
            } catch { $ReceiptOk = $false }
        }
        if ($Verify -or -not $ReceiptOk) { Confirm-AllFiles $EnvironmentPath; Write-Receipt }
        Write-Host "Runtime ready: $($Lock.runtime_id)"
    } else {
        if (-not $Lock.parts -or $Lock.parts.Count -eq 0) { throw 'The archive volume list is empty. Complete runtime packaging first.' }
        if (-not $DownloadDirectory) { $DownloadDirectory = Join-Path $Root 'downloads' }
        $DownloadDirectory = [IO.Path]::GetFullPath($DownloadDirectory)
        [IO.Directory]::CreateDirectory($DownloadDirectory) | Out-Null
        if (-not $RuntimeBaseUrl) { $RuntimeBaseUrl = $Lock.publication.base_url }
        Add-Type -AssemblyName System.Net.Http
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $Client = New-Object Net.Http.HttpClient
        $Client.Timeout = [TimeSpan]::FromHours(6)
        $Volumes = @()
        foreach ($Part in $Lock.parts) { $Volumes += Get-Volume $Part $DownloadDirectory $RuntimeBaseUrl }
        $Extractor = Join-Path $Root $Lock.extractor.path
        if ((Get-Digest $Extractor) -ne $Lock.extractor.sha256) { throw '7-Zip checksum mismatch.' }
        $Listing = & $Extractor l -slt -sccUTF-8 $Volumes[0]
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read runtime archive.' }
        $InFiles = $false; $Entries = 0
        foreach ($Line in $Listing) {
            if ($Line -eq '----------') { $InFiles = $true; continue }
            if ($InFiles -and $Line.StartsWith('Path = ')) {
                $Name = $Line.Substring(7).Replace('\','/')
                if ($Name -notmatch '^python_embeded(/|$)' -or $Name -match '(^|/)\.\.(/|$)|:|^/') { throw "Invalid archive path: $Name" }
                $Entries++
            }
            if ($InFiles -and $Line -match '^(Symbolic Link|Hard Link) = ') { throw 'Runtime archives cannot contain links.' }
        }
        if ($Entries -eq 0) { throw 'Empty runtime archive.' }
        $Stage = Assert-WithinRoot (Join-Path $Work ('stage_' + [Guid]::NewGuid().ToString('N')))
        [IO.Directory]::CreateDirectory($Stage) | Out-Null
        Write-Host 'Extracting and verifying every runtime file.'
        & $Extractor x $Volumes[0] "-o$Stage" -y -bsp0 -bb0 -sccUTF-8
        if ($LASTEXITCODE -ne 0) { throw "Extraction failed; retained for inspection: $Stage" }
        $Candidate = Assert-WithinRoot (Join-Path $Stage 'python_embeded')
        if (-not (Test-Environment $Candidate)) { throw 'Staged runtime is invalid.' }
        Confirm-AllFiles $Candidate
        $Running = @(
            foreach ($Process in [Diagnostics.Process]::GetProcesses()) {
                try {
                    if ($Process.MainModule.FileName.StartsWith($EnvironmentPath + '\', [StringComparison]::OrdinalIgnoreCase)) { $Process.Id }
                } catch { } finally { $Process.Dispose() }
            }
        )
        if ($Running) { throw 'Close all MotionAI workers before replacing the runtime.' }
        $Backup = $null
        if ([IO.Directory]::Exists($EnvironmentPath)) {
            $Backup = Assert-WithinRoot (Join-Path $Work ('previous_' + [Guid]::NewGuid().ToString('N')))
            $null = Assert-WithinRoot $EnvironmentPath
            Move-Item -LiteralPath $EnvironmentPath -Destination $Backup
        }
        try { Move-Item -LiteralPath $Candidate -Destination $EnvironmentPath }
        catch {
            if ($Backup -and -not [IO.Directory]::Exists($EnvironmentPath)) { Move-Item -LiteralPath $Backup -Destination $EnvironmentPath }
            throw
        }
        Write-Receipt
        Write-Host 'Runtime installation completed.'
    }
    if (-not $RuntimeOnly) {
        $Arguments = @('-X','utf8','-u',(Join-Path $Root 'runtime\entry.py'),'install')
        if ($Precision) { $Arguments += @('--precision',$Precision) }
        if ($Verify) { $Arguments += '--verify' }
        & (Join-Path $EnvironmentPath 'python.exe') @Arguments
        if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed.' }
    }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($Client) { $Client.Dispose() }; if ($Guard) { $Guard.Dispose() }
}
