#!/usr/bin/env python
import argparse
import asyncio
import logging
import sys
import os
import numpy as np

from catprinter import logger
from catprinter import cmds
from catprinter.ble import run_ble
from catprinter.img import read_img, show_preview


def parse_args():
    args = argparse.ArgumentParser(
        description="Prints an image on your MXW01 thermal cat printer"
    )
    args.add_argument("filename", type=str)
    args.add_argument(
        "-l",
        "--log-level",
        type=str,
        choices=["debug", "info", "warn", "error"],
        default="info",
    )
    args.add_argument(
        "-b",
        "--dithering-algo",
        type=str,
        choices=["mean-threshold", "floyd-steinberg", "atkinson", "halftone", "none"],
        default="floyd-steinberg",
        help=f"Which image binarization algorithm to use. If 'none' is used, no binarization will be used. In this case the image has to have a width of {cmds.PRINTER_WIDTH_PIXELS} px.",
    )
    args.add_argument(
        "-s",
        "--show-preview",
        action="store_true",
        help="If set, displays the final image and asks the user for confirmation before printing.",
    )
    args.add_argument(
        "-d",
        "--device",
        type=str,
        default="",
        help=(
            "The printer's Bluetooth Low Energy (BLE) address "
            "(MAC address on Linux; UUID on macOS) "
            'or advertisement name (e.g.: "MXW01"). '
            "If omitted, the the script will try to auto discover "
            "the printer based on its advertised BLE services."
        ),
    )
    args.add_argument(
        "-i",
        "--intensity",
        type=lambda x: int(x, 0),
        default=0x5D,
        help="Print intensity/energy byte (0x00-0xFF, default 0x5D). Higher values generally produce darker prints. Accepts hex (0xNN) or decimal.",
    )
    args.add_argument(
        "--top-first",
        action="store_true",
        help="Print the image top-first. By default, the image is rotated 180 degrees to print right-side-up.",
    )
    return args.parse_args()


def configure_logger(log_level):
    logger.setLevel(log_level)
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(log_level)
    logger.addHandler(h)


def main():
    args = parse_args()

    log_level = getattr(logging, args.log_level.upper())
    configure_logger(log_level)

    filename = args.filename
    if not os.path.exists(filename):
        logger.info("🛑 File not found. Exiting.")
        return

    try:
        bin_img_bool = read_img(
            args.filename,
            cmds.PRINTER_WIDTH_PIXELS,
            args.dithering_algo,
        )
        logger.info(f"✅ Read image: {bin_img_bool.shape} (h, w) pixels")

        # Preview the image before potential rotation
        if args.show_preview:
            preview_img_uint8 = (~bin_img_bool).astype(np.uint8) * 255
            show_preview(preview_img_uint8)

        # Rotate image 180 degrees unless --top-first is specified
        if not args.top_first:
            logger.info("🔄 Rotating image 180 degrees (to print the bottom first).")
            bin_img_bool = np.rot90(bin_img_bool, k=2)
        else:
            logger.info("ℹ️  Printing image top-first as requested.")
    except RuntimeError as e:
        logger.error(f"🛑 {e}")
        return
    except Exception as e:
        logger.error(f"🛑 Unexpected error during image processing: {e}", exc_info=True)
        return

    try:
        logger.info("Preparing image data buffer for MXW01...")
        image_data_buffer = cmds.prepare_image_data_buffer(bin_img_bool)
        logger.info(
            f"✅ Generated MXW01 image data buffer: {len(image_data_buffer)} bytes"
        )

        asyncio.run(
            run_ble(image_data_buffer, device=args.device, intensity=args.intensity)
        )

    except ValueError as e:
        logger.error(f"🛑 Error preparing image buffer: {e}")
        return
    except Exception as e:
        logger.error(
            f"🛑 Unexpected error during command prep or BLE execution: {e}",
            exc_info=True,
        )
        return


if __name__ == "__main__":
    main()
