from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import textwrap

from esphome import pins
import esphome.codegen as cg
from esphome.components.zephyr import (
    copy_files as zephyr_copy_files,
    zephyr_add_default_partitions,
    zephyr_add_prj_conf,
    zephyr_data,
    zephyr_overlay,
    zephyr_set_core_data,
    zephyr_setup_preferences,
    zephyr_to_code,
    zephyr_validate,
)
from esphome.components.zephyr.const import (
    KEY_BOARD,
    KEY_FLASH_PRIMARY,
    KEY_PARTITIONS,
    KEY_ZEPHYR,
)
import esphome.config_validation as cv
from esphome.const import (
    CONF_BOARD,
    CONF_COMPONENTS,
    CONF_FRAMEWORK,
    CONF_ID,
    CONF_NAME,
    CONF_RESET_PIN,
    CONF_SIZE,
    CONF_SOURCE,
    CONF_TYPE,
    CONF_VERSION,
    CONF_VOLTAGE,
    KEY_CORE,
    KEY_FRAMEWORK_VERSION,
    KEY_TARGET_FRAMEWORK,
    KEY_TARGET_PLATFORM,
    PLATFORM_NRF52,
    ThreadModel,
)
from esphome.core import CORE, CoroPriority, EsphomeError, coroutine_with_priority
from esphome.storage_json import StorageJSON
from esphome.types import ConfigType

from .boards import BOARDS, BOOTLOADER_PARTITION_MAP, FLASH_SIZE_MAP, Nrf52Board
from .const import (
    BOOTLOADER_ADAFRUIT_UF2_V6,
    BOOTLOADER_ADAFRUIT_UF2_V7,
    BOOTLOADER_MCUBOOT,
    BOOTLOADER_NONE,
    BOOTLOADER_NORDIC,
    CONF_BOOTLOADER,
    CONF_BOOTLOADERS,
    CONF_EXT_FLASH,
    CONF_FLASH_SIZE,
    CONF_LABEL,
    CONF_MCU,
    CONF_PARTITIONS,
    MCU_FAMILY_NRF52,
    MCU_FAMILY_NRF54,
)

# force import gpio to register pin schema
from .gpio import nrf52_pin_to_code  # noqa

CODEOWNERS = ["@tomaszduda23"]
AUTO_LOAD = ["zephyr", "preferences"]
IS_TARGET_PLATFORM = True
_LOGGER = logging.getLogger(__name__)


def _set_platform(config: ConfigType) -> ConfigType:
    CORE.data[KEY_CORE][KEY_TARGET_PLATFORM] = PLATFORM_NRF52
    return config


def _get_board_info(config):
    board_config = config[CONF_BOARD]
    board_id = board_config[CONF_NAME]
    if "/" in board_id:
        board_id = board_id.split("/")[0]
    board_info = BOARDS[board_id].copy()
    board_info[CONF_ID] = board_id
    board_info[CONF_NAME] = board_config[CONF_NAME]
    if CONF_FLASH_SIZE in board_config:
        board_info[CONF_FLASH_SIZE] = board_config[CONF_FLASH_SIZE]
    else:
        board_info[CONF_FLASH_SIZE] = FLASH_SIZE_MAP[board_info[CONF_MCU]]
    if CONF_EXT_FLASH in board_config:
        board_info[CONF_EXT_FLASH] = board_config[CONF_EXT_FLASH]

    return board_info


def _validate_bootloaders(config):
    if CONF_BOOTLOADERS in config:
        bootloaders = config[CONF_BOOTLOADERS]
        if len(bootloaders) > 2:
            raise cv.Invalid("A maximum of two bootloaders can be specified")
        if len(bootloaders) == 2 and BOOTLOADER_MCUBOOT not in bootloaders:
            raise cv.Invalid("Only MCUBoot is allowed as a second bootloader")
    elif CONF_BOOTLOADER in config:
        bootloader = config.pop(CONF_BOOTLOADER)
        config[CONF_BOOTLOADERS] = [bootloader]

    return config


