@echo off
rem Descarga yt-dlp, ffmpeg y COLMAP (sin CUDA) en .\tools
if not exist tools mkdir tools
echo Descargando yt-dlp...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe -OutFile tools\yt-dlp.exe"
echo Descargando ffmpeg...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile tools\ffmpeg.zip; Expand-Archive tools\ffmpeg.zip tools\ff_tmp -Force; Get-ChildItem tools\ff_tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1 | Copy-Item -Destination tools\ffmpeg.exe; Remove-Item tools\ff_tmp,tools\ffmpeg.zip -Recurse -Force"
echo Descargando COLMAP...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest https://github.com/colmap/colmap/releases/latest/download/colmap-x64-windows-nocuda.zip -OutFile tools\colmap.zip; Expand-Archive tools\colmap.zip tools\colmap -Force; Remove-Item tools\colmap.zip"
echo Si COLMAP fallo, bajalo de github.com/colmap/colmap/releases y descomprimelo en tools\colmap
if not defined CI pause
