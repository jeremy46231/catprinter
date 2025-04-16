import logging
import numpy as np  # Add numpy import if using numpy arrays internally

logger = logging.getLogger(__name__)  # Use local logger

# --- MXW01 BLE Constants ---
# Service UUID for MXW01 printers
MAIN_SERVICE_UUID = "0000ae30-0000-1000-8000-00805f9b34fb"
# Note: bleak on macOS might report af30 instead of ae30 for the same service.
#       Handling this might require adjustments in ble.py scan filter.

# Characteristic for sending control commands (A1, A2, A9, AD, etc.)
CONTROL_WRITE_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
# Characteristic for receiving status notifications (A1, A9, AA responses)
NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"
# Characteristic for sending bulk image data (Write Without Response)
DATA_WRITE_UUID = "0000ae03-0000-1000-8000-00805f9b34fb"

# --- Printer Specifics ---
PRINTER_WIDTH_PIXELS = 384
PRINTER_WIDTH_BYTES = PRINTER_WIDTH_PIXELS // 8  # Should be 48

# Minimum data buffer size observed in some implementations (natey, moblin)
# Equivalent to 90 lines * 48 bytes/line. Pad image data if shorter.
MIN_DATA_BYTES = 90 * PRINTER_WIDTH_BYTES  # 4320


# --- MXW01 Command IDs ---
class CommandIds:
    GET_STATUS = 0xA1
    PRINT_INTENSITY = 0xA2
    # QUERY_COUNT = 0xA7 # Optional status command
    PRINT = 0xA9  # Initiate print with dimensions/mode
    PRINT_COMPLETE = 0xAA  # Notification ID when printing finishes
    BATTERY_LEVEL = 0xAB  # Optional status command
    # CANCEL_PRINT = 0xAC    # Optional control command
    PRINT_DATA_FLUSH = 0xAD  # Signal end of image data transfer
    # GET_PRINT_TYPE = 0xB0  # Optional status command
    GET_VERSION = 0xB1  # Optional status command


# --- Print Modes (for A9 command) ---
class PrintModes:
    MONOCHROME = 0x00  # 1 bit per pixel
    GRAYSCALE = 0x02  # 4 bits per pixel (Future enhancement)


# CRC8 (Dallas/Maxim variant, Polynomial 0x07, Init 0x00) Lookup Table
_CRC8_TABLE = [
    0x00,
    0x07,
    0x0E,
    0x09,
    0x1C,
    0x1B,
    0x12,
    0x15,
    0x38,
    0x3F,
    0x36,
    0x31,
    0x24,
    0x23,
    0x2A,
    0x2D,
    0x70,
    0x77,
    0x7E,
    0x79,
    0x6C,
    0x6B,
    0x62,
    0x65,
    0x48,
    0x4F,
    0x46,
    0x41,
    0x54,
    0x53,
    0x5A,
    0x5D,
    0xE0,
    0xE7,
    0xEE,
    0xE9,
    0xFC,
    0xFB,
    0xF2,
    0xF5,
    0xD8,
    0xDF,
    0xD6,
    0xD1,
    0xC4,
    0xC3,
    0xCA,
    0xCD,
    0x90,
    0x97,
    0x9E,
    0x99,
    0x8C,
    0x8B,
    0x82,
    0x85,
    0xA8,
    0xAF,
    0xA6,
    0xA1,
    0xB4,
    0xB3,
    0xBA,
    0xBD,
    0xC7,
    0xC0,
    0xC9,
    0xCE,
    0xDB,
    0xDC,
    0xD5,
    0xD2,
    0xFF,
    0xF8,
    0xF1,
    0xF6,
    0xE3,
    0xE4,
    0xED,
    0xEA,
    0xB7,
    0xB0,
    0xB9,
    0xBE,
    0xAB,
    0xAC,
    0xA5,
    0xA2,
    0x8F,
    0x88,
    0x81,
    0x86,
    0x93,
    0x94,
    0x9D,
    0x9A,
    0x27,
    0x20,
    0x29,
    0x2E,
    0x3B,
    0x3C,
    0x35,
    0x32,
    0x1F,
    0x18,
    0x11,
    0x16,
    0x03,
    0x04,
    0x0D,
    0x0A,
    0x57,
    0x50,
    0x59,
    0x5E,
    0x4B,
    0x4C,
    0x45,
    0x42,
    0x6F,
    0x68,
    0x61,
    0x66,
    0x73,
    0x74,
    0x7D,
    0x7A,
    0x89,
    0x8E,
    0x87,
    0x80,
    0x95,
    0x92,
    0x9B,
    0x9C,
    0xB1,
    0xB6,
    0xBF,
    0xB8,
    0xAD,
    0xAA,
    0xA3,
    0xA4,
    0xF9,
    0xFE,
    0xF7,
    0xF0,
    0xE5,
    0xE2,
    0xEB,
    0xEC,
    0xC1,
    0xC6,
    0xCF,
    0xC8,
    0xDD,
    0xDA,
    0xD3,
    0xD4,
    0x69,
    0x6E,
    0x67,
    0x60,
    0x75,
    0x72,
    0x7B,
    0x7C,
    0x51,
    0x56,
    0x5F,
    0x58,
    0x4D,
    0x4A,
    0x43,
    0x44,
    0x19,
    0x1E,
    0x17,
    0x10,
    0x05,
    0x02,
    0x0B,
    0x0C,
    0x21,
    0x26,
    0x2F,
    0x28,
    0x3D,
    0x3A,
    0x33,
    0x34,
    0x4E,
    0x49,
    0x40,
    0x47,
    0x52,
    0x55,
    0x5C,
    0x5B,
    0x76,
    0x71,
    0x78,
    0x7F,
    0x6A,
    0x6D,
    0x64,
    0x63,
    0x3E,
    0x39,
    0x30,
    0x37,
    0x22,
    0x25,
    0x2C,
    0x2B,
    0x06,
    0x01,
    0x08,
    0x0F,
    0x1A,
    0x1D,
    0x14,
    0x13,
    0xAE,
    0xA9,
    0xA0,
    0xA7,
    0xB2,
    0xB5,
    0xBC,
    0xBB,
    0x96,
    0x91,
    0x98,
    0x9F,
    0x8A,
    0x8D,
    0x84,
    0x83,
    0xDE,
    0xD9,
    0xD0,
    0xD7,
    0xC2,
    0xC5,
    0xCC,
    0xCB,
    0xE6,
    0xE1,
    0xE8,
    0xEF,
    0xFA,
    0xFD,
    0xF4,
    0xF3,
]