def _set_core_data(config):
    CORE.data[KEY_CORE][KEY_TARGET_PLATFORM] = PLATFORM_NRF52
    CORE.data[KEY_CORE][KEY_TARGET_FRAMEWORK] = KEY_ZEPHYR
    CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION] = cv.Version.parse(
        config[CONF_FRAMEWORK][CONF_VERSION]
    )
    info = _get_board_info(config)
    mcuboot = False
    if CONF_BOOTLOADERS in config:
        conf_bootloaders = config[CONF_BOOTLOADERS].copy()
        if BOOTLOADER_MCUBOOT in conf_bootloaders:
            conf_bootloaders.remove(BOOTLOADER_MCUBOOT)
            mcuboot = True
        if len(conf_bootloaders) == 1:
            bootloader = conf_bootloaders[0]
            if bootloader == BOOTLOADER_NONE:
                info[CONF_BOOTLOADER] = None
            elif bootloader in BOOTLOADER_PARTITION_MAP:
                info[CONF_BOOTLOADER] = {
                    CONF_TYPE: bootloader,
                    CONF_PARTITIONS: BOOTLOADER_PARTITION_MAP[bootloader],
                }
            else:
                raise cv.Invalid(f"Invalid first-stage bootloader: {bootloader}")

    board = Nrf52Board.from_dict(info)
    zephyr_set_core_data(config, board=board, mcuboot=mcuboot)

    if board.bootloader and board.bootloader[CONF_TYPE] != BOOTLOADER_MCUBOOT:
        for p in board.bootloader[CONF_PARTITIONS]:
            zephyr_data()[KEY_PARTITIONS][KEY_FLASH_PRIMARY].add(
                p["name"], p["address"], p["size"]
            )

    zephyr_add_default_partitions()

    return config


BOOTLOADERS = [
    BOOTLOADER_ADAFRUIT_UF2_V6,
    BOOTLOADER_ADAFRUIT_UF2_V7,
    BOOTLOADER_MCUBOOT,
    BOOTLOADER_NONE,
    BOOTLOADER_NORDIC,
]

nrf52_ns = cg.esphome_ns.namespace("nrf52")
DeviceFirmwareUpdate = nrf52_ns.class_("DeviceFirmwareUpdate", cg.Component)

CONF_DFU = "dfu"
CONF_DCDC = "dcdc"
CONF_REG0 = "reg0"
CONF_UICR_ERASE = "uicr_erase"

VOLTAGE_LEVELS = [1.8, 2.1, 2.4, 2.7, 3.0, 3.3]

PLATFORM_RECOMMENDED_SOURCE = (
    "https://github.com/dawret/platform-nordicnrf52/archive/refs/tags/v11.1.2.tar.gz"
)
PLATFORM_RECOMMENDED_SDK_VERSION = "2.9.2"


def _validate_framework_config(config: ConfigType) -> ConfigType:
    """Validate the framework configuration."""
    config = config.copy()
    if config[CONF_SOURCE] == "recommended":
        config[CONF_SOURCE] = PLATFORM_RECOMMENDED_SOURCE
    if config[CONF_VERSION] == "recommended":
        config[CONF_VERSION] = PLATFORM_RECOMMENDED_SDK_VERSION

    components = config.get(CONF_COMPONENTS, [])
    config[CONF_COMPONENTS] = [f"{c[CONF_NAME]}@{c[CONF_SOURCE]}" for c in components]
    return config


FRAMEWORK_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.Optional(CONF_SOURCE, default="recommended"): cv.string_strict,
            cv.Optional(CONF_VERSION, default="recommended"): cv.string_strict,
            cv.Optional(CONF_COMPONENTS, default=[]): cv.ensure_list(
                cv.Schema(
                    {
                        cv.Required(CONF_NAME): cv.string_strict,
                        cv.Optional(
                            CONF_SOURCE, default="recommended"
                        ): cv.string_strict,
                    }
                )
            ),
        }
    ),
    _validate_framework_config,
)


def _validate_board(config: ConfigType) -> ConfigType:
    return config


