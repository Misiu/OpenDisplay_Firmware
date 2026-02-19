# Bootloader Update Tool

Updates the Adafruit nRF52 bootloader on XIAO nRF52840 boards via Serial DFU.

Some boards (e.g., EN04 revision) shipped with an older bootloader that has
broken OTA (Over-The-Air) DFU support. Updating the bootloader fixes this and
enables wireless firmware updates.

This tool uses `adafruit-nrfutil` Serial DFU with a `.zip` DFU package that
contains both the bootloader and the Nordic SoftDevice (BLE stack). It works on
**all** bootloader versions, including very old or broken ones, and does **not**
require any specific firmware to be running on the board.

## Prerequisites

- Python 3.7+
- `requests` library
- `adafruit-nrfutil`
- USB cable connected to the board

### Install requests

```bash
pip install requests
```

### Install adafruit-nrfutil

**Linux:**

```bash
pip3 install --user adafruit-nrfutil
```

**macOS (pip):**

```bash
pip3 install --user adafruit-nrfutil
```

**macOS (standalone binary):**

Download `adafruit-nrfutil-macos` from the
[adafruit-nrfutil releases](https://github.com/adafruit/Adafruit_nRF52_nrfutil/releases),
then make it executable:

```bash
chmod +x adafruit-nrfutil-macos
```

**Windows:**

Download `adafruit-nrfutil.exe` from the
[adafruit-nrfutil releases](https://github.com/adafruit/Adafruit_nRF52_nrfutil/releases)
and place it in this directory or add to PATH.

Or install via pip (requires Python):

```bash
pip install adafruit-nrfutil
```

## Quick Start

```bash
# Check current bootloader version first
python tools/update_bootloader.py --version

# Update the bootloader
python tools/update_bootloader.py
```

The tool will:

1. Check that `adafruit-nrfutil` is installed
2. Download the latest bootloader `.zip` from
   [Adafruit's GitHub releases](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases)
3. Guide you through entering DFU bootloader mode (double-tap RESET)
4. Detect the serial port
5. Flash the bootloader and SoftDevice via Serial DFU

## Usage

```bash
# Read the current bootloader version (safe, read-only)
python tools/update_bootloader.py --version

# Auto-detect everything (interactive)
python tools/update_bootloader.py

# Specify serial port
python tools/update_bootloader.py --port /dev/ttyACM0       # Linux
python tools/update_bootloader.py --port /dev/cu.usbmodem411 # macOS
python tools/update_bootloader.py --port COM3                # Windows

# Non-Sense XIAO variant
python tools/update_bootloader.py --board standard

# Use a local .zip DFU package (skip download)
python tools/update_bootloader.py --pkg /path/to/bootloader.zip
```

## Step-by-Step Guide

### Step 1: Connect the board

Connect the XIAO nRF52840 to your computer using a USB data cable (not
charge-only).

### Step 2: Enter DFU bootloader mode

Double-tap the RESET button on the board:

1. Press the RESET button once
2. Wait about half a second
3. Press the RESET button again quickly

The board LED should start pulsing/fading, and a USB drive ending in `BOOT`
should appear (e.g., `XIAO-SENSE`).

> **Note:** This works regardless of what firmware is running on the board.
> Even a brand-new board with factory firmware can enter DFU mode this way.

### Step 3: Run the tool

```bash
python tools/update_bootloader.py
```

The tool will detect the serial port and flash the bootloader. The process
typically takes 20–60 seconds.

> **Warning:** Do NOT unplug the board or close the terminal during flashing.

### Step 4: Verify

After the update completes, press RESET once. The new bootloader will be
running. Verify the update by reading the bootloader version:

```bash
python tools/update_bootloader.py --version
```

This reads `INFO_UF2.TXT` from the UF2 boot drive and compares with the
latest release on GitHub.

## Manual Update (without this tool)

If you prefer to update manually, or this tool is unavailable:

### Using adafruit-nrfutil (CLI)

1. Download the latest `.zip` DFU package for your board from
   [Adafruit nRF52 Bootloader releases](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases).
   Look for files like `xiao_nrf52840_ble_sense_bootloader-<version>_s140_7.3.0.zip`.
   **Do not unzip** the file.

2. Double-tap RESET to enter DFU bootloader mode.

3. Find your serial port:
   - **Linux:** `ls /dev/ttyACM*`
   - **macOS:** `ls /dev/cu.usbmodem*`
   - **Windows:** Device Manager → Ports → "USB Serial Device" (COMxx)

4. Run the update command:

   **Linux:**
   ```bash
   adafruit-nrfutil --verbose dfu serial \
     --package xiao_nrf52840_ble_sense_bootloader-0.10.0_s140_7.3.0.zip \
     --port /dev/ttyACM0 -b 115200 --singlebank --touch 1200
   ```

   **macOS (pip):**
   ```bash
   adafruit-nrfutil --verbose dfu serial \
     --package xiao_nrf52840_ble_sense_bootloader-0.10.0_s140_7.3.0.zip \
     --port /dev/cu.usbmodem411 -b 115200 --singlebank --touch 1200
   ```

   **macOS (standalone):**
   ```bash
   ./adafruit-nrfutil-macos --verbose dfu serial \
     --package xiao_nrf52840_ble_sense_bootloader-0.10.0_s140_7.3.0.zip \
     --port /dev/cu.usbmodem411 -b 115200 --singlebank --touch 1200
   ```

   **Windows:**
   ```bash
   adafruit-nrfutil.exe --verbose dfu serial ^
     --package xiao_nrf52840_ble_sense_bootloader-0.10.0_s140_7.3.0.zip ^
     --port COM3 -b 115200 --singlebank --touch 1200
   ```

### Using Arduino IDE

1. Install the [Adafruit nRF52 BSP](https://github.com/adafruit/Adafruit_nRF52_Arduino):
   File → Preferences → Additional Board Manager URLs, add:
   ```
   https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
   ```
2. Install "Adafruit nRF52" from Tools → Board → Boards Manager
3. Select your board under Tools → Board
4. Select programmer: Tools → Programmer → "Bootloader DFU for Bluefruit nRF52"
5. Close Serial Monitor
6. If CircuitPython was previously installed, double-tap RESET first
7. Tools → Burn Bootloader — wait for "Device programmed" (~30–60 seconds)

> **Warning:** Do NOT close the IDE, unplug the board, or open Serial Monitor
> during the process.

## Troubleshooting

**Serial DFU fails:**
- Double-tap RESET to manually enter DFU bootloader mode, then retry
- Try a different USB cable (some are charge-only)
- Close any Serial Monitor or terminal attached to the port
- Linux: ensure permissions with `sudo usermod -aG dialout $USER` (re-login required)
- Windows: check Device Manager → Ports for the correct COM port

**No serial port detected:**
- Make sure the board is in DFU bootloader mode (double-tap RESET)
- Try a different USB port or cable
- On Windows, install pyserial for auto-detection: `pip install pyserial`

**Board is completely bricked (no USB serial, no BOOT drive):**
- Use a J-Link or SWD debugger with `nrfjprog`:
  ```bash
  nrfjprog --program <bootloader>.hex --chiperase --reset
  ```
- Download the `.hex` file from
  [Adafruit nRF52 Bootloader releases](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases)

## References

- [Adafruit: Update Bootloader (overview)](https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader)
- [Adafruit: Update Bootloader (CLI)](https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader-use-command-line)
- [Adafruit: Update Bootloader (Arduino IDE)](https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/update-bootloader-use-arduino-ide)
- [Adafruit nRF52 Bootloader repository](https://github.com/adafruit/Adafruit_nRF52_Bootloader)
- [adafruit-nrfutil releases](https://github.com/adafruit/Adafruit_nRF52_nrfutil/releases)
