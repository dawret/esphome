import json
from pathlib import Path
import textwrap
from typing import TypedDict

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_BOARD, KEY_CORE, KEY_FRAMEWORK_VERSION
from esphome.core import CORE
from esphome.helpers import copy_file_if_changed, write_file_if_changed

from .const import (
    KEY_BOARD,
    KEY_BOOTLOADER,
    KEY_CONF_FILES,
    KEY_EXTRA_BUILD_FILES,
    KEY_OVERLAY,
    KEY_PM_STATIC,
    KEY_PRJ_CONF,
    KEY_SYSBUILD_CONF,
    KEY_USER,
    KEY_ZEPHYR,
    zephyr_ns,
)

CODEOWNERS = ["@tomaszduda23"]

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
    board_config: dict
    conf_files: dict[Path, dict[str, tuple[PrjConfValueType, bool]]]
    overlay: str
    extra_build_files: dict[str, Path]
    pm_static: list[Section]
    user: dict[str, list[str]]


def _zephyr_set_board_config(config):
    return {
        "frameworks": ["zephyr"],
        "board_name": config[CONF_BOARD],
        "name": "esphome nrf52",
        "upload": {"maximum_ram_size": 248832, "maximum_size": 815104, "speed": 115200},
        "url": "https://esphome.io/",
        "vendor": "esphome",
        "build": {"bsp": {"name": "adafruit"}, "softdevice": {"sd_fwid": "0x00B6"}},
    }


def zephyr_set_core_data(config):
    CORE.data[KEY_ZEPHYR] = ZephyrData(
        board=config[CONF_BOARD].split("/")[0],
        board_config=_zephyr_set_board_config(config),
        bootloader=config[KEY_BOOTLOADER],
        conf_files={},
        overlay="",
        extra_build_files={},
        pm_static=[],
        user={},
    )
    return config


def zephyr_data() -> ZephyrData:
    return CORE.data[KEY_ZEPHYR]


def zephyr_conf_file(key: Path) -> dict[str, tuple[PrjConfValueType, bool]]:
    conf_files = zephyr_data()[KEY_CONF_FILES]
    if key not in conf_files:
        conf_files[key] = {}
    return conf_files[key]


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


def zephyr_add_sysbuild_conf(
    name: str, value: PrjConfValueType, required: bool = True
) -> None:
    zephyr_add_conf(Path(KEY_SYSBUILD_CONF), name, value, required)


def zephyr_add_prj_conf(
    name: str, value: PrjConfValueType, required: bool = True
) -> None:
    """Set a zephyr prj conf value."""
    zephyr_add_conf(Path(KEY_PRJ_CONF), name, value, required)


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


def zephyr_to_code(config):
    cg.add_build_flag("-DUSE_ZEPHYR")
    cg.set_cpp_standard("gnu++20")
    # build is done by west so bypass board checking in platformio
    cg.add_platformio_option("boards_dir", CORE.relative_build_path("boards"))
    # c++ support
    zephyr_add_prj_conf("NEWLIB_LIBC", True)
    zephyr_add_prj_conf("FPU", True)
    zephyr_add_prj_conf("NEWLIB_LIBC_FLOAT_PRINTF", True)
    zephyr_add_prj_conf("STD_CPP20", True)

    # <err> os: ***** USAGE FAULT *****
    # <err> os:   Illegal load of EXC_RETURN into PC
    zephyr_add_prj_conf("MAIN_STACK_SIZE", 2048)

    add_extra_script(
        "pre",
        "pre_build.py",
        Path(__file__).parent / "pre_build.py.script",
    )


def zephyr_setup_preferences():
    cg.add(zephyr_ns.setup_preferences())
    zephyr_add_prj_conf("SETTINGS", True)
    zephyr_add_prj_conf("NVS", True)
    zephyr_add_prj_conf("FLASH_MAP", True)
    zephyr_add_prj_conf("FLASH", True)


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
    if CORE.is_nrf52 and framework_ver >= cv.Version(3, 2, 0):
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
    
def _cleanup_conf_files(path: Path, files: dict) -> None:
    conf_files = path.rglob("*.conf")
    valid_files = [CORE.relative_build_path(f"zephyr/{p}") for p in files]
    for conf_file in conf_files:
        if conf_file not in valid_files:
            conf_file.unlink()


def _write_conf_file(path: Path, entries) -> None:
    content = (
        "\n".join(
            f"{name}={_format_conf_val(value[0])}"
            for name, value in sorted(entries.items())
        )
        + "\n"
    )
    write_file_if_changed(CORE.relative_build_path("zephyr" / path), content)


def _write_conf_files() -> None:
    conf_files = zephyr_data()[KEY_CONF_FILES]
    for path, entries in conf_files.items():
        _write_conf_file(path, entries)


def copy_files():
    user = zephyr_data()[KEY_USER]
    if user:
        zephyr_add_overlay(
            f"""
                / {{
                    zephyr,user {{
                        {[f"{key} = {', '.join(value)};" for key, value in user.items()][0]}
                    }};
                }};
            """
        )

    _write_conf_files()
    
    _cleanup_conf_files(
        CORE.relative_build_path("zephyr"), zephyr_data()[KEY_CONF_FILES]
    )

    write_file_if_changed(
        CORE.relative_build_path("zephyr/app.overlay"),
        zephyr_data()[KEY_OVERLAY],
    )

    write_file_if_changed(
        CORE.relative_build_path(f"boards/{zephyr_data()[KEY_BOARD]}.json"),
        json.dumps(zephyr_data()["board_config"]),
    )

    for filename, path in zephyr_data()[KEY_EXTRA_BUILD_FILES].items():
        copy_file_if_changed(
            path,
            CORE.relative_build_path(filename),
        )

    pm_static = "\n".join(str(item) for item in zephyr_data()[KEY_PM_STATIC])
    if pm_static:
        write_file_if_changed(
            CORE.relative_build_path("zephyr/pm_static.yml"), pm_static
        )
