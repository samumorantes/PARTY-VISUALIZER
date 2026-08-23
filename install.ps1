# FIESTA — Instalador silencioso para Windows
# Crea: carpeta en %LOCALAPPDATA%\FIESTA, acceso directo en Escritorio y Menú Inicio,
# tarea programada que auto-arranca el server al iniciar sesión, y abre la app.
# Uso:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

$src     = $PSScriptRoot
$appDir  = "$env:LOCALAPPDATA\FIESTA"
$pyExe   = "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe"
if (-not (Test-Path $pyExe)) { $pyExe = "pythonw.exe" }   # fallback al PATH

Write-Host "== FIESTA installer ==" -ForegroundColor Magenta

# 1) Copiar archivos de la app (sin token.json: cada usuario conecta su cuenta)
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Copy-Item "$src\server.py"          $appDir -Force
Copy-Item "$src\index.html"         $appDir -Force
Copy-Item "$src\fiesta.ico"         $appDir -Force
Copy-Item "$src\fiesta_launcher.py" $appDir -Force
Copy-Item "$src\CHANGELOG.md"       $appDir -Force -ErrorAction SilentlyContinue
Copy-Item "$src\README.md"          $appDir -Force -ErrorAction SilentlyContinue
if (Test-Path "$src\config.json") { Copy-Item "$src\config.json" $appDir -Force }
New-Item -ItemType Directory -Force -Path "$appDir\fonts" | Out-Null
Copy-Item "$src\fonts\*" "$appDir\fonts\" -Force
Write-Host "[1/5] Archivos copiados a $appDir"

# 2) Lanzador .cmd (doble clic = abrir app; el server lo levanta el launcher)
$cmd = @'
@echo off
start "" pythonw "%LOCALAPPDATA%\FIESTA\fiesta_launcher.py"
'@
Set-Content -Path "$env:LOCALAPPDATA\FIESTA\FIESTA.cmd" -Value $cmd -Encoding ASCII

# 3) Accesos directos con icono (Escritorio + Menú Inicio)
$ws = New-Object -ComObject WScript.Shell
foreach ($lnkPath in @("$env:USERPROFILE\Desktop\FIESTA.lnk", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\FIESTA.lnk")) {
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = "$appDir\FIESTA.cmd"
    $lnk.WorkingDirectory = $appDir
    $lnk.IconLocation = "$appDir\fiesta.ico,0"
    $lnk.Description = "FIESTA - Visualizador de letras en tiempo real"
    $lnk.Save()
}
Write-Host "[2/5] Accesos directos creados (Escritorio + Menu Inicio)"

# 4) Auto-arranque del servidor al iniciar sesion (tarea programada, sin ventana)
$taskName = "FIESTA-server"
schtasks /Create /F /SC ONLOGON /TN $taskName `
    /TR "pythonw.exe $appDir\server.py" /RL LIMITED 2>$null
if ($LASTEXITCODE -ne 0) {
    # fallback: carpeta Startup (siempre funciona)
    Copy-Item "$appDir\FIESTA.cmd" "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\FIESTA-server.cmd" -Force
}
Write-Host "[3/5] Auto-arranque configurado"

# 5) Desinstalador
$un = @'
@echo off
echo Desinstalando FIESTA...
schtasks /Delete /F /TN FIESTA-server 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FIESTA-server.cmd" 2>nul
del "%USERPROFILE%\Desktop\FIESTA.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\FIESTA.lnk" 2>nul
rmdir /s /q "%LOCALAPPDATA%\FIESTA"
echo FIESTA desinstalado.
pause
'@
Set-Content -Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Uninstall FIESTA.cmd" -Value $un -Encoding ASCII
Write-Host "[4/5] Desinstalador creado (Menu Inicio)"

Write-Host "[5/5] Listo. Abriendo FIESTA..." -ForegroundColor Green
Start-Process "$appDir\FIESTA.cmd"
