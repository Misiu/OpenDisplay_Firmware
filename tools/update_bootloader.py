#!/usr/bin/env python3
"""
OpenDisplay Bootloader Update Tool

Updates the Adafruit nRF52 bootloader on XIAO nRF52840 (Sense) boards to fix
broken OTA DFU support (e.g., EN04 boards shipped with a buggy bootloader).

The tool:
  1. Downloads the latest Adafruit bootloader UF2 from GitHub releases
  2. Guides you to put the board into UF2 bootloader mode (double-tap reset)
  3. Detects the UF2 drive automatically
  4. Copies the bootloader update file to the drive

Requirements:
  - Python 3.7+
  - requests library (pip install requests)
  - USB cable connected to the XIAO nRF52840 board

Usage:
  python update_bootloader.py
  python update_bootloader.py --board sense     # XIAO nRF52840 Sense (default)
  python update_bootloader.py --board standard  # XIAO nRF52840 (non-Sense)
  python update_bootloader.py --uf2 /path/to/bootloader.uf2  # Use local file
"""

import argparse
import glob
import os
import platform
import shutil
import sys
import time

GITHUB_API_URL = "https://api.github.com/repos/adafruit/Adafruit_nRF52_Bootloader/releases/latest"

BOARD_UF2_PATTERNS = {
    "sense": "update-xiao_nrf52840_ble_sense_bootloader-",
    "standard": "update-xiao_nrf52840_ble_bootloader-",
}

# Known UF2 drive volume names
UF2_VOLUME_NAMES = ["XIAO-SENSE", "XIAO-BLE", "NRF52BOOT", "FTHR840BOOT"]


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


def find_uf2_drives():
    """Find mounted UF2 bootloader drives."""
    system = platform.system()
    drives = []

    if system == "Darwin":  # macOS
        volumes = glob.glob("/Volumes/*")
        for vol in volumes:
            info_path = os.path.join(vol, "INFO_UF2.TXT")
            if os.path.exists(info_path):
                drives.append(vol)
            elif os.path.basename(vol) in UF2_VOLUME_NAMES:
                drives.append(vol)

    elif system == "Linux":
        # Check common mount points (max 3 levels deep to avoid slow traversals)
        max_depth = 3
        for base in ["/media", "/mnt", "/run/media"]:
            if not os.path.isdir(base):
                continue
            for root, dirs, files in os.walk(base):
                if root.count(os.sep) - base.count(os.sep) >= max_depth:
                    dirs.clear()
                    continue
                if "INFO_UF2.TXT" in files:
                    drives.append(root)
                for name in UF2_VOLUME_NAMES:
                    if name in dirs:
                        path = os.path.join(root, name)
                        if path not in drives:
                            drives.append(path)

    elif system == "Windows":
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                info_path = os.path.join(drive, "INFO_UF2.TXT")
                if os.path.exists(info_path):
                    drives.append(drive)

    return drives


def read_uf2_info(drive_path):
    """Read INFO_UF2.TXT from the drive to show bootloader info."""
    info_path = os.path.join(drive_path, "INFO_UF2.TXT")
    if os.path.exists(info_path):
        with open(info_path, "r") as f:
            return f.read().strip()
    return None


def download_bootloader(board_type, dest_dir):
    """Download the latest Adafruit bootloader UF2 from GitHub releases."""
    try:
        import requests
    except ImportError:
        print("\n  ERROR: 'requests' library not found.")
        print("  Install it with: pip install requests")
        sys.exit(1)

    pattern = BOARD_UF2_PATTERNS.get(board_type)
    if not pattern:
        print(f"\n  ERROR: Unknown board type '{board_type}'")
        sys.exit(1)

    print(f"  Fetching latest release from GitHub...")
    headers = {"Accept": "application/vnd.github+json"}
    # Support optional GitHub token to avoid rate limits (60 req/hr unauthenticated)
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
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

    # Find matching asset — we need the "_nosd" (no SoftDevice) variant,
    # which updates only the bootloader while keeping the existing SoftDevice.
    # This is safe for boards that already have a working SoftDevice.
    asset_url = None
    asset_name = None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(pattern) and name.endswith("_nosd.uf2"):
            asset_url = asset.get("browser_download_url")
            asset_name = name
            break

    if not asset_url:
        print(f"\n  ERROR: Could not find UF2 asset matching '{pattern}*_nosd.uf2'")
        print("  Available assets:")
        for asset in release.get("assets", []):
            if "xiao" in asset.get("name", "").lower():
                print(f"    - {asset['name']}")
        sys.exit(1)

    print(f"  Downloading: {asset_name}")
    try:
        resp = requests.get(asset_url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"\n  ERROR: Failed to download bootloader: {e}")
        sys.exit(1)

    dest_path = os.path.join(dest_dir, asset_name)
    with open(dest_path, "wb") as f:
        f.write(resp.content)

    size_kb = len(resp.content) / 1024
    print(f"  Downloaded: {size_kb:.1f} KB")
    return dest_path


