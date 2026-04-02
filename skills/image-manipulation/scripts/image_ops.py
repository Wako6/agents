#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def require_magick() -> str:
    magick = shutil.which("magick")
    if not magick:
        raise SystemExit("ImageMagick `magick` command not found in PATH.")
    return magick


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def run_magick(args: list[str]) -> None:
    subprocess.run(args, check=True)


def add_common_output_args(command: list[str], output: Path, quality: int | None, background: str | None) -> list[str]:
    suffix = output.suffix.lower()
    if suffix in {".jpg", ".jpeg"} and background:
        command.extend(["-background", background, "-alpha", "remove", "-alpha", "off"])
    if quality is not None:
        command.extend(["-quality", str(quality)])
    command.append(str(output))
    return command


def parse_size(raw: str) -> tuple[int, int]:
    try:
        width_raw, height_raw = raw.lower().split("x", 1)
        return int(width_raw), int(height_raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Size must use WIDTHxHEIGHT, for example 480x320.") from exc


def resize_command(magick: str, args: argparse.Namespace) -> list[str]:
    base = [magick, str(args.input), "-auto-orient", "-strip"]
    geometry = f"{args.width}x{args.height}"
    if args.mode == "fit":
        base.extend(["-resize", geometry])
    elif args.mode == "fill":
        base.extend(["-resize", f"{geometry}^", "-gravity", "center", "-extent", geometry])
    else:
        base.extend(["-resize", f"{geometry}!"])
    return add_common_output_args(base, args.output, args.quality, args.background)


def crop_command(magick: str, args: argparse.Namespace) -> list[str]:
    base = [
        magick,
        str(args.input),
        "-auto-orient",
        "-strip",
        "-crop",
        f"{args.width}x{args.height}+{args.x}+{args.y}",
        "+repage",
    ]
    return add_common_output_args(base, args.output, args.quality, args.background)


def convert_command(magick: str, args: argparse.Namespace) -> list[str]:
    base = [magick, str(args.input), "-auto-orient", "-strip"]
    return add_common_output_args(base, args.output, args.quality, args.background)


def thumbnail_command(magick: str, args: argparse.Namespace) -> list[str]:
    width, height = parse_size(args.size)
    ns = argparse.Namespace(
        input=args.input,
        output=args.output,
        width=width,
        height=height,
        mode=args.mode,
        quality=args.quality,
        background=args.background,
    )
    return resize_command(magick, ns)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Image helper for crop, resize, convert and thumbnail generation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resize = subparsers.add_parser("resize", help="Resize an image into a target box.")
    resize.add_argument("input", type=Path)
    resize.add_argument("output", type=Path)
    resize.add_argument("--width", type=int, required=True)
    resize.add_argument("--height", type=int, required=True)
    resize.add_argument("--mode", choices=["fit", "fill", "stretch"], default="fit")
    resize.add_argument("--quality", type=int)
    resize.add_argument("--background")

    crop = subparsers.add_parser("crop", help="Crop an image using explicit coordinates.")
    crop.add_argument("input", type=Path)
    crop.add_argument("output", type=Path)
    crop.add_argument("--width", type=int, required=True)
    crop.add_argument("--height", type=int, required=True)
    crop.add_argument("--x", type=int, required=True)
    crop.add_argument("--y", type=int, required=True)
    crop.add_argument("--quality", type=int)
    crop.add_argument("--background")

    convert = subparsers.add_parser("convert", help="Convert an image to another format.")
    convert.add_argument("input", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--quality", type=int)
    convert.add_argument("--background")

    thumbnail = subparsers.add_parser("thumbnail", help="Generate a thumbnail using a target size.")
    thumbnail.add_argument("input", type=Path)
    thumbnail.add_argument("output", type=Path)
    thumbnail.add_argument("--size", required=True, help="WIDTHxHEIGHT, for example 480x320.")
    thumbnail.add_argument("--mode", choices=["fit", "fill", "stretch"], default="fill")
    thumbnail.add_argument("--quality", type=int)
    thumbnail.add_argument("--background")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    magick = require_magick()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    ensure_parent(args.output)

    builders = {
        "resize": resize_command,
        "crop": crop_command,
        "convert": convert_command,
        "thumbnail": thumbnail_command,
    }
    command = builders[args.command](magick, args)
    run_magick(command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
