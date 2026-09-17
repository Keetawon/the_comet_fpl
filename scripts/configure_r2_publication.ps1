# Run interactively on the existing owner host. Never paste credentials into chat.
# Creates a dedicated, owner-readable SDK profile outside the Git checkout.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$EndpointUrl,
    [string]$Bucket = 'the-comet-dashboard',
    [string]$PublicBaseUrl = 'https://data.thecometfpl.com',
    [string]$Directory = 'D:/Personal/fpl-operations/r2'
)
$ErrorActionPreference = 'Stop'
$endpoint = [Uri]$EndpointUrl
if ($endpoint.Scheme -ne 'https' -or $endpoint.Port -ne 443 -or $endpoint.Host -notmatch '^[a-z0-9.-]+\.r2\.cloudflarestorage\.com$' -or
    $endpoint.UserInfo -or $endpoint.Query -or $endpoint.Fragment -or $endpoint.AbsolutePath -ne '/') {
    throw 'Use the HTTPS S3 API endpoint shown by Cloudflare R2 (without a bucket path).'
}
$public = [Uri]$PublicBaseUrl
if ($public.Scheme -ne 'https' -or $public.Port -ne 443 -or $public.UserInfo -or $public.Query -or $public.Fragment -or $public.AbsolutePath -ne '/') {
    throw 'PublicBaseUrl must be a clean HTTPS origin.'
}
if ($Bucket -notmatch '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$') { throw 'Invalid bucket name.' }
$destination = [IO.Path]::GetFullPath($Directory)
$checkout = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
if ($destination -eq $checkout -or $destination.StartsWith($checkout + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Credentials must be outside the repository.'
}
$ancestor = $destination
while ($ancestor) {
    if (Test-Path -LiteralPath (Join-Path $ancestor '.git')) { throw 'Credentials cannot be inside any Git checkout.' }
    if ((Test-Path -LiteralPath $ancestor) -and
        ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Credential directory ancestors must not be symlinks or junctions.'
    }
    $ancestor = Split-Path -Parent $ancestor
}
if (Test-Path -LiteralPath $destination) {
    throw 'Use a new dedicated directory; existing directories and permissions will not be changed.'
}
$credentialsPath = Join-Path $destination 'credentials'
$configPath = Join-Path $destination 'publication.json'
if ((Test-Path -LiteralPath $credentialsPath) -or (Test-Path -LiteralPath $configPath)) {
    throw 'Configuration already exists; inspect it rather than overwriting credentials.'
}
if (-not $PSCmdlet.ShouldProcess($destination, 'Create an owner-only R2 profile and publication config')) { return }
New-Item -ItemType Directory -Path $destination | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($identity)
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
Set-Acl -LiteralPath $destination -AclObject $acl
$access = Read-Host 'R2 Access Key ID (hidden input)' -AsSecureString
$secret = Read-Host 'R2 Secret Access Key (hidden input)' -AsSecureString
$accessPtr = [IntPtr]::Zero
$secretPtr = [IntPtr]::Zero
try {
    $accessPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($access)
    $secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $accessText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($accessPtr)
    $secretText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)
    if ($accessText -notmatch '^[A-Za-z0-9]+$' -or $secretText -notmatch '^[A-Za-z0-9/+=]+$') {
        throw 'Invalid credential characters; no credential file was created.'
    }
    $body = "[comet-r2]`naws_access_key_id = $accessText`naws_secret_access_key = $secretText`n"
    $encoding = [Text.UTF8Encoding]::new($false)
    $bytes = $encoding.GetBytes($body)
    $stream = [IO.File]::Open($credentialsPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    $configuration = @{
        bucket = $Bucket; endpoint_url = $EndpointUrl.TrimEnd('/'); public_base_url = $PublicBaseUrl.TrimEnd('/')
        credentials_file = $credentialsPath; profile = 'comet-r2'
    } | ConvertTo-Json
    $configBytes = $encoding.GetBytes($configuration)
    $configStream = [IO.File]::Open($configPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $configStream.Write($configBytes, 0, $configBytes.Length); $configStream.Flush($true) } finally { $configStream.Dispose() }
    Write-Output "R2 credentials saved locally with owner-only access. Config: $configPath"
    Write-Output 'Nothing was uploaded and the scheduled task was not changed by this setup script.'
} finally {
    if ($accessPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($accessPtr) }
    if ($secretPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr) }
    $access.Dispose(); $secret.Dispose()
    $accessText = $null; $secretText = $null; $body = $null; $bytes = $null
}
