$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $projectDir "venv"
$python = Join-Path $venvDir "Scripts\python.exe"
$scriptsDir = Join-Path $venvDir "Scripts"
$logFile = Join-Path $projectDir "reclip-launch-$PID.log"
$url = "http://127.0.0.1:8899"

Set-Location $projectDir
Start-Transcript -Path $logFile -Append | Out-Null

try {
    try {
        Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2 | Out-Null
        Write-Host "ReClip is already running. Opening it now..."
        Start-Process $url
        return
    } catch {
        # No existing server is listening, so continue with startup.
    }

    if (-not (Test-Path $python)) {
        Write-Host "Setting up ReClip for the first run..."
        py -m venv $venvDir
    }

    $env:PATH = "$scriptsDir;$env:PATH"
    $env:PORT = "8899"

    Write-Host "Checking ReClip dependencies..."
    & $python -m pip install --disable-pip-version-check --quiet -r (Join-Path $projectDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install ReClip's Python dependencies."
    }

    $ffmpeg = Join-Path $scriptsDir "ffmpeg.exe"
    if (-not (Test-Path $ffmpeg)) {
        $bundledFfmpeg = & $python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
        Copy-Item -LiteralPath $bundledFfmpeg.Trim() -Destination $ffmpeg
    }

    Write-Host ""
    Write-Host "Starting ReClip at $url"
    Write-Host "Keep this window open while using ReClip."
    Write-Host ""

    $browserOpener = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-Command", "& { for (`$i = 0; `$i -lt 30; `$i++) { try { Invoke-WebRequest -UseBasicParsing '$url' -TimeoutSec 1 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Milliseconds 500 } } }"
    ) -WindowStyle Hidden -PassThru

    & $python (Join-Path $projectDir "app.py")
    if ($LASTEXITCODE -ne 0) {
        throw "ReClip stopped with exit code $LASTEXITCODE."
    }
} catch {
    Write-Host ""
    Write-Host "ReClip could not start:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Details were saved to: $logFile"
    Read-Host "Press Enter to close"
} finally {
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}
