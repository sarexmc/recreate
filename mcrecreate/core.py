#!/usr/bin/env python3
"""
mcrecreate/core.py - Reconstruye un lugar real en Minecraft a partir de videos (links o archivos).

Pipeline: videos -> fotogramas -> COLMAP (SfM/MVS, todos los videos juntos)
          -> nube de puntos -> voxelizacion -> bloques por color -> .schem / .mcfunction

Requisitos:
  pip install numpy nbtlib plyfile yt-dlp
  ffmpeg y COLMAP instalados y en el PATH  (colmap.github.io)
  Sin GPU NVIDIA funciona en CPU (puntos dispersos + relleno de huecos).

Uso:
  python -m mcrecreate.core URL1 URL2 video3.mp4 --size 128 -o mundo
  python -m mcrecreate.core https://twitch.tv/canal --stream 600 -o mundo   # graba 10 min de un directo
  python -m mcrecreate.core --selftest          # prueba sin videos
"""
import argparse, subprocess, shutil, sys
from pathlib import Path
import numpy as np

# nombre del bloque -> color promedio RGB
PALETTE = {
    "white_concrete": (207, 213, 214), "light_gray_concrete": (125, 125, 115),
    "gray_concrete": (54, 57, 61), "black_concrete": (8, 10, 15),
    "brown_concrete": (96, 60, 32), "red_concrete": (142, 33, 33),
    "orange_concrete": (224, 97, 0), "yellow_concrete": (240, 175, 21),
    "lime_concrete": (94, 168, 24), "green_concrete": (73, 91, 36),
    "cyan_concrete": (21, 119, 136), "light_blue_concrete": (35, 137, 198),
    "blue_concrete": (44, 46, 143), "purple_concrete": (100, 32, 156),
    "magenta_concrete": (169, 48, 159), "pink_concrete": (213, 101, 142),
    "stone": (125, 125, 125), "dirt": (134, 96, 67), "grass_block": (106, 150, 60),
    "sand": (219, 207, 163), "oak_planks": (162, 130, 78),
    "spruce_planks": (114, 84, 48), "birch_planks": (192, 175, 121),
    "oak_log": (109, 85, 50), "cobblestone": (127, 127, 127),
    "bricks": (150, 97, 83), "netherrack": (97, 38, 38),
    "snow_block": (249, 254, 254), "oak_leaves": (60, 120, 30),
    "sandstone": (216, 203, 155), "terracotta": (152, 94, 67),
    "deepslate": (80, 80, 83), "gravel": (131, 127, 126), "clay": (160, 166, 179),
}
NAMES = list(PALETTE)


LOG = print  # la interfaz grafica reemplaza esto para mostrar el log


