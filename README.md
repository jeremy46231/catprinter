![Cat Printer](./media/hackoclock.jpg)

Cat printer is a portable thermal printer sold on AliExpress for around $20. This project supports models using the MXW01 protocol.

This repository contains Python code for talking to the cat printer over Bluetooth Low Energy (BLE). The code has been reverse engineered from various sources analyzing the MXW01 protocol.

# Installation
```bash
# Clone the repository.
$ git clone git@github.com:rbaron/catprinter.git
$ cd catprinter
# Create a virtualenv on venv/ and activate it.
$ virtualenv --python=python3 venv
$ source venv/bin/activate
# Install requirements from requirements.txt.
$ pip install -r requirements.txt
```

# Usage
```bash
$ ./print.py --help
usage: print.py [-h] [-l {debug,info,warn,error}] [-b {mean-threshold,floyd-steinberg,atkinson,halftone,none}] [-s] [-d DEVICE] [--intensity INTENSITY]
                filename

prints an image on your MXW01 cat thermal printer

positional arguments:
  filename

options:
  -h, --help            show this help message and exit
  -l {debug,info,warn,error}, --log-level {debug,info,warn,error}
  -b {mean-threshold,floyd-steinberg,atkinson,halftone,none}, --img-binarization-algo {mean-threshold,floyd-steinberg,atkinson,halftone,none}
                        Which image binarization algorithm to use. If 'none' is used, no binarization will be used. In this case the image has to
                        have a width of 384 px.
  -s, --show-preview    If set, displays the final image and asks the user for confirmation before printing.
  -d DEVICE, --device DEVICE
                        The printer's Bluetooth Low Energy (BLE) address (MAC address on Linux; UUID on macOS) or advertisement name (e.g.:
                        "MXW01", "GT01"). If omitted, the the script will try to auto discover the printer based on its advertised BLE
                        services.
  --intensity INTENSITY
                        Print intensity/energy byte (0x00-0xFF, default 0x5D). Higher values generally produce darker prints. Accepts hex (0xNN) or decimal.
```

# Example
```bash
# Print test.png using default intensity (0x5D) and auto-discovery
% ./print.py --show-preview test.png

# Print test.png with higher intensity (darker) specifying device name
% ./print.py --intensity 0x80 --device MXW01 test.png

# Example Log Output (MXW01)
⏳ Applying Floyd-Steinberg dithering to image...
✅ Done.
✅ Read image: (42, 384) (h, w) pixels
ℹ️  Displaying preview.
🤔 Go ahead with print? [Y/n]? y
Preparing image data buffer for MXW01...
Image data buffer (2016 bytes) is smaller than minimum (4320 bytes). Adding 2304 bytes of padding.
✅ Generated MXW01 image data buffer: 4320 bytes
⏳ Trying to auto-discover a printer (MXW01 Service)...
✅ Got it. Address: XX:XX:XX:XX:XX:XX: MXW01
⏳ Attempting to connect to XX:XX:XX:XX:XX:XX...
✅ Connected: True; MTU: 247
Found service: 0000ae30-0000-1000-8000-00805f9b34fb
✅ Found required characteristics.
Starting notifications on 0000ae02-0000-1000-8000-00805f9b34fb...
✅ Notifications started.
Prepared 90 lines of image data (including padding if any).
Setting intensity to 0x5d...
Requesting printer status (A1)...
Received Response ID: 0xa1, Payload: 0000000000000000006400000000
Printer Status OK (Flag=0). State: 0x00, Battery: 100%
Sending print request for 90 lines (A9)...
Received Response ID: 0xa9, Payload: 00
✅ Print request accepted (A9 response OK).
Sending 4320 bytes of image data to 0000ae03-0000-1000-8000-00805f9b34fb...
Sent chunk 50/90
Sent chunk 90/90
✅ Finished sending image data.
Sending data flush command (AD)...
Waiting up to 21.0s for print complete (AA)...
Received Response ID: 0xaa, Payload: 00
✅ Print Complete notification (AA) received. Payload: 00
🎉 Print job successfully sent and acknowledged by printer.
Stopping notifications...
Disconnecting...
BLE operation finished.
```

# Different Algorithms

**Mean Threshold:**

![Mean threshold](./media/grumpymeanthreshold.png)

**Floyd Steinberg (default):**

![Floyd Steinberg](./media/grumpyfloydsteinbergexample.png)

**Atkinson:**

![Atkinson](./media/grumpyatkinsonexample.png)

**Halftone dithering:**

![Halftone](./media/grumpyhalftone.png)

**None (image must be 384px wide):**

![None](./media/grumpynone.png)
