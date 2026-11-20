# ⛏ Minecraft Recreator

Convierte **videos y streams** en construcciones de Minecraft. Pega uno o varios links, mira una **vista previa 3D** de lo que reconstruyó cada uno, corrige y exporta a `.schem` (WorldEdit / Litematica) o `.mcfunction`.

## Cómo funciona

1. `yt-dlp` descarga el link (o graba N segundos de un directo) y `ffmpeg` extrae fotogramas.
2. **COLMAP** (fotogrametría) reconstruye la escena 3D. Con varios links se reconstruyen juntos y los ángulos se complementan.
3. La nube de puntos se **voxeliza** y se rellenan huecos (importante si no tienes GPU).
4. Cada voxel se convierte en el **bloque con el color más cercano** (espacio Lab).

## Uso (Windows, sin instalar Python)

Descarga `MinecraftRecreator-windows.zip` desde **Releases**, descomprime y abre `MinecraftRecreator.exe`. Ya incluye `tools/` con ffmpeg, yt-dlp y COLMAP.

## Desde el código

```bash
pip install -r requirements.txt
# Windows: scripts\setup_tools.bat   (en Linux/macOS instala ffmpeg, yt-dlp y colmap con tu gestor)
python run.py
```

Para generar el `.exe` tú mismo: `scripts\build_exe.bat`. En GitHub, crea un tag (`git tag v1.0.0 && git push --tags`) y *Actions* publica el release automáticamente.

CLI sin interfaz: `python -m mcrecreate.core LINK1 LINK2 --size 128 -o mundo`

## Flujo recomendado

1. **+ Añadir** link → **▶ Procesar**: ves qué reconstruyó ese link.
2. Si sale girado, cambia el **eje vertical** (no reprocesa). Ajusta **tamaño** y **relleno** al vuelo.
3. Descarta con el ✓ los links que salgan mal y pulsa **Combinar**.
4. **Exportar**: `//schem load nombre` y `//paste` (WorldEdit), o `.mcfunction` en un datapack (antes: `/gamerule maxCommandChainLength 1000000`).

## Para buenos resultados

- La cámara debe **moverse** por el lugar con mucho solapamiento (caminar alrededor, recorrer). Cámara fija, cortes de edición o un streamer hablando no funcionan.
- Sin GPU NVIDIA usa reconstrucción dispersa + relleno de huecos (más aproximada). Con GPU activa **Densa**.
- Prueba primero con `Máx. fotogramas` bajo (60-80) y tamaño 64.

## Limitaciones

Solo bloques de superficie, paleta de ~35 bloques (editable en `core.PALETTE`), la escala es relativa (el tamaño se define por la dimensión mayor).

## Aviso

Respeta los derechos de autor y los términos de las plataformas de las que descargues video. Úsalo con contenido propio o con permiso.

Licencia MIT.