def run(cmd):
    cmd = list(map(str, cmd))
    LOG("$ " + " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in p.stdout:
        LOG(line.rstrip())
    if p.wait():
        raise subprocess.CalledProcessError(p.returncode, cmd)


# ---------- 1. videos -> fotogramas ----------
def get_frames(sources, work, every, stream_secs, max_frames, start="", end=""):
    frames = work / "images"
    frames.mkdir(parents=True, exist_ok=True)
    import re
    for t in (start, end):
        if t and not re.fullmatch(r"\d+(:\d{1,2}){0,2}", t):
            sys.exit(f"Tiempo invalido '{t}'. Usa el formato h:mm:ss (ej. 1:13:18)")
    for i, src in enumerate(sources):
        pre = []
        if src.startswith(("http://", "https://")):
            vid = work / f"video{i}.mp4"
            cmd = ["yt-dlp", "-f", "mp4/best", "--merge-output-format", "mp4", "-o", vid]
            if start or end:  # solo baja el tramo pedido (no el video completo)
                cmd += ["--download-sections", f"*{start or '0'}-{end or 'inf'}"]
            if stream_secs:  # directo: graba solo N segundos desde ahora
                cmd += ["--downloader", "ffmpeg", "--downloader-args", f"ffmpeg:-t {stream_secs}"]
            if not vid.exists():  # cache: no vuelve a descargar
                run(cmd + [src])
        else:
            vid = Path(src)
            if start: pre += ["-ss", start]
            if end: pre += ["-to", end]
        run(["ffmpeg", "-y", *pre, "-i", vid, "-vf", f"fps=1/{every}", "-q:v", "2",
             frames / f"v{i}_%04d.jpg"])
    # en CPU conviene limitar fotogramas: se reparten parejo entre todos los videos
    imgs = sorted(frames.glob("*.jpg"))
    if len(imgs) > max_frames:
        keep = set(np.linspace(0, len(imgs) - 1, max_frames).astype(int))
        for k, f in enumerate(imgs):
            if k not in keep:
                f.unlink()
    print(f"Fotogramas usados: {len(list(frames.glob('*.jpg')))}")
    return frames


# ---------- 2. COLMAP ----------
def gpu_flag(base, names, use_gpu):
    """COLMAP cambio el nombre de la opcion entre versiones: prueba ambos."""
    for n in names:
        try:
            return run(base + [n, "1" if use_gpu else "0"])
        except subprocess.CalledProcessError:
            continue
    sys.exit("COLMAP fallo. Revisa que este bien instalado.")


def reconstruct(work, frames, dense, multi):
    gpu = shutil.which("nvidia-smi") is not None
    if dense and not gpu:
        print("Sin GPU NVIDIA: se omite --dense (se usa reconstruccion dispersa en CPU).")
        dense = False
    db, sparse = work / "db.db", work / "sparse"
    sparse.mkdir(exist_ok=True)
    gpu_flag(["colmap", "feature_extractor", "--database_path", db, "--image_path", frames,
              "--SiftExtraction.max_num_features", "8000"],
             ["--SiftExtraction.use_gpu", "--FeatureExtraction.use_gpu"], gpu)
    if multi:   # varios videos: compara todo contra todo para unirlos
        gpu_flag(["colmap", "exhaustive_matcher", "--database_path", db],
                 ["--SiftMatching.use_gpu", "--FeatureMatching.use_gpu"], gpu)
    else:       # un solo video/stream: solo vecinos cercanos (mucho mas rapido en CPU)
        gpu_flag(["colmap", "sequential_matcher", "--database_path", db,
                  "--SequentialMatching.overlap", "15"],
                 ["--SiftMatching.use_gpu", "--FeatureMatching.use_gpu"], gpu)
    run(["colmap", "mapper", "--database_path", db, "--image_path", frames,
         "--output_path", sparse])
    model = sparse / "0"
    if not model.exists():
        sys.exit("COLMAP no logro reconstruir. Necesita movimiento de camara y solapamiento.")
    out = work / "cloud.ply"
    if dense:
        d = work / "dense"
        run(["colmap", "image_undistorter", "--image_path", frames, "--input_path", model,
             "--output_path", d])
        run(["colmap", "patch_match_stereo", "--workspace_path", d])
        run(["colmap", "stereo_fusion", "--workspace_path", d, "--output_path", out])
    else:
        run(["colmap", "model_converter", "--input_path", model, "--output_path", out,
             "--output_type", "PLY"])
    return out


# ---------- 3. nube de puntos -> voxeles ----------
def load_ply(path):
    from plyfile import PlyData
    v = PlyData.read(str(path))["vertex"]
    pts = np.stack([v["x"], v["y"], v["z"]], 1).astype(float)
    col = np.stack([v["red"], v["green"], v["blue"]], 1).astype(float)
    return pts, col


def orient(pts, up):
    """Pone el eje 'up' como eje vertical (Y de Minecraft)."""
    sign = -1 if up.startswith("-") else 1
    ax = {"x": 0, "y": 1, "z": 2}[up.lstrip("-")]
    order = [i for i in range(3) if i != ax]
    return np.stack([pts[:, order[0]], sign * pts[:, ax], pts[:, order[1]]], 1)


def voxelize(pts, col, size):
    # recorta valores atipicos (1%-99%) para ignorar puntos sueltos
    lo, hi = np.percentile(pts, 1, 0), np.percentile(pts, 99, 0)
    keep = np.all((pts >= lo) & (pts <= hi), 1)
    pts, col = pts[keep], col[keep]
    pts = pts - pts.min(0)
    idx = np.floor(pts / pts.max() * (size - 1)).astype(int)
    shape = idx.max(0) + 1
    flat = np.ravel_multi_index(idx.T, shape)
    uniq, inv = np.unique(flat, return_inverse=True)
    mean = np.zeros((len(uniq), 3))
    np.add.at(mean, inv, col)
    mean /= np.bincount(inv)[:, None]
    return np.array(np.unravel_index(uniq, shape)).T, mean, shape


def rgb2lab(rgb):
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[.4124, .3576, .1805], [.2126, .7152, .0722], [.0193, .1192, .9505]])
    xyz = (c @ m.T) / np.array([.95047, 1, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def to_blocks(colors):
    pal_lab = rgb2lab(np.array(list(PALETTE.values()), float))
    lab = rgb2lab(colors)
    d = ((lab[:, None, :] - pal_lab[None, :, :]) ** 2).sum(2)
    return d.argmin(1)


# ---------- 4. exportar ----------
def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def export_schem(path, vox, blk, shape):
    import nbtlib
    from nbtlib import tag
    W, H, L = int(shape[0]), int(shape[1]), int(shape[2])
    grid = np.zeros((H, L, W), int)  # 0 = aire
    grid[vox[:, 1], vox[:, 2], vox[:, 0]] = blk + 1
    pal = {"minecraft:air": tag.Int(0)}
    pal.update({f"minecraft:{n}": tag.Int(i + 1) for i, n in enumerate(NAMES)})
    data = b"".join(varint(int(v)) for v in grid.ravel())
    f = nbtlib.File({"Schematic": tag.Compound({
        "Version": tag.Int(2), "DataVersion": tag.Int(3955),
        "Width": tag.Short(W), "Height": tag.Short(H), "Length": tag.Short(L),
        "PaletteMax": tag.Int(len(pal)), "Palette": tag.Compound(pal),
        "BlockData": tag.ByteArray(np.frombuffer(data, np.int8)),
        "Offset": tag.IntArray([0, 0, 0])})}, gzipped=True)
    f.save(str(path))


def export_mcfunction(path, vox, blk):
    with open(path, "w") as f:
        for (x, y, z), b in zip(vox, blk):
            f.write(f"setblock ~{x} ~{y} ~{z} minecraft:{NAMES[b]}\n")


def fill_gaps(vox, vcol, shape, n):
    """Cierra huecos de una nube dispersa y pinta lo nuevo con el color del vecino mas cercano."""
    from scipy import ndimage as ndi
    p = n + 1
    occ = np.zeros(shape, bool); occ[tuple(vox.T)] = True
    cols = np.zeros((*shape, 3)); cols[tuple(vox.T)] = vcol
    st = ndi.generate_binary_structure(3, 2)
    closed = ndi.binary_closing(np.pad(occ, p), st, iterations=n)[p:-p, p:-p, p:-p]
    _, ind = ndi.distance_transform_edt(~occ, return_indices=True)
    new = closed & ~occ
    allv = np.argwhere(closed)
    allc = cols[ind[0][closed], ind[1][closed], ind[2][closed]]
    return allv, allc


def finish(pts, col, size, out, fill=1):
    vox, vcol, shape = voxelize(pts, col, size)
    if fill > 0:
        try:
            vox, vcol = fill_gaps(vox, vcol, shape, fill)
        except ImportError:
            print("Instala scipy para rellenar huecos: pip install scipy")
    blk = to_blocks(vcol)
    export_schem(f"{out}.schem", vox, blk, shape)
    export_mcfunction(f"{out}.mcfunction", vox, blk)
    print(f"\nListo: {len(vox)} bloques, tamano {tuple(int(s) for s in shape)} (X,Y,Z)")
    print(f"  {out}.schem        -> WorldEdit: //schem load / //paste   (o Litematica)")
    print(f"  {out}.mcfunction   -> datapack; antes: /gamerule maxCommandChainLength 1000000")


def selftest(out):
    rng = np.random.default_rng(0)
    g = np.c_[rng.uniform(-1, 1, (6000, 2)), np.zeros(6000)][:, [0, 2, 1]]
    gc = np.tile([100, 160, 60], (6000, 1)) + rng.normal(0, 8, (6000, 3))
    s = rng.normal(size=(6000, 3)); s = s / np.linalg.norm(s, axis=1)[:, None] * .6
    s[:, 1] = np.abs(s[:, 1]) + .05
    sc = np.tile([200, 40, 40], (6000, 1)) + rng.normal(0, 8, (6000, 3))
    finish(np.vstack([g, s]), np.clip(np.vstack([gc, sc]), 0, 255), 48, out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("sources", nargs="*", help="links o archivos de video")
    ap.add_argument("-o", "--out", default="mundo")
    ap.add_argument("--size", type=int, default=128, help="bloques en la dimension mas grande")
    ap.add_argument("--every", type=float, default=1.0, help="segundos entre fotogramas")
    ap.add_argument("--dense", action="store_true", help="reconstruccion densa (solo con GPU NVIDIA)")
    ap.add_argument("--stream", type=int, default=0, metavar="SEG",
                    help="si el link es un directo, graba SEG segundos (ej. 600)")
    ap.add_argument("--start", default="", help="inicio del tramo, h:mm:ss")
    ap.add_argument("--end", default="", help="fin del tramo, h:mm:ss")
    ap.add_argument("--max-frames", type=int, default=150, help="tope de fotogramas (CPU: 100-200)")
    ap.add_argument("--fill", type=int, default=1, help="relleno de huecos (0=off, 1-3)")
    ap.add_argument("--up", default="-y", help="eje vertical de COLMAP: x,y,z,-x,-y,-z")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.out)
    if not a.sources:
        ap.error("pasa al menos un link/video, o usa --selftest")
    for tool in ("ffmpeg", "colmap"):
        if not shutil.which(tool):
            sys.exit(f"Falta '{tool}' en el PATH.")
    work = Path(a.out + "_work"); work.mkdir(exist_ok=True)
    frames = get_frames(a.sources, work, a.every, a.stream, a.max_frames, a.start, a.end)
    ply = reconstruct(work, frames, a.dense, len(a.sources) > 1)
    pts, col = load_ply(ply)
    finish(orient(pts, a.up), col, a.size, a.out, a.fill)


if __name__ == "__main__":
    main()
