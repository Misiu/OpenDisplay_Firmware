#!/usr/bin/env python3
"""
OpenDisplay Bootloader Update Tool

Updates the Adafruit nRF52 bootloader on XIAO nRF52840 (Sense) boards to fix
broken OTA DFU support (e.g., EN04 boards shipped with a buggy bootloader).

Uses Serial DFU via adafruit-nrfutil, which works on ALL bootloader versions
including very old/broken ones. The .zip DFU package includes both the
bootloader and the SoftDevice for a complete update.

Requirements:
  - Python 3.7+
  - requests library (pip install requests)
  - adafruit-nrfutil (pip install adafruit-nrfutil)
  - USB cable connected to the XIAO nRF52840 board

Usage:
  python update_bootloader.py
  python update_bootloader.py --board standard             # XIAO nRF52840 (non-Sense)
  python update_bootloader.py --port /dev/ttyACM0          # Specify serial port
  python update_bootloader.py --pkg /path/to/bootloader.zip  # Use local DFU package

References:
  https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader
  https://github.com/adafruit/Adafruit_nRF52_Bootloader
"""

import argparse
import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile

GITHUB_API_URL = "https://api.github.com/repos/adafruit/Adafruit_nRF52_Bootloader/releases/latest"

# Board name patterns in GitHub release assets
BOARD_ASSET_NAMES = {
    "sense": "xiao_nrf52840_ble_sense_bootloader",
    "standard": "xiao_nrf52840_ble_bootloader",
}


def print_header():
    print()
    print("=" * 60)
    print("  OpenDisplay Bootloader Update Tool")
    print("  Fixes broken OTA DFU on EN04 and similar boards")
    print("=" * 60)
    print()


def print_step(step_num, message):
    print(f"\n  Step {step_num}: {message}")
    print("  " + "-" * 50)


# ---------------------------------------------------------------------------
# GitHub release download
# ---------------------------------------------------------------------------

def download_dfu_package(board_type, dest_dir):
    """Download the .zip DFU package (bootloader + SoftDevice) from GitHub."""
    try:
        import requests
    except ImportError:
        print("\n  ERROR: 'requests' library not found.")
        print("  Install it with: pip install requests")
        sys.exit(1)

    headers = {"Accept": "application/vnd.github+json"}
    # Support optional GitHub token to avoid rate limits (60 req/hr unauthenticated)
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    print("  Fetching latest release from GitHub...")
    try:
        resp = requests.get(GITHUB_API_URL, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"\n  ERROR: Failed to fetch release info: {e}")
        print("  Tip: Set GITHUB_TOKEN env var if you hit rate limits.")
        sys.exit(1)

    release = resp.json()
    tag = release.get("tag_name", "unknown")
    print(f"  Latest bootloader version: {tag}")

    # Find the .zip DFU package — includes both bootloader + SoftDevice,
    # safe for updating from any bootloader version
    board_name = BOARD_ASSET_NAMES.get(board_type, "")
    asset_url = None
    asset_name = None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if board_name in name and name.endswith(".zip"):
            asset_url = asset.get("browser_download_url")
            asset_name = name
            break

    if not asset_url:
        print(f"\n  ERROR: No .zip asset found for '{board_name}'")
        print("  Available XIAO assets:")
        for asset in release.get("assets", []):
            if "xiao" in asset.get("name", "").lower():
                print(f"    - {asset['name']}")
        sys.exit(1)

    print(f"  Downloading: {asset_name}")
    try:
        resp = requests.get(asset_url, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"\n  ERROR: Download failed: {e}")
        sys.exit(1)

    dest_path = os.path.join(dest_dir, asset_name)
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    print(f"  Downloaded: {len(resp.content) / 1024:.1f} KB")
    return dest_path


# ---------------------------------------------------------------------------
# Serial port detection
# ---------------------------------------------------------------------------

def find_serial_ports():
    """Find likely nRF52840 serial ports."""
    system = platform.system()
    ports = []

    if system == "Linux":
        # ttyACM* is the typical CDC-ACM serial port for nRF52840
        for dev in sorted(glob.glob("/dev/ttyACM*")):
            ports.append(dev)
    elif system == "Darwin":
        for dev in sorted(glob.glob("/dev/cu.usbmodem*")):
            ports.append(dev)
    elif system == "Windows":
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                if "nRF" in (p.description or "") or "Bluefruit" in (p.description or ""):
                    ports.append(p.device)
            if not ports:
                for p in serial.tools.list_ports.comports():
                    ports.append(p.device)
        except ImportError:
            print("  Note: Install pyserial for automatic COM port detection")
            print("        pip install pyserial")

    return ports


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Update the Adafruit nRF52 bootloader on XIAO nRF52840 boards via Serial DFU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Uses adafruit-nrfutil Serial DFU to flash the bootloader + SoftDevice.
Works on ALL bootloader versions including very old/broken ones.