def _parse_shorthand_board(value: str) -> ConfigType:
    return {CONF_NAME: value}


BOARD_SCHEMA = cv.All(
    cv.Any(
        cv.All(cv.string_strict, _parse_shorthand_board),
        cv.Schema(
            {
                cv.Required(CONF_NAME): cv.string_strict,
                cv.Optional(CONF_EXT_FLASH): cv.Schema(
                    {
                        cv.Required(CONF_LABEL): cv.string_strict,
                        cv.Required(CONF_SIZE): cv.hex_int,
                    }
                ),
                cv.Optional(CONF_FLASH_SIZE): cv.hex_int,
            }
        ),
    ),
    _validate_board,
)

CONFIG_SCHEMA = cv.All(
    _set_platform,
    cv.Schema(
        {
            cv.Required(CONF_BOARD): BOARD_SCHEMA,
            cv.Optional(CONF_BOOTLOADER): cv.one_of(*BOOTLOADERS, lower=True),
            cv.Optional(CONF_BOOTLOADERS): cv.ensure_list(
                cv.one_of(*BOOTLOADERS, lower=True)
            ),
            cv.Optional(CONF_DFU): cv.Schema(
                {
                    cv.GenerateID(): cv.declare_id(DeviceFirmwareUpdate),
                    cv.Required(CONF_RESET_PIN): pins.gpio_output_pin_schema,
                }
            ),
            cv.Optional(CONF_DCDC, default=True): cv.boolean,
            cv.Optional(CONF_REG0): cv.Schema(
                {
                    cv.Required(CONF_VOLTAGE): cv.All(
                        cv.voltage,
                        cv.one_of(*VOLTAGE_LEVELS, float=True),
                    ),
                    cv.Optional(CONF_UICR_ERASE, default=False): cv.boolean,
                }
            ),
            cv.Optional(CONF_FRAMEWORK, default={}): FRAMEWORK_SCHEMA,
        }
    ),
    cv.has_at_most_one_key((CONF_BOOTLOADER, CONF_BOOTLOADERS)),
    _validate_bootloaders,
    _set_core_data,
)


def _validate_dfu():
    bootloader = zephyr_data()[KEY_BOARD].bootloader
    if not bootloader:
        raise cv.Invalid("DFU requires a bootloader to be configured")
    if bootloader[CONF_TYPE] not in (
        BOOTLOADER_ADAFRUIT_UF2_V6,
        BOOTLOADER_ADAFRUIT_UF2_V7,
        BOOTLOADER_NORDIC,
    ):
        raise cv.Invalid(f"'{bootloader[CONF_TYPE]}' bootloader does not support DFU")


def _final_validate(config):
    zephyr_validate(config)
    zephyr_data()[KEY_PARTITIONS][KEY_FLASH_PRIMARY].validate()
    if CONF_DFU in config:
        _validate_dfu()

    return config


FINAL_VALIDATE_SCHEMA = _final_validate


