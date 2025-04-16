import asyncio
import contextlib
import uuid
from typing import Optional, Dict, Any
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.scanner import AdvertisementData
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from . import cmds
from . import logger

PACING_DELAY_S = 0.015
NOTIFICATION_TIMEOUT_S = 7.0
PRINT_COMPLETE_BASE_TIMEOUT_S = 15.0
PRINT_COMPLETE_LINES_PER_SEC = 15.0

SCAN_TIMEOUT_S = 10

NotificationState = Dict[str, Any]


async def scan(name: Optional[str], timeout: int):
    autodiscover = not name
    if autodiscover:
        logger.info("⏳ Trying to auto-discover a printer (MXW01 Service)...")
        possible_service_uuids = [
            cmds.MAIN_SERVICE_UUID.lower(),
            "0000af30-0000-1000-8000-00805f9b34fb",
        ]
        filter_fn = lambda d, ad: any(
            uuid in [s.lower() for s in ad.service_uuids]
            for uuid in possible_service_uuids
        )
    else:
        logger.info(f"⏳ Looking for a BLE device named {name}...")
        filter_fn = lambda d, ad: d.name == name

    device = await BleakScanner.find_device_by_filter(
        filter_fn,
        timeout=timeout,
    )
    if device is None:
        raise RuntimeError(
            "Unable to find printer, make sure it is turned on and in range"
        )
    logger.info(f"✅ Got it. Address: {device}")
    return device


async def get_device_address(device: Optional[str]):
    if device:
        with contextlib.suppress(ValueError):
            return str(uuid.UUID(device))
        if device.count(":") == 5 and device.replace(":", "").isalnum():
            return device

    return await scan(device, timeout=SCAN_TIMEOUT_S)


def notification_receiver_factory(notification_state: NotificationState):
    async def update_notification_state(cmd_id: int, payload: bytes):
        async with notification_state["condition"]:
            notification_state["received"][cmd_id] = payload
            notification_state["condition"].notify_all()
            logger.debug(f"Notified waiters for command 0x{cmd_id:02X}")

    def notification_receiver(sender: int, data: bytearray):
        # Basic check for header and minimum possible length (header, cmd, fixed, len)
        if len(data) >= 6 and data[0] == 0x22 and data[1] == 0x21:
            cmd_id = data[2]
            try:
                payload_len = int.from_bytes(data[4:6], "little")
                expected_payload_end_idx = 6 + payload_len  # Index after the payload

                # Check if we received AT LEAST enough data for the declared payload
                if len(data) >= expected_payload_end_idx:
                    payload = bytes(data[6:expected_payload_end_idx])

                    # --- Optional: Perform CRC/Footer check only if data is long enough ---
                    expected_total_len = 8 + payload_len  # Includes CRC and Footer
                    if len(data) >= expected_total_len:
                        crc_received = data[expected_payload_end_idx]
                        footer = data[expected_payload_end_idx + 1]
                        crc_calculated = cmds.calculate_crc8(payload)
                        if crc_received != crc_calculated:
                            logger.warning(
                                f"CRC mismatch for 0x{cmd_id:02X}. Got {crc_received:02X}, expected {crc_calculated:02X}. Payload: {payload.hex()}"
                            )
                        if footer != 0xFF:
                            logger.warning(
                                f"Invalid footer for 0x{cmd_id:02X}. Got {footer:02X}, expected FF."
                            )
                    elif len(data) > expected_payload_end_idx:
                        # Data is longer than payload but shorter than full packet
                        logger.warning(
                            f"Notification for 0x{cmd_id:02X} possibly truncated. Length {len(data)}, expected payload end at {expected_payload_end_idx}, expected total {expected_total_len}. Skipping CRC/Footer check."
                        )
                    # else: Data ends exactly after payload, CRC/Footer definitely missing.

                    # --- Process the payload regardless of CRC/Footer issues ---
                    logger.info(
                        f"Received Response ID: 0x{cmd_id:02X}, Payload: {payload.hex()}"
                    )
                    asyncio.create_task(update_notification_state(cmd_id, payload))

                else:
                    # This means we didn't even get the full payload bytes
                    logger.warning(
                        f"Received notification too short for declared payload. Cmd: 0x{cmd_id:02X}, Declared len: {payload_len}, Actual len: {len(data)}, Needed for payload: {expected_payload_end_idx}"
                    )

            except IndexError:
                logger.error(
                    f"Error parsing notification - IndexError. Data: {data.hex()}"
                )
            except Exception as e:
                logger.error(f"Error parsing notification: {e}. Data: {data.hex()}")
        else:
            logger.debug(
                f"Ignoring unexpected/non-MXW01 notification format or too short: {data.hex()}"
            )

    return notification_receiver


