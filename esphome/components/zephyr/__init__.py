from pathlib import Path
import textwrap
from typing import TypedDict, Final

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_BOARD, KEY_CORE, KEY_FRAMEWORK_VERSION
from esphome.core import CORE, CoroPriority, coroutine_with_priority
from esphome.helpers import copy_file_if_changed, write_file_if_changed

from .const import (
    KEY_BOOTLOADER,
    KEY_CONF_FILES,
    KEY_EXTRA_BUILD_FILES,
    KEY_MODULES,
    KEY_OVERLAY,
    KEY_PM_STATIC,
    KEY_PRJ_CONF,
    KEY_SYSBUILD_CONF,
    KEY_USER,
    KEY_ZEPHYR,
    zephyr_ns,
)

CODEOWNERS = ["@tomaszduda23"]
AUTO_LOAD = ["preferences"]

PrjConfValueType = bool | str | int


class Section:
    def __init__(self, name, address, size, region):
        self.name = name
        self.address = address
        self.size = size
        self.region = region
        self.end_address = self.address + self.size

    def __str__(self):
        return (
            f"{self.name}:\n"
            f"  address: 0x{self.address:X}\n"
            f"  end_address: 0x{self.end_address:X}\n"
            f"  region: {self.region}\n"
            f"  size: 0x{self.size:X}"
        )


class ZephyrData(TypedDict):
    board: str
    bootloader: str
    conf_files: dict[Path, dict[str, tuple[PrjConfValueType, bool]]]
    overlay: str
    modules: list[str]
    extra_build_files: dict[str, Path]
    pm_static: list[Section]
    user: dict[str, list[str]]


def zephyr_set_core_data(config):
    CORE.data[KEY_ZEPHYR] = ZephyrData(
        board=config[CONF_BOARD],
        bootloader=config[KEY_BOOTLOADER],
        conf_files={},
        overlay="",
        modules=[],
        extra_build_files={},
        pm_static=[],
        user={},
    )
    return config


def zephyr_add_module(module: str) -> None:
    zephyr_data()[KEY_MODULES].append(module)


def zephyr_data() -> ZephyrData:
    return CORE.data[KEY_ZEPHYR]


def zephyr_conf_file(key: Path) -> dict[str, tuple[PrjConfValueType, bool]]:
    conf_files = zephyr_data()[KEY_CONF_FILES]
    if key not in conf_files:
        conf_files[key] = {}
    return conf_files[key]


def zephyr_add_prj_conf(
    name: str, value: PrjConfValueType, required: bool = True
) -> None:
    zephyr_add_conf(Path(KEY_PRJ_CONF), name, value, required)


def zephyr_add_sysbuild_conf(
    name: str, value: PrjConfValueType, required: bool = True
) -> None:
    zephyr_add_conf(Path(KEY_SYSBUILD_CONF), name, value, required)


def zephyr_add_conf(
    key: Path, name: str, value: PrjConfValueType, required: bool = True
) -> None:
    """Set an zephyr conf value."""
    conf = zephyr_conf_file(key)
    if not name.startswith("CONFIG_") and not name.startswith("SB_CONFIG_"):
        name = "CONFIG_" + name
    if name not in conf:
        conf[name] = (value, required)
        return
    old_value, old_required = conf[name]
    if old_value != value and old_required:
        raise ValueError(
            f"{name} already set with value '{old_value}', cannot set again to '{value}'"
        )
    if required:
        conf[name] = (value, required)


def zephyr_add_overlay(content):
    zephyr_data()[KEY_OVERLAY] += textwrap.dedent(content)


def add_extra_build_file(filename: str, path: Path) -> bool:
    """Add an extra build file to the project."""
    extra_build_files = zephyr_data()[KEY_EXTRA_BUILD_FILES]
    if filename not in extra_build_files:
        extra_build_files[filename] = path
        return True
    return False


def add_extra_script(stage: str, filename: str, path: Path) -> None:
    """Add an extra script to the project."""
    key = f"{stage}:{filename}"
    if add_extra_build_file(filename, path):
        cg.add_platformio_option("extra_scripts", [key])