@coroutine_with_priority(CoroPriority.PLATFORM)
async def to_code(config: ConfigType) -> None:
    """Convert the configuration to code."""
    board = zephyr_data()[KEY_BOARD]
    cg.add_platformio_option("board", board.id)
    cg.add_platformio_option(
        KEY_FRAMEWORK_VERSION, CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]
    )
    cg.add_build_flag("-DUSE_NRF52")
    cg.add_define("ESPHOME_BOARD", board.id)
    cg.add_define("ESPHOME_VARIANT", board.mcu)
    # nRF52 processors are single-core
    cg.add_define(ThreadModel.SINGLE)
    cg.add_platformio_option(CONF_FRAMEWORK, CORE.data[KEY_CORE][KEY_TARGET_FRAMEWORK])
    conf = config[CONF_FRAMEWORK]
    cg.add_platformio_option(
        "platform",
        conf[CONF_SOURCE],
    )
    if CONF_COMPONENTS in conf:
        cg.add_platformio_option(
            "platform_packages",
            conf[CONF_COMPONENTS],
        )

    if board.bootloader and board.bootloader[CONF_TYPE] == BOOTLOADER_MCUBOOT:
        cg.add_define("USE_BOOTLOADER_MCUBOOT")

    if board.bootloader and board.bootloader[CONF_TYPE] in (
        BOOTLOADER_ADAFRUIT_UF2_V7,
        BOOTLOADER_ADAFRUIT_UF2_V6,
    ):
        # make sure that firmware.zip is created
        # for Adafruit_nRF52_Bootloader
        cg.add_platformio_option("board_upload.protocol", "nrfutil")
        cg.add_platformio_option("board_upload.use_1200bps_touch", "true")
        cg.add_platformio_option("board_upload.require_upload_port", "true")
        cg.add_platformio_option("board_upload.wait_for_upload_port", "true")

    zephyr_setup_preferences()
    zephyr_to_code(config)

    if dfu_config := config.get(CONF_DFU):
        CORE.add_job(_dfu_to_code, dfu_config)
    framework_ver: cv.Version = CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]

    if board.mcu in MCU_FAMILY_NRF52:
        if framework_ver < cv.Version(2, 9, 2):
            zephyr_add_prj_conf("BOARD_ENABLE_DCDC", config[CONF_DCDC])
        else:
            zephyr_overlay().node("reg1").add_property(
                "regulator-initial-mode",
                f"<{'NRF5X_REG_MODE_DCDC' if config[CONF_DCDC] else 'NRF5X_REG_MODE_LDO'}>",
            )

        if reg0_config := config.get(CONF_REG0):
            value = VOLTAGE_LEVELS.index(reg0_config[CONF_VOLTAGE])
            cg.add_define("USE_NRF52_REG0_VOUT", value)
            if reg0_config[CONF_UICR_ERASE]:
                cg.add_define("USE_NRF52_UICR_ERASE")

            # use NFC pins as GPIO
            if framework_ver < cv.Version(2, 9, 2):
                zephyr_add_prj_conf("NFCT_PINS_AS_GPIOS", True)
            else:
                zephyr_overlay().node("uicr").add_property("nfct-pins-as-gpios")

    if board.mcu in MCU_FAMILY_NRF54:
        zephyr_overlay().node("wdt31").add_property("status", '"okay"')

    framework_ver: cv.Version = CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]
    # c++ support
    if framework_ver < cv.Version(2, 9, 2):
        zephyr_add_prj_conf("CPLUSPLUS", True)
        zephyr_add_prj_conf("LIB_CPLUSPLUS", True)
    else:
        zephyr_add_prj_conf("CPP", True)
        zephyr_add_prj_conf("REQUIRES_FULL_LIBCPP", True)
    # watchdog
    zephyr_add_prj_conf("WATCHDOG", True)
    zephyr_add_prj_conf("WDT_DISABLE_AT_BOOT", False)
    # disable console
    zephyr_add_prj_conf("UART_CONSOLE", False)
    zephyr_add_prj_conf("CONSOLE", False)


@coroutine_with_priority(CoroPriority.DIAGNOSTICS)
async def _dfu_to_code(dfu_config):
    cg.add_define("USE_NRF52_DFU")
    var = cg.new_Pvariable(dfu_config[CONF_ID])
    pin = await cg.gpio_pin_expression(dfu_config[CONF_RESET_PIN])
    cg.add(var.set_reset_pin(pin))
    zephyr_add_prj_conf("CDC_ACM_DTE_RATE_CALLBACK_SUPPORT", True)
    await cg.register_component(var, dfu_config)


def copy_files() -> None:
    """Copy files to the build directory."""
    zephyr_copy_files()