async def wait_for_notification(
    notification_state: NotificationState, expected_cmd_id: int, timeout: float
) -> Optional[bytes]:
    async with notification_state["condition"]:
        notification_state["received"].pop(expected_cmd_id, None)
        try:
            await asyncio.wait_for(
                notification_state["condition"].wait_for(
                    lambda: expected_cmd_id in notification_state["received"]
                ),
                timeout=timeout,
            )
            payload = notification_state["received"].pop(expected_cmd_id)
            logger.debug(f"Successfully received notification 0x{expected_cmd_id:02X}")
            return payload
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for notification 0x{expected_cmd_id:02X} after {timeout}s"
            )
            return None


async def run_ble(image_data_buffer: bytes, device: Optional[str], intensity: int):
    address = None
    client = None
    notify_char_uuid = None

    try:
        address = await get_device_address(device)
    except RuntimeError as e:
        logger.error(f"🛑 Printer discovery/address error: {e}")
        return
    except Exception as e:
        logger.error(f"🛑 Unexpected error during device scan: {e}")
        return

    logger.info(f"⏳ Attempting to connect to {address}...")

    notification_state: NotificationState = {
        "received": {},
        "condition": asyncio.Condition(),
    }
    receive_notification = notification_receiver_factory(notification_state)

    try:
        async with BleakClient(address, timeout=20.0) as client:
            logger.info(f"✅ Connected: {client.is_connected}; MTU: {client.mtu_size}")

            control_char = None
            notify_char = None
            data_char = None
            try:
                service = None
                possible_service_uuids = [
                    cmds.MAIN_SERVICE_UUID.lower(),
                    "0000af30-0000-1000-8000-00805f9b34fb",
                ]
                for s in client.services:
                    if s.uuid.lower() in possible_service_uuids:
                        service = s
                        logger.info(f"Found service: {s.uuid}")
                        break
                if not service:
                    raise BleakError(
                        f"Service {cmds.MAIN_SERVICE_UUID} (or alternative) not found."
                    )

                control_char = service.get_characteristic(cmds.CONTROL_WRITE_UUID)
                notify_char = service.get_characteristic(cmds.NOTIFY_UUID)
                data_char = service.get_characteristic(cmds.DATA_WRITE_UUID)
                notify_char_uuid = notify_char.uuid

                if not all([control_char, notify_char, data_char]):
                    missing = [
                        uuid
                        for uuid, char in [
                            (cmds.CONTROL_WRITE_UUID, control_char),
                            (cmds.NOTIFY_UUID, notify_char),
                            (cmds.DATA_WRITE_UUID, data_char),
                        ]
                        if char is None
                    ]
                    raise BleakError(f"Missing required characteristics: {missing}")

                logger.info("✅ Found required characteristics.")

            except BleakError as e:
                logger.error(f"🛑 Error finding service/characteristics: {e}")
                return
            except Exception as e:
                logger.error(f"🛑 Unexpected error getting characteristics: {e}")
                return

            try:
                logger.info(f"Starting notifications on {notify_char.uuid}...")
                await client.start_notify(notify_char.uuid, receive_notification)
                logger.info("✅ Notifications started.")
            except Exception as e:
                logger.error(f"🛑 Failed to start notifications: {e}")
                return

            line_count = len(image_data_buffer) // cmds.PRINTER_WIDTH_BYTES
            logger.info(
                f"Prepared {line_count} lines of image data (including padding if any)."
            )

            logger.info(f"Setting intensity to 0x{intensity:02X}...")
            intensity_cmd = cmds.cmd_set_intensity(intensity)
            await client.write_gatt_char(
                control_char.uuid, intensity_cmd, response=False
            )
            await asyncio.sleep(0.1)

            logger.info("Requesting printer status (A1)...")
            status_cmd = cmds.cmd_get_status()
            await client.write_gatt_char(control_char.uuid, status_cmd, response=False)
            status_payload = await wait_for_notification(
                notification_state, cmds.CommandIds.GET_STATUS, NOTIFICATION_TIMEOUT_S
            )
            if status_payload is None:
                return

            status_ok = False
            if len(status_payload) >= 13:
                is_ok_flag = status_payload[12] == 0
                if is_ok_flag:
                    status_ok = True
                    status_byte = status_payload[6]
                    battery_level = status_payload[9]
                    logger.info(
                        f"Printer Status OK (Flag=0). State: 0x{status_byte:02X}, Battery: {battery_level}%"
                    )
                else:
                    error_byte = 0
                    if len(status_payload) >= 14:
                        error_byte = status_payload[13]
                    logger.error(
                        f"Printer Status Error (Flag!=0). Error code byte: 0x{error_byte:02X}"
                    )
            else:
                logger.error(
                    f"Received A1 status payload is too short ({len(status_payload)} bytes) to parse fully."
                )

            logger.info(f"Sending print request for {line_count} lines (A9)...")
            print_req_cmd = cmds.cmd_print_request(
                line_count, cmds.PrintModes.MONOCHROME
            )
            await client.write_gatt_char(
                control_char.uuid, print_req_cmd, response=False
            )
            print_req_payload = await wait_for_notification(
                notification_state, cmds.CommandIds.PRINT, NOTIFICATION_TIMEOUT_S
            )
            if print_req_payload is None:
                return

            if len(print_req_payload) > 0 and print_req_payload[0] == 0:
                logger.info("✅ Print request accepted (A9 response OK).")
            else:
                logger.error(
                    f"🛑 Printer rejected print request (A9). Payload: {print_req_payload.hex()}. Aborting."
                )
                return

            logger.info(
                f"Sending {len(image_data_buffer)} bytes of image data to {data_char.uuid}..."
            )
            chunk_size = cmds.PRINTER_WIDTH_BYTES
            num_chunks = (len(image_data_buffer) + chunk_size - 1) // chunk_size

            for i in range(0, len(image_data_buffer), chunk_size):
                chunk = image_data_buffer[i : i + chunk_size]
                await client.write_gatt_char(data_char.uuid, chunk, response=False)
                await asyncio.sleep(PACING_DELAY_S)
                current_chunk_num = i // chunk_size + 1
                if current_chunk_num % 50 == 0 or current_chunk_num == num_chunks:
                    logger.debug(f"Sent chunk {current_chunk_num}/{num_chunks}")

            logger.info("✅ Finished sending image data.")

            logger.info("Sending data flush command (AD)...")
            flush_cmd = cmds.cmd_flush()
            await client.write_gatt_char(control_char.uuid, flush_cmd, response=False)
            await asyncio.sleep(0.1)

            print_timeout_duration = PRINT_COMPLETE_BASE_TIMEOUT_S + (
                line_count / PRINT_COMPLETE_LINES_PER_SEC
            )
            logger.info(
                f"Waiting up to {print_timeout_duration:.1f}s for print complete (AA)..."
            )
            completion_payload = await wait_for_notification(
                notification_state,
                cmds.CommandIds.PRINT_COMPLETE,
                print_timeout_duration,
            )

            if completion_payload is None:
                logger.warning(
                    "⚠️ Did not receive print complete notification (AA) within timeout. Print might be finished or still running."
                )
            else:
                logger.info(
                    f"✅ Print Complete notification (AA) received. Payload: {completion_payload.hex()}"
                )
                logger.info(
                    "🎉 Print job successfully sent and acknowledged by printer."
                )

            await asyncio.sleep(1.0)

    except BleakError as e:
        logger.error(f"🛑 Bluetooth Error: {e}")
    except asyncio.TimeoutError:
        logger.error(f"🛑 Connection timed out to {address}")
    except Exception as e:
        logger.error(f"🛑 An unexpected error occurred: {e}", exc_info=True)
    finally:
        if client and client.is_connected:
            if notify_char_uuid:
                try:
                    logger.info("Stopping notifications...")
                    await client.stop_notify(notify_char_uuid)
                except Exception as e:
                    logger.error(f"Error stopping notifications: {e}")
            logger.info("Disconnecting...")
        else:
            logger.info("Client was not connected or already disconnected.")
        logger.info("BLE operation finished.")
