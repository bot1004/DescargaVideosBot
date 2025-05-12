# Configurar variables de entorno
$Env:TELEGRAM_TOKEN = "8121623575:AAH798Us_OvXfiejYhURKDfxA3m4yXWe3PM"
$Env:GOOGLE_CREDS_PATH = "./credentials/pytube-uploader-key.json"
$Env:GDRIVE_FOLDER_ID = "197qt1E5WzZYHv3mNLgtVvjhujyCTgVUM"

# Mostrar estado de las variables
Write-Host "=== Configuracion de variables de entorno ==="
Write-Host "[OK] TELEGRAM_TOKEN: Configurado"
Write-Host "[OK] GOOGLE_CREDS_PATH: $Env:GOOGLE_CREDS_PATH"
Write-Host "[OK] GDRIVE_FOLDER_ID: $Env:GDRIVE_FOLDER_ID"

# Iniciar el bot
Write-Host "`n=== Iniciando bot... ==="
python main.py