examples:
  %(prog)s                                    # Auto-detect port
  %(prog)s --port /dev/ttyACM0                # Specify serial port
  %(prog)s --board standard                   # Non-Sense XIAO variant
  %(prog)s --pkg bootloader.zip               # Use local DFU package
""",
    )
    parser.add_argument(
        "--board",
        choices=["sense", "standard"],
        default="sense",
        help="Board variant (default: sense)",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=None,
        help="Serial port (e.g., /dev/ttyACM0, COM3). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--pkg",
        type=str,
        default=None,
        help="Path to a local .zip DFU package (skips download)",
    )
    args = parser.parse_args()

    print_header()

    # Step 1: Check prerequisites
    print_step(1, "Checking prerequisites")
    try:
        result = subprocess.run(
            ["adafruit-nrfutil", "version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  adafruit-nrfutil: {result.stdout.strip()}")
        else:
            raise FileNotFoundError
    except (FileNotFoundError, Exception):
        print("\n  ERROR: adafruit-nrfutil not found.")
        print("  Install it with: pip install adafruit-nrfutil")
        sys.exit(1)

    # Step 2: Get or download the DFU package
    print_step(2, "Preparing bootloader DFU package")
    tmp_dir = None
    if args.pkg:
        if not os.path.exists(args.pkg):
            print(f"  ERROR: File not found: {args.pkg}")
            sys.exit(1)
        pkg_path = args.pkg
        print(f"  Using local file: {pkg_path}")
    else:
        board_label = "XIAO nRF52840 Sense" if args.board == "sense" else "XIAO nRF52840"
        print(f"  Board: {board_label}")
        tmp_dir = tempfile.mkdtemp(prefix="opendisplay_bl_")
        pkg_path = download_dfu_package(args.board, tmp_dir)

    try:
        # Step 3: Detect or use specified serial port
        print_step(3, "Detecting serial port")
        if args.port:
            port = args.port
            print(f"  Using specified port: {port}")
        else:
            ports = find_serial_ports()
            if not ports:
                print("  No serial ports detected.")
                print("  Connect the board via USB and try again.")
                print("  You can specify the port manually with --port")
                sys.exit(1)
            if len(ports) == 1:
                port = ports[0]
                print(f"  Detected serial port: {port}")
            else:
                print("  Multiple serial ports found:")
                for i, p in enumerate(ports):
                    print(f"    [{i}] {p}")
                try:
                    choice = input("  Select port number: ").strip()
                    port = ports[int(choice)]
                except (ValueError, IndexError):
                    print("  Invalid selection.")
                    sys.exit(1)
                except KeyboardInterrupt:
                    print("\n  Cancelled.")
                    sys.exit(1)
                print(f"  Selected: {port}")

        # Step 4: Flash the bootloader
        print_step(4, "Flashing bootloader via Serial DFU")
        print()
        print(f"  Package: {os.path.basename(pkg_path)}")
        print(f"  Port:    {port}")
        print(f"  Speed:   115200")
        print()
        print("  This will update both the bootloader and SoftDevice.")
        print("  The process takes about 30-60 seconds.")
        print()

        cmd = [
            "adafruit-nrfutil", "dfu", "serial",
            "--package", pkg_path,
            "--port", port,
            "--baudrate", "115200",
            "--touch", "1200",
        ]
        print(f"  Running: {' '.join(cmd)}")
        print()

        try:
            result = subprocess.run(cmd, timeout=120)
        except subprocess.TimeoutExpired:
            print("\n  ERROR: DFU timed out after 120 seconds.")
            sys.exit(1)
        except FileNotFoundError:
            print("\n  ERROR: adafruit-nrfutil not found in PATH.")
            sys.exit(1)

        if result.returncode != 0:
            print(f"\n  ERROR: DFU failed (exit code {result.returncode}).")
            print("  Try putting the board into DFU mode manually:")
            print("    - Double-tap the RESET button, then retry")
            sys.exit(1)

        print()
        print("  " + "=" * 50)
        print("  Bootloader update completed successfully!")
        print("  The board will automatically restart.")
        print()
        print("  After restart, the board will have a working")
        print("  OTA DFU bootloader. You can now use BLE OTA")
        print("  updates via Home Assistant or nRF Connect.")
        print("  " + "=" * 50)
        print()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
