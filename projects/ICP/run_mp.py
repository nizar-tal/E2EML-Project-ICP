import os, json, time
os.environ.setdefault("EASYOCR_GPU", "1")
import multiprocessing as mp
from datasets import load_dataset
from image import process_image
from ocr import run_ocr
from metrics import score_ocr

N_PROC = 40

print("loading dataset...", flush=True)
ds = load_dataset("lansinuote/ocr_id_card", split="train")
N = len(ds); print("images:", N, flush=True)

_raw = open("pipeline_configs.json").read()
_raw = "\n".join(l for l in _raw.splitlines() if not l.strip().startswith("//"))
configs = json.loads(_raw)

_current = None
def _init(cfg):
    global _current; _current = cfg
def _score(i):
    row = ds[i]
    text = run_ocr(process_image(row["image"], _current), _current["ocr"])
    r = score_ocr(text, row["ocr"])
    return r["n_fields"], r["n_exact"]
def run_config(cfg):
    start = time.perf_counter()
    if cfg["ocr"] == "tesseract":
        with mp.Pool(N_PROC, initializer=_init, initargs=(cfg,)) as pool:
            res = pool.map(_score, range(N), chunksize=50)
    else:
        _init(cfg); res = [_score(i) for i in range(N)]
    nf = sum(a for a,_ in res); ne = sum(b for _,b in res)
    el = time.perf_counter() - start
    return cfg["name"], cfg["ocr"], (ne/nf if nf else 0.0), el/N, el

if __name__ == "__main__":
    order = sorted(configs, key=lambda c: 0 if c["ocr"]=="tesseract" else 1)
    rows = []
    for cfg in order:
        r = run_config(cfg); rows.append(r)
        print(f"{r[0]:<30} {r[1]:<10} recall={r[2]:.3f} {r[3]:.4f}s/img {r[4]:.1f}s", flush=True)
    with open("results_full.csv","w") as f:
        f.write("config,engine,recall,s_per_img,total_s\n")
        for r in rows: f.write(f"{r[0]},{r[1]},{r[2]:.4f},{r[3]:.4f},{r[4]:.1f}\n")
    print("DONE -> results_full.csv", flush=True)
