@echo off
rem Genera dist\MinecraftRecreator.exe (ejecutar desde la raiz del repo)
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller --noconfirm --onefile --noconsole --name MinecraftRecreator --add-data "mcrecreate/web;mcrecreate/web" --collect-all webview run.py
echo Listo: dist\MinecraftRecreator.exe  (copia la carpeta tools junto al .exe)
if not defined CI pause