@coroutine_with_priority(CoroPriority.PLATFORM)
async def to_code(config) -> None:
    print("zephyr to_code")
    cg.add(zephyr_ns.setup_preferences())
    cg.add_build_flag("-DUSE_ZEPHYR")
    # build is done by west so bypass board checking in platformio
    cg.add_platformio_option("boards_dir", CORE.relative_build_path("boards"))

    framework_ver: cv.Version = CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]

    # c++ support
    cg.set_cpp_standard("gnu++20")
    zephyr_add_prj_conf("NEWLIB_LIBC", True)
    zephyr_add_prj_conf("FPU", True)
    zephyr_add_prj_conf("NEWLIB_LIBC_FLOAT_PRINTF", True)
    if framework_ver < cv.Version(3, 2, 0):
        zephyr_add_prj_conf("CPLUSPLUS", True)
        zephyr_add_prj_conf("LIB_CPLUSPLUS", True)
    else:
        zephyr_add_prj_conf("CPP", True)
        zephyr_add_prj_conf("REQUIRES_FULL_LIBCPP", True)
    zephyr_add_prj_conf("STD_CPP20", True)

    # preferences
    zephyr_add_prj_conf("SETTINGS", True)
    zephyr_add_prj_conf("NVS", True)
    zephyr_add_prj_conf("FLASH_MAP", True)
    zephyr_add_prj_conf("CONFIG_FLASH", True)

    # watchdog
    zephyr_add_prj_conf("WATCHDOG", True)
    zephyr_add_prj_conf("WDT_DISABLE_AT_BOOT", False)

    # disable console
    zephyr_add_prj_conf("CONFIG_LOG", True)
    #zephyr_add_prj_conf("UART_CONSOLE", False)
    zephyr_add_prj_conf("CONFIG_SERIAL", True)
    zephyr_add_prj_conf("CONSOLE", True)
    zephyr_add_prj_conf("CONFIG_PRINTK", True)
    #zephyr_add_prj_conf("CONFIG_RTT_CONSOLE", True)
    #zephyr_add_prj_conf("CONFIG_USE_SEGGER_RTT", True)
    zephyr_add_prj_conf("CONFIG_DEBUG_THREAD_INFO", True)
    zephyr_add_prj_conf("CONFIG_DEBUG_OPTIMIZATIONS", True)
    #zephyr_add_prj_conf("CONFIG_LOG", True)
    #zephyr_add_prj_conf("CONFIG_USB_DEVICE_STACK_NEXT", True)
    zephyr_add_prj_conf("CONFIG_USB_CDC_ACM", True)
    #zephyr_add_prj_conf("CONFIG_USB_UART_CONSOLE", True)



    # <err> os: ***** USAGE FAULT *****
    # <err> os:   Illegal load of EXC_RETURN into PC
    zephyr_add_prj_conf("MAIN_STACK_SIZE", 2048)

    add_extra_script(
        "pre",
        "pre_build.py",
        Path(__file__).parent / "pre_build.py.script",
    )


def _format_conf_val(value: PrjConfValueType) -> str:
    if isinstance(value, bool):
        return "y" if value else "n"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    raise ValueError


def zephyr_add_cdc_acm(config, id):
    framework_ver: cv.Version = CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION]
    if framework_ver >= cv.Version(3, 2, 0):
        zephyr_add_prj_conf("CONFIG_USB_DEVICE_STACK_NEXT", False)
    zephyr_add_prj_conf("USB_DEVICE_STACK", True)
    zephyr_add_prj_conf("USB_CDC_ACM", True)
    # prevent device to go to susspend, without this communication stop working in python
    # there should be a way to solve it
    zephyr_add_prj_conf("USB_DEVICE_REMOTE_WAKEUP", False)
    # prevent logging when buffer is full
    zephyr_add_prj_conf("USB_CDC_ACM_LOG_LEVEL_WRN", True)
    zephyr_add_overlay(
        f"""
&zephyr_udc0 {{
    cdc_acm_uart{id}: cdc_acm_uart{id} {{
        compatible = "zephyr,cdc-acm-uart";
    }};
}};
"""
    )


def zephyr_add_pm_static(section: Section):
    CORE.data[KEY_ZEPHYR][KEY_PM_STATIC].extend(section)


def zephyr_add_user(key, value):
    user = zephyr_data()[KEY_USER]
    if key not in user:
        user[key] = []
    user[key] += [value]


def _write_modules_file() -> None:
    modules = zephyr_data()[KEY_MODULES]
    content = "\n".join(modules) + "\n"
    write_file_if_changed(
        CORE.relative_build_path("modules.txt"), content
    )


def _write_conf_file(path: Path, entries) -> None:
    content = (
        "\n".join(
            f"{name}={_format_conf_val(value[0])}"
            for name, value in sorted(entries.items())
        )
        + "\n"
    )
    write_file_if_changed(CORE.relative_build_path("app" / path), content)


def _write_conf_files() -> None:
    conf_files = zephyr_data()[KEY_CONF_FILES]
    for path, entries in conf_files.items():
        _write_conf_file(path, entries)

def _write_overlay_file() -> None:
    user = zephyr_data()[KEY_USER]
    if user:
        zephyr_add_overlay(
            f"""
/ {{
    zephyr,user {{
        {[f"{key} = {', '.join(value)};" for key, value in user.items()][0]}
}};
}};"""
        )
    write_file_if_changed(
        CORE.relative_build_path("app/app.overlay"),
        zephyr_data()[KEY_OVERLAY],
    )

def _write_extra_build_files() -> None:
    for filename, path in zephyr_data()[KEY_EXTRA_BUILD_FILES].items():
        copy_file_if_changed(
            path,
            CORE.relative_build_path(filename),
        )

def _write_pm_static_file() -> None:
    pm_static = "\n".join(str(item) for item in zephyr_data()[KEY_PM_STATIC])
    if pm_static:
        write_file_if_changed(CORE.relative_build_path("app/pm_static.yml"), pm_static)


def copy_files():
    print("zephyr copy_files")
    _write_modules_file()
    _write_conf_files()
    _write_overlay_file()
    _write_extra_build_files()
    _write_pm_static_file()
    

