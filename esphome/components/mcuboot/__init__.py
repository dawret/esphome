from __future__ import annotations
from pathlib import Path

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.core import CoroPriority, coroutine_with_priority
from esphome.types import ConfigType
from esphome.components.zephyr import (
    Section,
    zephyr_add_pm_static,
    zephyr_add_prj_conf,
    zephyr_add_sysbuild_conf,
    zephyr_add_conf,
    zephyr_add_module,
    PrjConfValueType,
)

CODEOWNERS = ["@dawret"]
AUTO_LOAD = []

CONFIG_SCHEMA = cv.Schema({}).extend(cv.COMPONENT_SCHEMA)


def zephyr_add_mcuboot_conf(name: str, value: PrjConfValueType):
    zephyr_add_conf(Path("sysbuild/mcuboot.conf"), name, value)

@coroutine_with_priority(CoroPriority.PLATFORM)
async def to_code(config: ConfigType) -> None:
    print("mcuboot to_code")
    zephyr_add_module("mcuboot")
    zephyr_add_module("zcbor")
    cg.add_platformio_option("sysbuild", True)
    cg.add_define("USE_BOOTLOADER_MCUBOOT")
    zephyr_add_pm_static(
        [
            Section("mcuboot", 0x1000, 0x10000, "flash_primary"),
            Section("nrf5_mbr", 0x0000, 0x1000, "flash_primary"),
            Section("storage_partition", 0xb0000, 0x28000, "flash_primary"),
        ]
    )

    # mcuboot config
    zephyr_add_mcuboot_conf("CONFIG_BOOT_ENCRYPT_IMAGE", False)
    #zephyr_add_mcuboot_conf(
    #    "CONFIG_PM_PARTITION_SIZE_MCUBOOT", 0x12000
    #)  # TODO: Calculate the required size based on enabled features
    #zephyr_add_mcuboot_conf("CONFIG_NRF_APPROTECT_LOCK", False)
    #zephyr_add_mcuboot_conf("CONFIG_NRF_APPROTECT_USE_UICR", False)
    #zephyr_add_mcuboot_conf("CONFIG_LOG", True)
    #zephyr_add_mcuboot_conf("CONFIG_FPROTECT", False)
    #zephyr_add_mcuboot_conf("CONFIG_MCUBOOT_SERIAL", True)
    #zephyr_add_mcuboot_conf("CONFIG_MCUBOOT_LOG_LEVEL_INF", True)
    #zephyr_add_mcuboot_conf("CONFIG_BOOT_SERIAL_UART", False)
    #zephyr_add_mcuboot_conf("CONFIG_BOOT_SERIAL_CDC_ACM", True)
    #zephyr_add_mcuboot_conf("CONFIG_UART_CONSOLE", True)

    # sysbuild config
    zephyr_add_sysbuild_conf("SB_CONFIG_BOOTLOADER_MCUBOOT", True)
    zephyr_add_sysbuild_conf("SB_CONFIG_BOOT_SIGNATURE_TYPE_NONE", True)
    zephyr_add_sysbuild_conf("SB_CONFIG_BOOT_SIGNATURE_KEY_FILE", "")

    # app config
    zephyr_add_prj_conf("CONFIG_BOOTLOADER_MCUBOOT", True)
    zephyr_add_prj_conf("CONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE", True)
    zephyr_add_prj_conf("CONFIG_NET_BUF", True)
    zephyr_add_prj_conf("CONFIG_ZCBOR", True)
    zephyr_add_prj_conf("CONFIG_CRC", True)
    zephyr_add_prj_conf("CONFIG_MCUMGR", True)
    zephyr_add_prj_conf("CONFIG_STREAM_FLASH", True)
    zephyr_add_prj_conf("CONFIG_FLASH_MAP", True)
    zephyr_add_prj_conf("CONFIG_FLASH", True)
    zephyr_add_prj_conf("CONFIG_THREAD_MONITOR", True)
    zephyr_add_prj_conf("CONFIG_MCUMGR_GRP_OS_TASKSTAT", True)

    zephyr_add_prj_conf("CONFIG_STATS", True)
    zephyr_add_prj_conf("CONFIG_STATS_NAMES", True)
    zephyr_add_prj_conf("CONFIG_IMG_MANAGER", True)
    zephyr_add_prj_conf("CONFIG_MCUMGR_GRP_IMG", True)
    zephyr_add_prj_conf("CONFIG_MCUMGR_GRP_OS", True)
    zephyr_add_prj_conf("CONFIG_MCUMGR_GRP_STAT", True)
    zephyr_add_prj_conf("CONFIG_MCUBOOT_UTIL_LOG_LEVEL_WRN", True)
    zephyr_add_prj_conf("CONFIG_MCUMGR_TRANSPORT_UART", True)
    zephyr_add_prj_conf("CONFIG_BASE64", True)
