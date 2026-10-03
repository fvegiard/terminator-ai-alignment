$ErrorActionPreference = 'Stop'
$lab = $PSScriptRoot
$runName = 'pain-axis-pilot-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$runDir = Join-Path $lab ('results\' + $runName)
New-Item -ItemType Directory -Path $runDir | Out-Null
$image = docker image inspect francis-pain-axis-sandbox:pilot-20261003 --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Sandbox image is missing' }
$argsList = @('create', '--name', $runName, '--network=none', '--read-only',
    '--user=65534:65534', '--cap-drop=ALL', '--security-opt=no-new-privileges',
    '--pids-limit=128', '--memory=12g', '--memory-swap=12g', '--cpus=6',
    '--tmpfs=/tmp:rw,noexec,nosuid,size=256m', '--shm-size=256m',
    '--mount', "type=bind,source=$(Join-Path $lab 'src'),target=/app,readonly",
    '--mount', "type=bind,source=$(Join-Path $lab 'data'),target=/data,readonly",
    '--mount', "type=bind,source=$(Join-Path $lab 'model'),target=/model,readonly",
    '--mount', "type=bind,source=$runDir,target=/results", $image)
$container = docker @argsList
if ($LASTEXITCODE -ne 0) { throw 'Sandbox creation failed' }
$inspection = docker inspect $container | ConvertFrom-Json | Select-Object -First 1
[pscustomobject]@{
    name=$runName; container_id=$container; image=$inspection.Image;
    user=$inspection.Config.User; network=$inspection.HostConfig.NetworkMode;
    read_only_root=$inspection.HostConfig.ReadonlyRootfs;
    capabilities_dropped=$inspection.HostConfig.CapDrop;
    security_options=$inspection.HostConfig.SecurityOpt;
    memory_bytes=$inspection.HostConfig.Memory; cpu_nanocpus=$inspection.HostConfig.NanoCpus;
    mounts=@($inspection.Mounts | Select-Object Source,Destination,RW);
    protocol_sha256=(Get-FileHash -LiteralPath (Join-Path $lab 'data\protocol.json')).Hash;
    cases_sha256=(Get-FileHash -LiteralPath (Join-Path $lab 'data\cases.json')).Hash
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'container.json') -Encoding utf8
$container | Set-Content -LiteralPath (Join-Path $runDir 'container-id.txt')
$runDir | Write-Output
docker start $container | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Sandbox failed to start' }
Write-Output "STARTED $runName"
