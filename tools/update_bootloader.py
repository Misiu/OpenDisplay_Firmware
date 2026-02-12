#!/usr/bin/env python3
"""
OpenDisplay Bootloader Update Tool

Updates the Adafruit nRF52 bootloader on XIAO nRF52840 (Sense) boards to fix
broken OTA DFU support (e.g., EN04 boards shipped with a buggy bootloader).

Supports three update methods:
  - serial: Serial DFU via adafruit-nrfutil (default, works on ALL bootloader versions)
  - uf2:    UF2 drag-and-drop via USB drive (requires double-tap reset)
  - ota:    OTA DFU via BLE using adafruit-nrfutil (wireless, no USB needed)

The serial method is recommended because it works regardless of how old or
broken the current bootloader is. It uses a .zip DFU package that includes
both the bootloader and the SoftDevice.

Requirements:
  - Python 3.7+
  - requests library (pip install requests)
  - adafruit-nrfutil (pip install adafruit-nrfutil) — for serial/ota methods
  - USB cable connected to the XIAO nRF52840 board

Usage:
  python update_bootloader.py                              # Serial DFU (default)
  python update_bootloader.py --method uf2                 # UF2 drag-and-drop
  python update_bootloader.py --method ota --address XX:XX:XX:XX:XX:XX  # BLE OTA
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
import time

GITHUB_API_URL = "https://api.github.com/repos/adafruit/Adafruit_nRF52_Bootloader/releases/latest"

# Board name patterns in GitHub release assets
BOARD_ASSET_NAMES = {
    "sense": "xiao_nrf52840_ble_sense_bootloader",
    "standard": "xiao_nrf52840_ble_bootloader",
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


# ---------------------------------------------------------------------------
# GitHub release download helpers
# ---------------------------------------------------------------------------

def _github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers


def _fetch_latest_release():
    import requests
    print("  Fetching latest release from GitHub...")
    try:
        resp = requests.get(GITHUB_API_URL, headers=_github_headers(), timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"\n  ERROR: Failed to fetch release info: {e}")
        print("  Tip: Set GITHUB_TOKEN env var if you hit rate limits.")
        sys.exit(1)
    return resp.json()


def _download_asset(release, suffix, dest_dir, board_type):
    """Download an asset from a GitHub release matching board + suffix."""
    import requests
    board_name = BOARD_ASSET_NAMES.get(board_type, "")
    asset_url = None
    asset_name = None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if board_name in name and name.endswith(suffix):
            asset_url = asset.get("browser_download_url")
            asset_name = name
            break
    if not asset_url:
        print(f"\n  ERROR: No asset matching '*{board_name}*{suffix}'")
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


def download_dfu_package(board_type, dest_dir):
    """Download the .zip DFU package (bootloader + SoftDevice) for serial/OTA DFU."""
    try:
        import requests  # noqa: F401
    except ImportError:
        print("\n  ERROR: 'requests' library not found.")
        print("  Install it with: pip install requests")
        sys.exit(1)

    release = _fetch_latest_release()
    tag = release.get("tag_name", "unknown")
    print(f"  Latest bootloader version: {tag}")
    # The .zip includes both bootloader + SoftDevice — safe for any version
    return _download_asset(release, ".zip", dest_dir, board_type)


def download_uf2(board_type, dest_dir):
    """Download the UF2 bootloader update (no SoftDevice) for UF2 drag-and-drop."""
    try:
        import requests  # noqa: F401
    except ImportError:
        print("\n  ERROR: 'requests' library not found.")
        print("  Install it with: pip install requests")
        sys.exit(1)

    release = _fetch_latest_release()
    tag = release.get("tag_name", "unknown")
    print(f"  Latest bootloader version: {tag}")
    # The _nosd.uf2 updates only the bootloader, keeping existing SoftDevice
    return _download_asset(release, "_nosd.uf2", dest_dir, board_type)


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
        # List COM ports
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                if "nRF" in (p.description or "") or "Bluefruit" in (p.description or ""):
                    ports.append(p.device)
            if not ports:
                # Fallback: list all COM ports
                for p in serial.tools.list_ports.comports():
                    ports.append(p.device)
        except ImportError:
            # Without pyserial, can't enumerate COM ports
            print("  Note: Install pyserial for automatic COM port detection")
            print("        pip install pyserial")

    return ports


# ---------------------------------------------------------------------------
# UF2 drive detection
# ---------------------------------------------------------------------------

def find_uf2_drives():
    """Find mounted UF2 bootloader drives."""
    system = platform.system()
    drives = []

    if system == "Darwin":
        volumes = glob.glob("/Volumes/*")
        for vol in volumes:
            info_path = os.path.join(vol, "INFO_UF2.TXT")
            if os.path.exists(info_path):
                drives.append(vol)
            elif os.path.basename(vol) in UF2_VOLUME_NAMES:
                drives.append(vol)

    elif system == "Linux":
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


# ---------------------------------------------------------------------------
# Update methods
# ---------------------------------------------------------------------------

def check_nrfutil():
    """Check if adafruit-nrfutil is installed."""
    try:
        result = subprocess.run(
            ["adafruit-nrfutil", "version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"  adafruit-nrfutil: {version}")
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return False


def _prepare_package(args, download_fn):
    """Get local package path or download from GitHub. Returns (path, temp_dir_or_None)."""
    if args.pkg:
        if not os.path.exists(args.pkg):
            print(f"  ERROR: File not found: {args.pkg}")
            sys.exit(1)
        print(f"  Using local file: {args.pkg}")
        return args.pkg, None
    board_label = "XIAO nRF52840 Sense" if args.board == "sense" else "XIAO nRF52840"
    print(f"  Board: {board_label}")
    tmp_dir = tempfile.mkdtemp(prefix="opendisplay_bl_")
    path = download_fn(args.board, tmp_dir)
    return path, tmp_dir


def do_serial_dfu(args):
    """Update bootloader via Serial DFU using adafruit-nrfutil."""
    print_step(1, "Checking prerequisites")
    if not check_nrfutil():
        print("\n  ERROR: adafruit-nrfutil not found.")
        print("  Install it with: pip install adafruit-nrfutil")
        sys.exit(1)

    # Get or download the DFU package
    print_step(2, "Preparing bootloader DFU package")
    pkg_path, tmp_dir = _prepare_package(args, download_dfu_package)

    try:
        # Detect or use specified serial port
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

        # Perform the DFU update
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
            print("    - Double-tap the RESET button")
            print("    - Or try the --method uf2 option instead")
            sys.exit(1)

        _print_success()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def do_uf2(args):
    """Update bootloader via UF2 drag-and-drop."""
    print_step(1, "Preparing bootloader UF2 file")
    uf2_path, tmp_dir = _prepare_package(args, download_uf2)

    try:
        # Enter UF2 bootloader mode
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

        # Detect the UF2 drive
        if args.drive:
            drive = args.drive
            if not os.path.isdir(drive):
                print(f"  ERROR: Drive path not found: {drive}")
                sys.exit(1)
            print(f"  Using specified drive: {drive}")
        else:
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

        # Flash the bootloader
        print_step(4, "Flashing bootloader update")
        dest = os.path.join(drive, os.path.basename(uf2_path))
        print(f"  Copying {os.path.basename(uf2_path)} to {drive}...")
        try:
            shutil.copy2(uf2_path, dest)
        except OSError as e:
            print(f"\n  ERROR: Failed to copy file: {e}")
            sys.exit(1)

        _print_success()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def do_ota_dfu(args):
    """Update bootloader via BLE OTA DFU using adafruit-nrfutil."""
    print_step(1, "Checking prerequisites")
    if not check_nrfutil():
        print("\n  ERROR: adafruit-nrfutil not found.")
        print("  Install it with: pip install adafruit-nrfutil")
        sys.exit(1)

    if not args.address:
        print("\n  ERROR: BLE address required for OTA DFU.")
        print("  Use --address XX:XX:XX:XX:XX:XX")
        print("  You can find the address using: nRF Connect app or bluetoothctl")
        sys.exit(1)

    # Get or download the DFU package
    print_step(2, "Preparing bootloader DFU package")
    pkg_path, tmp_dir = _prepare_package(args, download_dfu_package)

    try:
        # Perform the OTA DFU update
        print_step(3, "Flashing bootloader via BLE OTA DFU")
        print()
        print(f"  Package: {os.path.basename(pkg_path)}")
        print(f"  Address: {args.address}")
        print()
        print("  The board must be in OTA DFU mode (GPREGRET = 0xB1).")
        print("  If using OpenDisplay firmware, send BLE command 0x0044 first.")
        print()

        cmd = [
            "adafruit-nrfutil", "dfu", "ble",
            "--package", pkg_path,
            "--address", args.address,
        ]
        print(f"  Running: {' '.join(cmd)}")
        print()

        try:
            result = subprocess.run(cmd, timeout=180)
        except subprocess.TimeoutExpired:
            print("\n  ERROR: OTA DFU timed out after 180 seconds.")
            sys.exit(1)
        except FileNotFoundError:
            print("\n  ERROR: adafruit-nrfutil not found in PATH.")
            sys.exit(1)

        if result.returncode != 0:
            print(f"\n  ERROR: OTA DFU failed (exit code {result.returncode}).")
            print("  Make sure the board is in OTA DFU mode and in BLE range.")
            sys.exit(1)

        _print_success()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _print_success():
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Update the Adafruit nRF52 bootloader on XIAO nRF52840 boards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
methods:
  serial  Update via USB serial using adafruit-nrfutil (default).
          Works on ALL bootloader versions including very old ones.
          Requires: pip install adafruit-nrfutil

  uf2     Update via UF2 drag-and-drop to USB drive.
          Requires double-tap reset to enter UF2 bootloader mode.

  ota     Update via BLE OTA using adafruit-nrfutil.
          Requires the board to be in OTA DFU mode (BLE command 0x0044).
          Requires: pip install adafruit-nrfutil

examples:
  %(prog)s                                    # Serial DFU (recommended)
  %(prog)s --method uf2                       # UF2 drag-and-drop
  %(prog)s --method ota --address AA:BB:CC:DD:EE:FF
  %(prog)s --port /dev/ttyACM0                # Specify serial port
  %(prog)s --board standard                   # Non-Sense XIAO variant
  %(prog)s --pkg bootloader.zip               # Use local DFU package
""",
    )
    parser.add_argument(
        "--method",
        choices=["serial", "uf2", "ota"],
        default="serial",
        help="Update method (default: serial)",
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
        help="Serial port for serial DFU (e.g., /dev/ttyACM0, COM3)",
    )
    parser.add_argument(
        "--address",
        type=str,
        default=None,
        help="BLE address for OTA DFU (e.g., AA:BB:CC:DD:EE:FF)",
    )
    parser.add_argument(
        "--pkg",
        type=str,
        default=None,
        help="Path to a local .zip DFU package or .uf2 file (skips download)",
    )
    parser.add_argument(
        "--drive",
        type=str,
        default=None,
        help="Path to UF2 drive for uf2 method (skips auto-detection)",
    )
    args = parser.parse_args()

    print_header()

    if args.method == "serial":
        do_serial_dfu(args)
    elif args.method == "uf2":
        do_uf2(args)
    elif args.method == "ota":
        do_ota_dfu(args)


if __name__ == "__main__":
    main()