def get_download_types(storage_json: StorageJSON) -> list[dict[str, str]]:
    """Get the download types for the firmware."""
    types = []
    UF2_PATH = "merged.uf2"
    DFU_PATH = "merged.zip"
    HEX_PATH = "merged.hex"
    APP_IMAGE_PATH = "zephyr/app_update.bin"
    build_dir = Path(storage_json.firmware_bin_path).parent
    if (build_dir / UF2_PATH).is_file():
        types = [
            {
                "title": "UF2 package (recommended)",
                "description": textwrap.dedent(
                    """\
                    For flashing via Adafruit nRF52 Bootloader as a flash drive.

                    To flash, either copy the UF2 file to the mounted drive,
                    or run esphome upload --host [uf2|<drive_path>] <config.yaml>.
                    When using --host uf2, the drive will be auto-detected.
                """
                ),
                "file": UF2_PATH,
                "download": f"{storage_json.name}.uf2",
            }
        ]
    if (build_dir / DFU_PATH).is_file():
        types += [
            {
                "title": "DFU package",
                "description": textwrap.dedent(
                    """\
                    For flashing via adafruit-nrfutil or nordic-nrfutil using USB CDC.

                    To flash, run esphome upload <config.yaml> or esphome upload --host <serial_port> <config.yaml>.
                """
                ),
                "file": DFU_PATH,
                "download": f"dfu-{storage_json.name}.zip",
            },
        ]
    if (build_dir / HEX_PATH).is_file():
        types += [
            {
                "title": "HEX package",
                "description": textwrap.dedent(
                    """\
                    For flashing via pyocd using SWD.

                    To flash, run esphome upload --host swd <config.yaml>.
                """
                ),
                "file": (HEX_PATH),
                "download": f"{storage_json.name}.hex",
            },
        ]
    if (build_dir / APP_IMAGE_PATH).is_file():
        types += [
            {
                "title": "App update package",
                "description": "For flashing via mcumgr-web using BLE or smpclient using USB CDC.",
                "file": APP_IMAGE_PATH,
                "download": f"app-{storage_json.name}.img",
            },
        ]

    return types


def _find_uf2_partitions():
    import psutil

    uf2_devices = {}
    for partition in psutil.disk_partitions():
        if "fstype" in partition and partition.fstype == "":
            continue

        mount_point = partition.mountpoint
        device = partition.device

        info_path = Path(mount_point) / "INFO_UF2.TXT"

        try:
            if info_path.is_file():
                if device in uf2_devices:
                    if len(uf2_devices[device]) > len(mount_point):
                        uf2_devices[device] = mount_point
                else:
                    uf2_devices[device] = mount_point
        except (OSError, PermissionError):
            continue

    return list(uf2_devices.values())


def _get_upload_host(config: ConfigType, host: str) -> str | None:
    from esphome.__main__ import check_permissions, choose_prompt, get_port_type

    if host in ("swd", "pyocd"):
        return host
    if host == "uf2":
        devices = _find_uf2_partitions()
        if not devices:
            return None
        if len(devices) > 1:
            host = choose_prompt([(d, d) for d in devices], purpose="upload")
        else:
            host = devices[0]
        return host
    if get_port_type(host) == "SERIAL":
        check_permissions(host)
        return host
    return None


def _upload_using_platformio(
    config: ConfigType, port: str, upload_args: list[str]
) -> int | str:
    from esphome import platformio_api

    if port is not None:
        upload_args += ["--upload-port", port]
    return platformio_api.run_platformio_cli_run(config, CORE.verbose, *upload_args)


def upload_program(config: ConfigType, args, host: str) -> bool:
    print(f"Uploading to nrf52 via {host} ({args=})")

    pio_host = _get_upload_host(config, host)
    if not pio_host:
        return False

    if host == "pyocd":
        result = _upload_using_platformio(config, host, ["-t", "flash_pyocd"])

    result = _upload_using_platformio(
        config,
        pio_host,
        ["-t", "upload"],
    )

    if result != 0:
        raise EsphomeError(f"Upload failed with result: {result}")

    return True


def show_logs(config: ConfigType, args, devices: list[str]) -> bool:
    address = devices[0]
    from .ble_logger import is_mac_address, logger_connect, logger_scan

    if devices[0] == "BLE":
        ble_device = asyncio.run(logger_scan(CORE.config["esphome"]["name"]))
        if ble_device:
            address = ble_device.address
        else:
            return True

    if is_mac_address(address):
        asyncio.run(logger_connect(address))
        return True
    return False
