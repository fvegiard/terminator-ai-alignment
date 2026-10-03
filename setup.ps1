$ErrorActionPreference='Stop'
$lab=$PSScriptRoot
$modelDir=Join-Path $lab 'model'
if(Test-Path -LiteralPath $modelDir){throw 'Model directory already exists. Preserve it or use a fresh checkout.'}
New-Item -ItemType Directory -Path $modelDir | Out-Null
$manifest=Get-Content -LiteralPath (Join-Path $lab 'manifest.json') -Raw | ConvertFrom-Json
foreach($file in @('LICENSE','config.json','generation_config.json','merges.txt','model.safetensors','tokenizer.json','tokenizer_config.json','vocab.json')){
    Invoke-WebRequest -Uri "https://huggingface.co/$($manifest.model)/resolve/$($manifest.revision)/$file" -OutFile (Join-Path $modelDir $file)
}
docker build --tag francis-pain-axis-sandbox:pilot-20261003 (Join-Path $lab 'build')
if($LASTEXITCODE -ne 0){throw 'Container build failed'}
Write-Output 'Setup complete. Run .\run-sandbox.ps1 for a new isolated pilot.'
