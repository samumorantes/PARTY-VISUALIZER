' Fiesta Visualizer — arranque OCULTO + watchdog (si se cae, se reinicia en 3s)
' Registrado en el Programador de tareas al iniciar sesión.
Set ws = CreateObject("WScript.Shell")
proj = "C:\Users\moran\fiesta-visualizer"
logf = proj & "\fiesta.log"
py = "C:\Users\moran\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
cmdline = "cmd /c cd /d """ & proj & """ && """ & py & """ server.py >> """ & logf & """ 2>&1"
Do
  ws.Run cmdline, 0, True
  WScript.Sleep 3000
Loop
