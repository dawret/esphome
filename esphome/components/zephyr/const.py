from typing import Final

import esphome.codegen as cg

BOOTLOADER_MCUBOOT = "mcuboot"

KEY_BOOTLOADER: Final = "bootloader"
KEY_EXTRA_BUILD_FILES: Final = "extra_build_files"
KEY_OVERLAYS: Final = "overlays"
KEY_PM_STATIC: Final = "pm_static"
KEY_PRJ_CONF: Final = "prj.conf"
KEY_SYSBUILD_CONF: Final = "sysbuild.conf"
KEY_CONF_FILES: Final = "conf_files"
KEY_ZEPHYR = "zephyr"
KEY_BOARD: Final = "board"
KEY_USER: Final = "user"

zephyr_ns = cg.esphome_ns.namespace("zephyr")
