"""Benchmark: python -m ai.benchmark --images some_photos_dir [--runs 3]
Measures load time, inference time per model, memory, and sequential vs parallel total time."""
import argparse, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1048576
    except Exception:
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            return float('nan')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--images', required=True); ap.add_argument('--runs', type=int, default=3)
    a = ap.parse_args()
    from ai import manager as M
    imgs = [os.path.join(a.images, f) for f in sorted(os.listdir(a.images)) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))][:10]
    if not imgs:
        sys.exit('no images found')
    base = rss_mb()
    print(f'memory before loading: {base:.0f} MB')
    for d in M.get_detectors({}):
        t = time.time(); ok = d.load()
        print(f'  load {d.display_name:<16} {"ok" if ok else "FAILED: " + str(d.error)}  {time.time() - t:.2f}s   rss {rss_mb():.0f} MB')
    print(f'memory after loading all models: {rss_mb():.0f} MB')
    res = {}
    for mode, par in (('sequential', False), ('parallel', True)):
        times = []
        for _ in range(a.runs):
            for im in imgs:
                t = time.time(); M.analyze(im, {'AI_PARALLEL': par}); times.append(time.time() - t)
        res[mode] = sum(times) / len(times)
        print(f'{mode:<11} mean {res[mode] * 1000:.0f} ms per photo   (peak rss {rss_mb():.0f} MB)')
    faster = (res['sequential'] - res['parallel']) / res['sequential'] * 100
    print(f'\nparallel is {faster:+.0f}% vs sequential.',
          'Consider AI_PARALLEL=True.' if faster > 25 else 'Keep AI_PARALLEL=False (default): little gain, simpler and lighter on memory.')

if __name__ == '__main__':
    main()
