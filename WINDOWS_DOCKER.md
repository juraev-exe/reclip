# Run ReClip On Windows With One Click

This project now has a Docker-based Windows launcher. Docker is recommended on Windows because ReClip needs `ffmpeg`, and the Docker image installs it automatically.

## First Time Setup

1. Install and open Docker Desktop.
2. Double-click `start-reclip-docker.bat`.
3. ReClip will open at <http://localhost:8899>.

The first run can take a few minutes because Docker builds the local image.

## Create A Desktop Shortcut

From PowerShell in this folder, run:

```powershell
.\create-desktop-shortcut.ps1
```

Then use the new `Start ReClip` shortcut on your Desktop.

If PowerShell blocks scripts on your machine, run this instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\create-desktop-shortcut.ps1
```

## Stop ReClip

Double-click `stop-reclip-docker.bat`.

## Where Downloads Go

Downloaded files are saved in this project folder:

```text
downloads
```
