from .core import audit, generate, load_gray, render_png, save_svg


def main() -> None:
    import sys

    img = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/eric_cropped.jpg"
    mode = sys.argv[2] if len(sys.argv) > 2 else "radiating"

    gray = load_gray(img, max_side=500)
    h, w = gray.shape
    seed = (w // 2, int(h * 0.22))

    polys, field = generate(img, mode=mode, seed_xy=seed, max_side=500)
    print(f"Generated {len(polys)} polylines in {mode!r} mode.")
    audit(polys, w, h)

    render_png(polys, f"/mnt/user-data/outputs/demo_{mode}.png", w, h)
    save_svg(polys, f"/mnt/user-data/outputs/demo_{mode}.svg", w, h)
    print(f"Saved PNG + SVG to /mnt/user-data/outputs/demo_{mode}.*")


if __name__ == "__main__":
    main()
