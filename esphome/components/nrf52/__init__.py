from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import textwrap

from esphome import pins
import esphome.codegen as cg
from esphome.components.zephyr import (
    Section,
    copy_files as zephyr_copy_files,
    zephyr_add_conf,
    zephyr_add_pm_static,
    zephyr_add_prj_conf,
    zephyr_add_sysbuild_conf,
    zephyr_data,
    zephyr_overlay,
    zephyr_set_core_data,
    zephyr_setup_preferences,
    zephyr_to_code,
)
from esphome.components.zephyr.const import (
    CONF_BOARD_FULL,
    KEY_BOARD,
    KEY_BOOTLOADERS,
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

from .boards import BOARDS_ZEPHYR
from .const import (
    BOOTLOADER_ADAFRUIT,
    BOOTLOADER_ADAFRUIT_NRF52_SD132,
    BOOTLOADER_ADAFRUIT_NRF52_SD140_V6,
    BOOTLOADER_ADAFRUIT_NRF52_SD140_V7,
    BOOTLOADER_MCUBOOT,
    BOOTLOADER_NORDIC,
)

# force import gpio to register pin schema
from .gpio import nrf52_pin_to_code  # noqa

CODEOWNERS = ["@tomaszduda23"]
AUTO_LOAD = ["zephyr", "preferences"]
IS_TARGET_PLATFORM = True
_LOGGER = logging.getLogger(__name__)


def set_platform(config: ConfigType) -> ConfigType:
    CORE.data[KEY_CORE][KEY_TARGET_PLATFORM] = PLATFORM_NRF52
    return config


def set_core_data(config: ConfigType) -> ConfigType:
    zephyr_set_core_data(config)
    CORE.data[KEY_CORE][KEY_TARGET_PLATFORM] = PLATFORM_NRF52
    CORE.data[KEY_CORE][KEY_TARGET_FRAMEWORK] = KEY_ZEPHYR
    CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION] = cv.Version.parse(
        config[CONF_FRAMEWORK][CONF_VERSION]
    )

    sections = _get_bootloader_partitions(config)
    zephyr_add_pm_static(sections)

    return config


BOOTLOADERS = [
    BOOTLOADER_ADAFRUIT,
    BOOTLOADER_MCUBOOT,
    BOOTLOADER_NORDIC,
]


nrf52_ns = cg.esphome_ns.namespace("nrf52")
DeviceFirmwareUpdate = nrf52_ns.class_("DeviceFirmwareUpdate", cg.Component)

CONF_DFU = "dfu"
CONF_DCDC = "dcdc"
CONF_REG0 = "reg0"
CONF_UICR_ERASE = "uicr_erase"
CONF_SOFTDEVICE_VERSION = "softdevice_version"
CONF_SOFTDEVICE_MODEL = "softdevice_model"
CONF_FLASH_START_SIZE = "flash_start_size"
CONF_FLASH_END_SIZE = "flash_end_size"
CONF_BOOTLOADERS = "bootloaders"
CONF_BOOTLOADER = "bootloader"

VOLTAGE_LEVELS = [1.8, 2.1, 2.4, 2.7, 3.0, 3.3]

# Adafruit bootloader flash partition sizes
ADAFRUIT_FLASH_START_SIZE_SD140_V7 = 0x27000
ADAFRUIT_FLASH_START_SIZE_SD140_V6_SD132 = 0x26000
ADAFRUIT_FLASH_START_SIZE_DEFAULT = 0x19000
ADAFRUIT_FLASH_END_SIZE = 0xC000

# Nordic bootloader flash partition sizes
NORDIC_FLASH_START_SIZE = 0x1000
NORDIC_FLASH_END_SIZE = 0x20000

# MCUboot flash partition sizes (no reserved regions)
MCUBOOT_FLASH_START_SIZE = 0x0
MCUBOOT_FLASH_END_SIZE = 0x0