def wait_for_uf2_drive(timeout=60):
    """Wait for a UF2 drive to appear."""
    print(f"  Waiting for UF2 drive (timeout: {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        drives = find_uf2_drives()
        if drives:
            return drives[0]
        time.sleep(1)
        elapsed = int(time.time() - start)
        if elapsed % 10 == 0 and elapsed > 0:
            print(f"  Still waiting... ({elapsed}s)")
    return None


def copy_uf2_to_drive(uf2_path, drive_path):
    """Copy the UF2 file to the bootloader drive."""
    dest = os.path.join(drive_path, os.path.basename(uf2_path))
    print(f"  Copying {os.path.basename(uf2_path)} to {drive_path}...")
    try:
        shutil.copy2(uf2_path, dest)
    except OSError as e:
        print(f"\n  ERROR: Failed to copy file: {e}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Update the Adafruit nRF52 bootloader on XIAO nRF52840 boards"
    )
    parser.add_argument(
        "--board",
        choices=["sense", "standard"],
        default="sense",
        help="Board variant: 'sense' for XIAO nRF52840 Sense (default), 'standard' for XIAO nRF52840",
    )
    parser.add_argument(
        "--uf2",
        type=str,
        default=None,
        help="Path to a local bootloader UF2 file (skips download)",
    )
    parser.add_argument(
        "--drive",
        type=str,
        default=None,
        help="Path to the UF2 drive (skips auto-detection)",
    )
    args = parser.parse_args()

    print_header()

    # Step 1: Get the bootloader UF2 file
    print_step(1, "Preparing bootloader update file")

    if args.uf2:
        if not os.path.exists(args.uf2):
            print(f"  ERROR: File not found: {args.uf2}")
            sys.exit(1)
        uf2_path = args.uf2
        print(f"  Using local file: {uf2_path}")
    else:
        board_name = "XIAO nRF52840 Sense" if args.board == "sense" else "XIAO nRF52840"
        print(f"  Board: {board_name}")
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="opendisplay_bl_")
        uf2_path = download_bootloader(args.board, tmp_dir)

    # Step 2: Enter UF2 bootloader mode
    print_step(2, "Enter UF2 bootloader mode on your board")
    print()
    print("  Connect the board via USB and double-tap the RESET button.")
    print("  The board should appear as a USB drive (e.g., XIAO-SENSE).")
    print()
    print("  How to double-tap reset:")
    print("    1. Press the RESET button once")
    print("    2. Wait ~0.5 seconds")
    print("    3. Press the RESET button again quickly")
    print("    4. The board LED should pulse/fade (bootloader mode)")
    print()

    # Step 3: Detect the UF2 drive
    if args.drive:
        drive = args.drive
        if not os.path.isdir(drive):
            print(f"  ERROR: Drive path not found: {drive}")
            sys.exit(1)
        print(f"  Using specified drive: {drive}")
    else:
        # Check if already connected
        drives = find_uf2_drives()
        if drives:
            drive = drives[0]
            print(f"  UF2 drive already detected: {drive}")
        else:
            input("  Press Enter when the USB drive appears (or Ctrl+C to cancel)...")
            print()
            print_step(3, "Detecting UF2 bootloader drive")
            drive = wait_for_uf2_drive(timeout=60)

        if not drive:
            print("\n  ERROR: No UF2 drive detected.")
            print("  Make sure the board is in bootloader mode (double-tap reset).")
            print("  You can also specify the drive path with --drive /path/to/drive")
            sys.exit(1)

    # Show current bootloader info
    info = read_uf2_info(drive)
    if info:
        print(f"\n  Current bootloader info:")
        for line in info.split("\n"):
            print(f"    {line}")
    print()

    # Step 4: Flash the bootloader
    print_step(4, "Flashing bootloader update")

    if not copy_uf2_to_drive(uf2_path, drive):
        sys.exit(1)

    print()
    print("  " + "=" * 50)
    print("  Bootloader update file copied successfully!")
    print("  The board will automatically restart.")
    print()
    print("  After restart, the board will have a working")
    print("  OTA DFU bootloader. You can now use BLE OTA")
    print("  updates via Home Assistant or nRF Connect.")
    print("  " + "=" * 50)
    print()


if __name__ == "__main__":
    main()