def calculate_crc8(data: bytes) -> int:
    """Calculates CRC8 checksum for the given data payload."""
    crc = 0
    for byte in data:
        crc = _CRC8_TABLE[crc ^ byte]
    return crc


def create_command(command_id: int, command_data: bytes) -> bytearray:
    """
    Creates a complete MXW01 command packet with preamble, length, data, CRC, and footer.
    CRC is calculated ONLY over the command_data payload.
    """
    data_len = len(command_data)
    if data_len > 0xFFFF:
        # This should realistically never happen for control commands
        logger.error(f"Command data too large: {data_len} bytes")
        raise ValueError("Command data length exceeds 65535 bytes")

    command = bytearray(
        [
            0x22,
            0x21,  # Preamble
            command_id & 0xFF,  # Command ID
            0x00,  # Fixed byte
            data_len & 0xFF,  # Data length (Little Endian Byte 0)
            (data_len >> 8) & 0xFF,  # Data length (Little Endian Byte 1)
        ]
    )
    command.extend(command_data)  # Command Data Payload
    crc = calculate_crc8(command_data)
    command.append(crc)  # CRC8 of command_data
    command.append(0xFF)  # Footer
    return command


# --- Optional: Helper functions for common commands ---
def cmd_get_status() -> bytearray:
    return create_command(CommandIds.GET_STATUS, bytes([0x00]))


def cmd_set_intensity(intensity_byte: int) -> bytearray:
    # Ensure intensity is within byte range
    intensity = max(0, min(255, intensity_byte))
    return create_command(CommandIds.PRINT_INTENSITY, bytes([intensity]))


def cmd_print_request(line_count: int, mode: int = PrintModes.MONOCHROME) -> bytearray:
    # line_count is the number of image rows (pixels height)
    # mode should be PrintModes.MONOCHROME or PrintModes.GRAYSCALE
    line_count_le = line_count.to_bytes(2, "little")
    # Payload format: [line_count_le(2 bytes), 0x30, print_mode(1 byte)]
    data = bytearray(line_count_le)
    data.append(0x30)
    data.append(mode & 0xFF)
    return create_command(CommandIds.PRINT, bytes(data))


def cmd_flush() -> bytearray:
    return create_command(CommandIds.PRINT_DATA_FLUSH, bytes([0x00]))


# Add others like cmd_get_version(), cmd_get_battery() if needed later


def encode_1bpp_row(image_row_bool: np.ndarray) -> bytearray:
    """
    Encodes a single row of 384 boolean pixels (True=Black) into 48 bytes.
    LSB corresponds to the leftmost pixel in each 8-pixel chunk.
    """
    if len(image_row_bool) != PRINTER_WIDTH_PIXELS:
        raise ValueError(
            f"Image row length must be {PRINTER_WIDTH_PIXELS}, got {len(image_row_bool)}"
        )

    row_data = bytearray(PRINTER_WIDTH_BYTES)
    for byte_idx in range(PRINTER_WIDTH_BYTES):
        byte_val = 0
        for bit_idx in range(8):
            pixel_idx = byte_idx * 8 + bit_idx
            # In numpy boolean array, True means black (needs to set bit)
            if image_row_bool[pixel_idx]:
                byte_val |= 1 << bit_idx
        row_data[byte_idx] = byte_val
    return row_data


def prepare_image_data_buffer(image_rows_bool: np.ndarray) -> bytearray:
    """
    Encodes all image rows and pads the resulting buffer if needed.
    Input: 2D numpy boolean array (height x 384), True=Black.
    """
    height, width = image_rows_bool.shape
    if width != PRINTER_WIDTH_PIXELS:
        raise ValueError(f"Image width must be {PRINTER_WIDTH_PIXELS}, got {width}")

    buffer = bytearray()
    for y in range(height):
        row_bytes = encode_1bpp_row(image_rows_bool[y, :])
        buffer.extend(row_bytes)

    # --- Padding Logic ---
    if len(buffer) < MIN_DATA_BYTES:
        padding_needed = MIN_DATA_BYTES - len(buffer)
        logger.info(
            f"Image data buffer ({len(buffer)} bytes) is smaller than minimum ({MIN_DATA_BYTES} bytes). Adding {padding_needed} bytes of padding."
        )
        buffer.extend(bytearray(padding_needed))  # Pad with 0x00 bytes

    return buffer