PLATFORM_RECOMMENDED_SOURCE = (
    "https://github.com/dawret/platform-nordicnrf52/archive/refs/tags/v11.1.1.tar.gz"
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


def _validate_bootloader(config: ConfigType) -> ConfigType:
    btype = config.get(CONF_TYPE)

    if btype == "adafruit":
        if not all(
            (CONF_SOFTDEVICE_MODEL in config, CONF_SOFTDEVICE_VERSION in config)
        ):
            raise cv.Invalid(
                "Adafruit bootloader requires both 'softdevice_model' and 'softdevice_version' to be set. You can find them in INFO_UF2.TXT"
            )
        if not config[CONF_FLASH_START_SIZE]:
            sd_ver = config[CONF_SOFTDEVICE_VERSION]
            sd_model = config[CONF_SOFTDEVICE_MODEL]
            if sd_model == 140 and sd_ver == 7:
                config[CONF_FLASH_START_SIZE] = ADAFRUIT_FLASH_START_SIZE_SD140_V7
            elif sd_ver == 6 and sd_model in (132, 140):
                config[CONF_FLASH_START_SIZE] = ADAFRUIT_FLASH_START_SIZE_SD140_V6_SD132
            else:
                config[CONF_FLASH_START_SIZE] = ADAFRUIT_FLASH_START_SIZE_DEFAULT
        if not config[CONF_FLASH_END_SIZE]:
            config[CONF_FLASH_END_SIZE] = ADAFRUIT_FLASH_END_SIZE
    elif btype == "nordic":
        if not config[CONF_FLASH_START_SIZE]:
            config[CONF_FLASH_START_SIZE] = NORDIC_FLASH_START_SIZE
        if not config[CONF_FLASH_END_SIZE]:
            config[CONF_FLASH_END_SIZE] = NORDIC_FLASH_END_SIZE

    return config


def _get_default_bootloader_for_board(config: ConfigType) -> str:
    print(f"Getting default bootloader for board {config[CONF_BOARD]}")
    if config[CONF_BOARD] in BOARDS_ZEPHYR:
        return BOARDS_ZEPHYR[config[CONF_BOARD]]
    if "adafruit" in config[CONF_BOARD].lower():
        _LOGGER.warning(
            "Assuming Adafruit bootloader SoftDevice S140 V6 for Adafruit board. Check if this is correct and set manually if needed"
        )
        return BOOTLOADER_ADAFRUIT_NRF52_SD140_V6
    return BOOTLOADER_MCUBOOT


def _validate_bootloaders(config: ConfigType) -> ConfigType:
    if all((CONF_BOOTLOADERS in config, CONF_BOOTLOADER in config)):
        raise cv.Invalid(
            f"Cannot specify both '{CONF_BOOTLOADERS}' and '{CONF_BOOTLOADER}'"
        )
    if CONF_BOOTLOADERS not in config:
        config[CONF_BOOTLOADERS] = [
            config.get(
                CONF_BOOTLOADER,
                _parse_shorthand_bootloader(_get_default_bootloader_for_board(config)),
            )
        ]
    if len(config[CONF_BOOTLOADERS]) > 1:
        raise cv.Invalid("Multiple bootloaders are not supported yet.")
    return config


def _parse_shorthand_bootloader(value: str) -> ConfigType:
    if value.startswith("adafruit"):
        if value == BOOTLOADER_ADAFRUIT_NRF52_SD132:
            return {
                CONF_TYPE: BOOTLOADER_ADAFRUIT,
                CONF_SOFTDEVICE_MODEL: 132,
                CONF_SOFTDEVICE_VERSION: 6,
                CONF_FLASH_START_SIZE: ADAFRUIT_FLASH_START_SIZE_SD140_V6_SD132,
                CONF_FLASH_END_SIZE: ADAFRUIT_FLASH_END_SIZE,
            }
        if value == BOOTLOADER_ADAFRUIT_NRF52_SD140_V6:
            return {
                CONF_TYPE: BOOTLOADER_ADAFRUIT,
                CONF_SOFTDEVICE_MODEL: 140,
                CONF_SOFTDEVICE_VERSION: 6,
                CONF_FLASH_START_SIZE: ADAFRUIT_FLASH_START_SIZE_SD140_V6_SD132,
                CONF_FLASH_END_SIZE: ADAFRUIT_FLASH_END_SIZE,
            }
        if value == BOOTLOADER_ADAFRUIT_NRF52_SD140_V7:
            return {
                CONF_TYPE: BOOTLOADER_ADAFRUIT,
                CONF_SOFTDEVICE_MODEL: 140,
                CONF_SOFTDEVICE_VERSION: 7,
                CONF_FLASH_START_SIZE: ADAFRUIT_FLASH_START_SIZE_SD140_V7,
                CONF_FLASH_END_SIZE: ADAFRUIT_FLASH_END_SIZE,
            }
        return {CONF_TYPE: BOOTLOADER_ADAFRUIT}
    if value == BOOTLOADER_NORDIC:
        return {
            CONF_TYPE: BOOTLOADER_NORDIC,
            CONF_FLASH_START_SIZE: NORDIC_FLASH_START_SIZE,
            CONF_FLASH_END_SIZE: NORDIC_FLASH_END_SIZE,
        }
    if value == BOOTLOADER_MCUBOOT:
        return {
            CONF_TYPE: BOOTLOADER_MCUBOOT,
            CONF_FLASH_START_SIZE: MCUBOOT_FLASH_START_SIZE,
            CONF_FLASH_END_SIZE: MCUBOOT_FLASH_END_SIZE,
        }
    raise cv.Invalid(f"Unknown bootloader shorthand: {value}")


def _get_bootloader_partitions(config: ConfigType) -> list[Section]:
    sections = []
    bootloader = config[CONF_BOOTLOADERS][0]
    if bootloader[CONF_FLASH_START_SIZE] > 0:
        sections.append(
            Section(
                (
                    "nrf5_mbr"
                    if bootloader[CONF_TYPE] == BOOTLOADER_NORDIC
                    else "bootloader_start_reserved"
                ),
                size=bootloader[CONF_FLASH_START_SIZE],
                region="flash_primary",
                address=0x0,
            )
        )
    if bootloader[CONF_FLASH_END_SIZE] > 0:
        sections.append(
            Section(
                "bootloader_end_reserved",
                size=bootloader[CONF_FLASH_END_SIZE],
                region="flash_primary",
                address=0x100000 - bootloader[CONF_FLASH_END_SIZE],
            )
        )
    return sections


BOOTLOADER_SCHEMA = cv.All(
    cv.Any(
        cv.All(cv.string_strict, _parse_shorthand_bootloader),
        cv.Schema(
            {
                cv.Required(CONF_TYPE): cv.one_of(*BOOTLOADERS, lower=True),
                cv.Optional(CONF_SOFTDEVICE_VERSION): cv.one_of(6, 7),
                cv.Optional(CONF_SOFTDEVICE_MODEL): cv.one_of(112, 132, 140),
                cv.Optional(CONF_FLASH_START_SIZE, default=0x0): cv.hex_int,
                cv.Optional(CONF_FLASH_END_SIZE, default=0x0): cv.hex_int,
            }
        ),
    ),
    _validate_bootloader,
)


def _parse_board_config(config: ConfigType) -> ConfigType:
    """Add full board name to config based on CONF_BOARD."""

    if CONF_BOARD_FULL not in config:
        # Store the full board name (use BOARDS_ZEPHYR if available as reference)
        config[CONF_BOARD_FULL] = config[CONF_BOARD]
        if "/" in config[CONF_BOARD]:
            config[CONF_BOARD] = config[CONF_BOARD].split("/")[0]
    return config


CONFIG_SCHEMA = cv.All(
    set_platform,
    _parse_board_config,
    cv.Schema(
        {
            cv.Required(CONF_BOARD): cv.string_strict,
            cv.Optional(CONF_BOARD_FULL): cv.string_strict,
            cv.Optional(CONF_BOOTLOADER): BOOTLOADER_SCHEMA,
            cv.Optional(CONF_BOOTLOADERS): cv.ensure_list(BOOTLOADER_SCHEMA),
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
    _validate_bootloaders,
    set_core_data,
)


def _validate_mcumgr(config):
    bootloader = zephyr_data()[KEY_BOOTLOADERS][0]
    if bootloader[CONF_TYPE] not in (BOOTLOADER_ADAFRUIT, BOOTLOADER_NORDIC):
        raise cv.Invalid(f"'{bootloader}' bootloader does not support DFU")


def _final_validate(config):
    if CONF_DFU in config:
        _validate_mcumgr(config)


FINAL_VALIDATE_SCHEMA = _final_validate


@coroutine_with_priority(CoroPriority.PLATFORM)
async def to_code(config: ConfigType) -> None:
    """Convert the configuration to code."""
    cg.add_platformio_option("board", zephyr_data()[KEY_BOARD])
    cg.add_platformio_option(
        KEY_FRAMEWORK_VERSION, CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]
    )
    cg.add_build_flag("-DUSE_NRF52")
    cg.add_define("ESPHOME_BOARD", zephyr_data()[KEY_BOARD])
    cg.add_define("ESPHOME_VARIANT", "NRF52")
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

    bootloader = config[CONF_BOOTLOADERS][0]
    if bootloader[CONF_TYPE] == BOOTLOADER_MCUBOOT:
        zephyr_add_prj_conf("CONFIG_BOOTLOADER_MCUBOOT", True)
    elif bootloader[CONF_TYPE] == BOOTLOADER_ADAFRUIT:
        zephyr_add_prj_conf("CONFIG_BUILD_OUTPUT_UF2", True)

    zephyr_add_sysbuild_conf("SB_CONFIG_BOOTLOADER_MCUBOOT", True)
    zephyr_add_sysbuild_conf("SB_CONFIG_BOOT_SIGNATURE_TYPE_NONE", True)
    zephyr_add_sysbuild_conf("SB_CONFIG_MCUBOOT_MODE_OVERWRITE_ONLY", True)
    # zephyr_add_sysbuild_conf("SB_CONFIG_BOOT_SERIAL_CDC_ACM", False)
    zephyr_add_conf(
        Path("sysbuild/mcuboot.conf"), "CONFIG_BOOT_USE_MIN_PARTITION_SIZE", False
    )
    zephyr_add_conf(Path("sysbuild/mcuboot.conf"), "CONFIG_PM", True)
    zephyr_add_conf(Path("sysbuild/mcuboot.conf"), "BOOT_SERIAL_CDC_ACM", False)
    zephyr_add_conf(Path("sysbuild/mcuboot.conf"), "MCUBOOT_SERIAL", False)

    if config[CONF_BOARD] == "xiao_ble":
        zephyr_overlay().node("flash0").add_entry(
            "partitions",
            textwrap.dedent(
                """
                &flash0 {

                    partitions {
                        compatible = "fixed-partitions";
                        #address-cells = <1>;
                        #size-cells = <1>;

                        slot0_partition: partition@c000 {
                            label = "image-0";
                            reg = <0x0000C000 0x00077000>;
                        };
                        slot1_partition: partition@83000 {
                            label = "image-1";
                            reg = <0x00083000 0x00075000>;
                        };
                    };
                };
                """
            ),
        )

    zephyr_setup_preferences()
    zephyr_to_code(config)

    if dfu_config := config.get(CONF_DFU):
        CORE.add_job(_dfu_to_code, dfu_config)
    framework_ver: cv.Version = CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]
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
    # use NFC pins as GPIO
    if framework_ver < cv.Version(2, 9, 2):
        zephyr_add_prj_conf("NFCT_PINS_AS_GPIOS", True)
    else:
        zephyr_overlay().node("uicr").add_property("nfct-pins-as-gpios")


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

    if host == "swd":
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
