param([ValidateSet('Prepare','Compare')][string]$Stage='Prepare', [Parameter(Mandatory=$true)][string]$PrimaryRun)
$ErrorActionPreference='Stop'
$lab=$PSScriptRoot
$research=Join-Path $lab 'results\delayed-research'
$primary=(Resolve-Path -LiteralPath $PrimaryRun).Path
$image=docker image inspect francis-pain-axis-sandbox:pilot-20261003 --format '{{.Id}}'
if($LASTEXITCODE -ne 0){throw 'Sandbox image missing'}
function Invoke-Lab([string]$Mode){
    $name='pain-axis-research-'+$Mode+'-'+(Get-Date -Format 'HHmmss')
    $container=docker create --name $name --network=none --read-only --user=65534:65534 --cap-drop=ALL --security-opt=no-new-privileges --pids-limit=128 --memory=12g --memory-swap=12g --cpus=6 --tmpfs=/tmp:rw,noexec,nosuid,size=256m --shm-size=256m --mount "type=bind,source=$(Join-Path $lab 'src'),target=/app,readonly" --mount "type=bind,source=$(Join-Path $lab 'data'),target=/data,readonly" --mount "type=bind,source=$(Join-Path $lab 'model'),target=/model,readonly" --mount "type=bind,source=$research,target=/research,readonly" --mount "type=bind,source=$primary,target=/primary,readonly" --mount "type=bind,source=$research,target=/results" --entrypoint python $image /app/research.py $Mode
    if($LASTEXITCODE -ne 0){throw 'Container creation failed'}
    docker start -a $container
    $exitCode=docker inspect $container --format '{{.State.ExitCode}}'
    [pscustomobject]@{mode=$Mode;container=$container;image=$image;network='none';read_only=$true;exit_code=$exitCode} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $research ($Mode+'-container.json'))
    if($exitCode -ne '0'){throw "Research stage $Mode failed"}
}
if($Stage -eq 'Compare'){
    if(-not(Test-Path -LiteralPath (Join-Path $research 'first-answer.json'))){throw 'First answer is missing'}
    Invoke-Lab 'compare'
    exit
}
if(Test-Path -LiteralPath $research){throw 'Research run exists; refusing overwrite'}
New-Item -ItemType Directory -Path $research | Out-Null
Invoke-Lab 'query'
$q=Get-Content -LiteralPath (Join-Path $research 'query.json') -Raw | ConvertFrom-Json
if(-not $q.complete){throw 'Search query did not finish'}
$query=$q.text.Trim()
if($query.Length -gt 500){throw 'Search query too long'}
$searchUri='https://learn.microsoft.com/api/search?search='+[uri]::EscapeDataString($query)+'&locale=en-us&$top=5'
$search=Invoke-RestMethod -Uri $searchUri -TimeoutSec 30
$search | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $research 'search-results.json') -Encoding utf8
# Restrict reads to official Edge documentation. The broker supplies the exact policy
# page when Microsoft's search index returns only the broad policy index.
$urls=@('https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/ExperimentationAndConfigurationServiceControl')
$sources=@()
foreach($url in $urls){
    $page=Invoke-WebRequest -Uri $url -TimeoutSec 30
    $html=$page.Content
    $start=$html.IndexOf('id="description"')
    $end=$html.IndexOf('id="supported-features"',$start)
    if($start -lt 0 -or $end -le $start){throw 'Policy page shape changed'}
    $fragment=$html.Substring($start,$end-$start)
    $plain=[System.Net.WebUtility]::HtmlDecode([regex]::Replace($fragment,'<[^>]+>',' '))
    $plain=[regex]::Replace($plain,'\s+',' ').Trim()
    $sources += [pscustomobject]@{url=$url;text=$plain;retrieved_utc=[DateTime]::UtcNow.ToString('o');selection='Constrained broker selected exact policy page after official search'}
}
$sources | ConvertTo-Json -Depth 4 -AsArray | Set-Content -LiteralPath (Join-Path $research 'sources.json') -Encoding utf8
[pscustomobject]@{query=$query;search_endpoint=$searchUri;read_urls=$urls;network_owner='Host read-only documentation broker';model_network='none';note='This tests assisted retrieval, not unrestricted autonomous browsing'} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $research 'tool-trace.json') -Encoding utf8
Invoke-Lab 'answer'
