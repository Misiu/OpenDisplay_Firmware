#!/usr/bin/env python3
"""
OpenDisplay Bootloader Update Tool

Updates the Adafruit nRF52 bootloader on XIAO nRF52840 (Sense) boards to fix
broken OTA DFU support (e.g., EN04 boards shipped with a buggy bootloader).

Uses Serial DFU via adafruit-nrfutil, which works on ALL bootloader versions
including very old/broken ones. The .zip DFU package includes both the
bootloader and the SoftDevice for a complete update.

Runs on Windows, macOS, and Linux.

Requirements:
  - Python 3.7+
  - requests library (pip install requests)
  - adafruit-nrfutil:
      Linux/macOS: pip3 install --user adafruit-nrfutil
      macOS alt:   Download adafruit-nrfutil-macos from GitHub, chmod +x
      Windows:     Download adafruit-nrfutil.exe from GitHub
  - USB cable connected to the XIAO nRF52840 board

Usage:
  python update_bootloader.py
  python update_bootloader.py --board standard             # XIAO nRF52840 (non-Sense)
  python update_bootloader.py --port /dev/ttyACM0          # Specify serial port
  python update_bootloader.py --port COM3                   # Windows COM port
  python update_bootloader.py --pkg /path/to/bootloader.zip  # Use local DFU package

References:
  https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader
  https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader-use-command-line
  https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader-use-arduino-ide
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
BOOTLOADER_REPO_URL = "https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases"
NRFUTIL_RELEASES_URL = "https://github.com/adafruit/Adafruit_nRF52_nrfutil/releases"

# Board name patterns in GitHub release assets
BOARD_ASSET_NAMES = {
    "sense": "xiao_nrf52840_ble_sense_bootloader",
    "standard": "xiao_nrf52840_ble_bootloader",
}

BOARD_LABELS = {
    "sense": "XIAO nRF52840 Sense",
    "standard": "XIAO nRF52840",
}

# adafruit-nrfutil binary names to try, in order of preference.
# On Linux/macOS via pip: "adafruit-nrfutil"
# On macOS standalone:    "adafruit-nrfutil-macos" or "./adafruit-nrfutil-macos"
# On Windows via pip:     "adafruit-nrfutil" (resolved as adafruit-nrfutil.exe)
# On Windows standalone:  "adafruit-nrfutil.exe" or ".\\adafruit-nrfutil.exe"
_NRFUTIL_CANDIDATES = [
    "adafruit-nrfutil",
]
if platform.system() == "Darwin":
    _NRFUTIL_CANDIDATES.append("adafruit-nrfutil-macos")
    _NRFUTIL_CANDIDATES.append(os.path.join(".", "adafruit-nrfutil-macos"))
elif platform.system() == "Windows":
    _NRFUTIL_CANDIDATES.append("adafruit-nrfutil.exe")
    _NRFUTIL_CANDIDATES.append(os.path.join(".", "adafruit-nrfutil.exe"))


def print_header():
    system = platform.system()
    os_name = {"Linux": "Linux", "Darwin": "macOS", "Windows": "Windows"}.get(system, system)
    print()
    print("=" * 70)
    print("  OpenDisplay Bootloader Update Tool")
    print(f"  Running on {os_name}")
    print("=" * 70)
    print()
    print("  What this tool does:")
    print("  --------------------")
    print("  Updates the Adafruit nRF52 bootloader on your XIAO nRF52840 board")
    print("  using Serial DFU (Device Firmware Update) over USB.")
    print()
    print("  Why you might need this:")
    print("  ------------------------")
    print("  Some boards (e.g., EN04 revision) shipped with an older bootloader")
    print("  that has broken OTA (Over-The-Air) DFU support. Updating the")
    print("  bootloader fixes this and enables wireless firmware updates via")
    print("  BLE from Home Assistant or the nRF Connect mobile app.")
    print()
    print("  How it works:")
    print("  -------------")
    print("  1. Downloads the latest bootloader .zip from Adafruit's GitHub")
    print("  2. You double-tap RESET to put the board into DFU bootloader mode")
    print("  3. The tool detects the serial port and flashes via adafruit-nrfutil")
    print()
    print("  The .zip DFU package contains both the bootloader AND the Nordic")
    print("  SoftDevice (BLE stack), so this is a complete update that works")
    print("  regardless of what bootloader version is currently installed.")
    print("  The bootloader can also be freely upgraded or downgraded.")
    print()


def print_step(step_num, message):
    print(f"\n  Step {step_num}: {message}")
    print("  " + "-" * 50)


def print_manual_instructions(board_type, pkg_name):
    """Print manual update instructions for future reference."""
    board_name = BOARD_ASSET_NAMES.get(board_type, "")
    board_label = BOARD_LABELS.get(board_type, "")
    pkg_placeholder = pkg_name if pkg_name else f"{board_name}-<version>_s140_7.3.0.zip"
    print()
    print("=" * 70)
    print("  Manual Update Instructions (for future reference)")
    print("=" * 70)
    print()
    print("  If this tool is unavailable, you can update the bootloader")
    print("  manually using either method below.")
    print()
    print("-" * 70)
    print("  METHOD 1: Command Line (adafruit-nrfutil)")
    print("-" * 70)
    print()
    print("  Works on ALL bootloader versions. Recommended method.")
    print()
    print("  Install adafruit-nrfutil:")
    print()
    print("    Linux:")
    print("      pip3 install --user adafruit-nrfutil")
    print()
    print("    macOS:")
    print("      pip3 install --user adafruit-nrfutil")
    print("      Or download adafruit-nrfutil-macos from:")
    print(f"      {NRFUTIL_RELEASES_URL}")
    print("      Then: chmod +x adafruit-nrfutil-macos")
    print()
    print("    Windows:")
    print("      Download adafruit-nrfutil.exe from:")
    print(f"      {NRFUTIL_RELEASES_URL}")
    print()
    print(f"  1. Download the latest .zip for your board ({board_label}):")
    print(f"     {BOOTLOADER_REPO_URL}")
    print(f"     Look for: {board_name}-<version>_s140_7.3.0.zip")
    print(f"     Do NOT unzip this file — it will be used as-is.")
    print()
    print("  2. Connect the board via USB, then double-tap the RESET button")
    print("     to enter DFU bootloader mode. The board LED should pulse/fade")
    print("     and a USB drive ending in BOOT should appear.")
    print()
    print("  3. Find your serial port:")
    print("     Linux:   ls /dev/ttyACM*")
    print("     macOS:   ls /dev/cu.usbmodem*")
    print("     Windows: Device Manager > Ports > 'USB Serial Device' (COMxx)")
    print()
    print("  4. Run the update command for your OS:")
    print()
    print("     Linux:")
    print(f"       adafruit-nrfutil --verbose dfu serial \\")
    print(f"         --package {pkg_placeholder} \\")
    print(f"         --port /dev/ttyACM0 -b 115200 --singlebank --touch 1200")
    print()
    print("     macOS (pip install):")
    print(f"       adafruit-nrfutil --verbose dfu serial \\")
    print(f"         --package {pkg_placeholder} \\")
    print(f"         --port /dev/cu.usbmodemXXXX -b 115200 --singlebank --touch 1200")
    print()
    print("     macOS (standalone binary):")
    print(f"       ./adafruit-nrfutil-macos --verbose dfu serial \\")
    print(f"         --package {pkg_placeholder} \\")
    print(f"         --port /dev/cu.usbmodemXXXX -b 115200 --singlebank --touch 1200")
    print()
    print("     Windows:")
    print(f"       adafruit-nrfutil.exe --verbose dfu serial \\")
    print(f"         --package {pkg_placeholder} \\")
    print(f"         --port COMxx -b 115200 --singlebank --touch 1200")
    print()
    print("  Expected output:")
    print("    Upgrading target on <port> with DFU package <file>.")
    print("    Flow control is disabled, Single bank, Touch 1200")
    print("    Touched serial port <port>")
    print("    Opened serial port <port>")
    print("    Starting DFU upgrade of type 3, SoftDevice size: ..., bootloader size: ...")
    print("    Sending DFU start packet")
    print("    Sending DFU init packet")
    print("    Sending firmware file")
    print("    ########################################")
    print("    ...")
    print("    Activating new firmware")
    print("    DFU upgrade took XXs")
    print("    Device programmed.")
    print()
    print("  Once done, click RESET — the new bootloader will be running.")
    print()
    print("-" * 70)
    print("  METHOD 2: Arduino IDE (Burn Bootloader)")
    print("-" * 70)
    print()
    print("  Works on Windows, macOS, and Linux.")
    print("  Easiest if you already have Arduino IDE installed.")
    print("  The bundled bootloader may not be the absolute latest,")
    print("  but it will fix broken OTA DFU.")
    print()
    print("  IMPORTANT: Close Serial Monitor before starting!")
    print("  Do NOT close the IDE, unplug the board, or open Serial Monitor")
    print("  during the process — this can brick the device.")
    print()
    print("  1. Install the Adafruit nRF52 BSP in Arduino IDE:")
    print("     File > Preferences > Additional Board Manager URLs, add:")
    print("     https://adafruit.github.io/arduino-board-index/package_adafruit_index.json")
    print()
    print("  2. Install 'Adafruit nRF52' from Tools > Board > Boards Manager")
    print()
    print(f"  3. Select your board: Tools > Board > {board_label}")
    print()
    print("  4. Select programmer: Tools > Programmer >")
    print("     'Bootloader DFU for Bluefruit nRF52'")
    print()
    print("  5. Select your serial port: Tools > Port")
    print()
    print("  6. If you previously had CircuitPython on the board,")
    print("     double-tap RESET to enter bootloader mode first.")
    print()
    print("  7. Tools > Burn Bootloader")
    print("     Wait for 'Device programmed.' in the output log (~30-60s).")
    print()
    print("-" * 70)
    print("  TROUBLESHOOTING")
    print("-" * 70)
    print()
    print("  Serial DFU fails:")
    print("    - Double-tap RESET to manually enter DFU bootloader mode")
    print("    - Try a different USB cable (some are charge-only)")
    print("    - Verify the serial port is correct")
    print("    - Close any Serial Monitor or terminal attached to the port")
    print("    - Linux: ensure permission with: sudo usermod -aG dialout $USER")
    print("    - Windows: check Device Manager > Ports for the correct COMxx")
    print()
    print("  Board is completely bricked (no USB serial, no BOOT drive):")
    print("    - Use a J-Link/SWD debugger with nrfjprog to flash the .hex file")
    print(f"    - Download: {board_name}-<version>_s140_7.3.0.hex")
    print(f"    - Flash:    nrfjprog --program <file.hex> --chiperase --reset")
    print()
    print("  References:")
    print("    https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader")
    print("    https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader-use-command-line")
    print("    https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader-use-arduino-ide")
    print(f"    {BOOTLOADER_REPO_URL}")
    print()


# ---------------------------------------------------------------------------
# adafruit-nrfutil detection
# ---------------------------------------------------------------------------

def find_nrfutil():
    """Find the adafruit-nrfutil binary. Returns (path, version) or (None, None)."""
    for candidate in _NRFUTIL_CANDIDATES:
        try:
            result = subprocess.run(
                [candidate, "version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                return candidate, version
        except (FileNotFoundError, OSError):
            continue
        except Exception:
            continue
    return None, None


def print_nrfutil_install_help():
    """Print platform-specific adafruit-nrfutil install instructions."""
    system = platform.system()
    print("\n  ERROR: adafruit-nrfutil not found.")
    print()
    if system == "Linux":
        print("  Install on Linux:")
        print("    pip3 install --user adafruit-nrfutil")
    elif system == "Darwin":
        print("  Install on macOS (option A — pip):")
        print("    pip3 install --user adafruit-nrfutil")
        print()
        print("  Install on macOS (option B — standalone binary):")
        print(f"    1. Download adafruit-nrfutil-macos from {NRFUTIL_RELEASES_URL}")
        print("    2. Extract and make executable: chmod +x adafruit-nrfutil-macos")
        print("    3. Run this tool from the same directory, or add to PATH")
    elif system == "Windows":
        print("  Install on Windows:")
        print(f"    1. Download adafruit-nrfutil.exe from {NRFUTIL_RELEASES_URL}")
        print("    2. Place it in this directory or add to PATH")
        print()
        print("  Or install via pip (requires Python):")
        print("    pip install adafruit-nrfutil")
    else:
        print("  Install: pip3 install adafruit-nrfutil")


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
    """Find likely nRF52840 serial ports on any OS."""
    system = platform.system()
    ports = []

    if system == "Linux":
        # ttyACM* is the typical CDC-ACM serial port for nRF52840
        for dev in sorted(glob.glob("/dev/ttyACM*")):
            ports.append(dev)
    elif system == "Darwin":
        # cu.usbmodem* is the typical USB serial port on macOS
        for dev in sorted(glob.glob("/dev/cu.usbmodem*")):
            ports.append(dev)
    elif system == "Windows":
        # Use pyserial to enumerate COM ports; prefer nRF/Bluefruit matches
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                desc = (p.description or "").lower()
                if "nrf" in desc or "bluefruit" in desc:
                    ports.append(p.device)
            if not ports:
                for p in serial.tools.list_ports.comports():
                    ports.append(p.device)
        except ImportError:
            print("  Note: Install pyserial for automatic COM port detection:")
            print("        pip install pyserial")
            print("  Or specify the port manually with --port COMxx")

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
Runs on Windows, macOS, and Linux.

examples:
  %(prog)s                                    # Auto-detect port
  %(prog)s --port /dev/ttyACM0                # Linux: specify port
  %(prog)s --port /dev/cu.usbmodem14101       # macOS: specify port
  %(prog)s --port COM3                        # Windows: specify port
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
        help="Serial port (e.g., /dev/ttyACM0, /dev/cu.usbmodem14101, COM3)",
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
    nrfutil_bin, nrfutil_version = find_nrfutil()
    if not nrfutil_bin:
        print_nrfutil_install_help()
        sys.exit(1)
    print(f"  Found: {nrfutil_bin}")
    if nrfutil_version:
        print(f"  Version: {nrfutil_version}")

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
        board_label = BOARD_LABELS.get(args.board, "")
        print(f"  Board: {board_label}")
        tmp_dir = tempfile.mkdtemp(prefix="opendisplay_bl_")
        pkg_path = download_dfu_package(args.board, tmp_dir)

    try:
        # Step 3: Enter DFU bootloader mode
        print_step(3, "Enter DFU bootloader mode")
        print()
        print("  Connect the board via USB, then double-tap the RESET button.")
        print("  The board LED should start pulsing/fading and a USB drive")
        print("  ending in 'BOOT' should appear (e.g., XIAO-SENSE).")
        print()
        print("  How to double-tap reset:")
        print("    1. Press the RESET button once")
        print("    2. Wait about half a second")
        print("    3. Press the RESET button again quickly")
        print()
        input("  Press Enter when the board is in bootloader mode (or Ctrl+C to cancel)...")

        # Step 4: Detect or use specified serial port
        print_step(4, "Detecting serial port")
        if args.port:
            port = args.port
            print(f"  Using specified port: {port}")
        else:
            ports = find_serial_ports()
            if not ports:
                system = platform.system()
                print("  No serial ports detected.")
                print("  Make sure the board is in DFU bootloader mode")
                print("  (double-tap RESET) and connected via USB.")
                if system == "Linux":
                    print("  Check with: ls /dev/ttyACM*")
                    print("  Permission fix: sudo usermod -aG dialout $USER")
                elif system == "Darwin":
                    print("  Check with: ls /dev/cu.usbmodem*")
                elif system == "Windows":
                    print("  Check Device Manager > Ports for 'USB Serial Device'")
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

        # Step 5: Flash the bootloader
        print_step(5, "Flashing bootloader via Serial DFU")
        print()
        print(f"  Package: {os.path.basename(pkg_path)}")
        print(f"  Port:    {port}")
        print(f"  Speed:   115200")
        print(f"  Mode:    Single bank")
        print()
        print("  This will update both the bootloader and SoftDevice.")
        print("  The process typically takes 20-60 seconds.")
        print("  Do NOT unplug the board or close this window until done!")
        print()

        cmd = [
            nrfutil_bin, "--verbose", "dfu", "serial",
            "--package", pkg_path,
            "--port", port,
            "-b", "115200",
            "--singlebank",
            "--touch", "1200",
        ]
        print(f"  Running: {' '.join(cmd)}")
        print()

        try:
            result = subprocess.run(cmd, timeout=120)
        except subprocess.TimeoutExpired:
            print("\n  ERROR: DFU timed out after 120 seconds.")
            sys.exit(1)
        except (FileNotFoundError, OSError) as e:
            print(f"\n  ERROR: Failed to run {nrfutil_bin}: {e}")
            sys.exit(1)

        if result.returncode != 0:
            print(f"\n  ERROR: DFU failed (exit code {result.returncode}).")
            print("  Make sure the board is in DFU bootloader mode:")
            print("    - Double-tap the RESET button, then retry")
            print("    - Close any Serial Monitor or terminal on that port")
            sys.exit(1)

        print()
        print("  " + "=" * 58)
        print("  Bootloader update completed successfully!")
        print()
        print("  Click RESET once — the new bootloader will be running.")
        print("  You can now use BLE firmware updates via Home Assistant")
        print("  or the nRF Connect mobile app.")
        print("  " + "=" * 58)

        # Print manual instructions for future reference
        print_manual_instructions(args.board, os.path.basename(pkg_path))

    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
