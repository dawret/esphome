from pathlib import Path
import textwrap

from esphome.components.nrf52.const import CONF_LABEL
from esphome.components.zephyr import (
    KEY_BOARD,
    PrjConfValueType,
    zephyr_add_conf,
    zephyr_add_sysbuild_conf,
    zephyr_data,
    zephyr_overlay,
)
from esphome.components.zephyr.const import (
    KEY_EXTERNAL_FLASH,
    KEY_FLASH_PRIMARY,
    KEY_PARTITIONS,
)
import esphome.config_validation as cv
from esphome.const import CONF_MODE, CONF_SIZE

CODEOWNERS = ["@dawret"]
DEPENDENCIES = ["zephyr"]

# MCUboot modes
MODE_SINGLE_BANK = "single_bank"
MODE_DUAL_BANK = "dual_bank"

DEFAULT_ERASE_BLOCK_SIZE = 0x1000
# This size give some space for potential serial recovery, logging or image signing
DEFAULT_MCUBOOT_PARTITION_SIZE = 0xE000
MCUBOOT_PAD_SIZE = 0x200
MCUBOOT = "mcuboot"
MCUBOOT_PRIMARY = "mcuboot_primary"
MCUBOOT_SECONDARY = "mcuboot_secondary"
MCUBOOT_PAD = "mcuboot_pad"
APP = "app"
MCUBOOT_CONF = "sysbuild/mcuboot.conf"
CONF_MCUBOOT_PARTITION_SIZE = "mcuboot_partition_size"
CONF_USE_EXTERNAL_FLASH = "use_external_flash"


def _set_core_data(config):
    board = zephyr_data()[KEY_BOARD]
    flash_primary = zephyr_data()[KEY_PARTITIONS][KEY_FLASH_PRIMARY]
    flash_primary.add_start(MCUBOOT, config[CONF_MCUBOOT_PARTITION_SIZE])
    space = flash_primary.available_space
    mcuboot_primary = None
    if config[CONF_USE_EXTERNAL_FLASH]:
        space = min(space, board.external_flash[CONF_SIZE] - DEFAULT_ERASE_BLOCK_SIZE)
    if config[CONF_MODE] == MODE_SINGLE_BANK or config[CONF_USE_EXTERNAL_FLASH]:
        mcuboot_primary = flash_primary.add_start(
            MCUBOOT_PRIMARY, space, [MCUBOOT_PAD, APP]
        )
    else:
        sectors = space // DEFAULT_ERASE_BLOCK_SIZE
        # swap using offset needs either equally sized slots,
        # or the secondary slot one sector bigger than the primary
        slot0_size = (sectors // 2) * DEFAULT_ERASE_BLOCK_SIZE
        slot1_size = space - slot0_size

        mcuboot_primary = flash_primary.add_start(
            MCUBOOT_PRIMARY, slot0_size, [MCUBOOT_PAD, APP]
        )
        flash_primary.add_start(MCUBOOT_SECONDARY, slot1_size)

    if config[CONF_USE_EXTERNAL_FLASH]:
        flash_external = zephyr_data()[KEY_PARTITIONS][KEY_EXTERNAL_FLASH]
        flash_external.add_start(MCUBOOT_SECONDARY, space + DEFAULT_ERASE_BLOCK_SIZE)
    flash_primary.add(MCUBOOT_PAD, mcuboot_primary.address, MCUBOOT_PAD_SIZE)
    return config


def _set_defaults(config):
    mode = config[CONF_MODE]
    board = zephyr_data()[KEY_BOARD]

    if CONF_USE_EXTERNAL_FLASH not in config:
        if mode == MODE_DUAL_BANK:
            config[CONF_USE_EXTERNAL_FLASH] = board.external_flash is not None
        else:
            config[CONF_USE_EXTERNAL_FLASH] = False

    return config


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.Optional(CONF_MODE, default=MODE_DUAL_BANK): cv.one_of(
                MODE_SINGLE_BANK, MODE_DUAL_BANK
            ),
            cv.Optional(
                CONF_MCUBOOT_PARTITION_SIZE, default=DEFAULT_MCUBOOT_PARTITION_SIZE
            ): cv.positive_int,
            cv.Optional(CONF_USE_EXTERNAL_FLASH): cv.boolean,
        },
    ),
    _set_defaults,
    _set_core_data,
)


def _final_validate(config):
    board = zephyr_data()[KEY_BOARD]

    if config[CONF_USE_EXTERNAL_FLASH] and config[CONF_MODE] == MODE_SINGLE_BANK:
        raise cv.Invalid("use_external_flash can only be used with dual_bank mode")

    if config[CONF_USE_EXTERNAL_FLASH] and not board.external_flash:
        raise cv.Invalid(
            "use_external_flash is set but the board does not have an external flash configured"
        )

    if (
        config[CONF_USE_EXTERNAL_FLASH]
        and board.external_flash["erase_block_size"] != DEFAULT_ERASE_BLOCK_SIZE
    ):
        raise cv.Invalid(
            "Different sector sizes between internal and external flash are not supported"
        )

    return config


FINAL_VALIDATE_SCHEMA = _final_validate


def _add_mcuboot_conf(
    name: str, value: PrjConfValueType, required: bool = True
) -> None:
    zephyr_add_conf(Path(MCUBOOT_CONF), name, value, required)


def generate_dt_partitions(partitions):
    output = textwrap.dedent(
        """
            compatible = "fixed-partitions";
            #address-cells = <1>;
            #size-cells = <1>;

        """
    )
    for p in partitions:
        label = p.name
        # This renaming is needed to satisfy the zephyr build system
        if label == MCUBOOT:
            label = "boot_partition"
        if label == MCUBOOT_PRIMARY:
            label = "slot0_partition"
        if label == MCUBOOT_SECONDARY:
            label = "slot1_partition"
        output += textwrap.dedent(
            f"""
                {label}: partition@{p.address:X} {{
                    label = "{p.name}";
                    reg = <0x{p.address:X} 0x{p.size:X}>;
                }};
            """
        )
    return output


def set_partitions(config, overlay):
    """
    This function generated the partition dts overlay
    This is not really required when using partition manager,
    However on some boards (ie. xiao_ble) the build system complains
    about missing partitions in the overlay.
    """
    board = zephyr_data()[KEY_BOARD]
    flash_primary = zephyr_data()[KEY_PARTITIONS][KEY_FLASH_PRIMARY]
    partitions = generate_dt_partitions(flash_primary.get_top_level_partitions())
    flash0 = overlay.node("flash0")
    flash0.add_property("/delete-node/ partitions")
    flash0.add_entry("partitions", partitions)
    if config[CONF_USE_EXTERNAL_FLASH]:
        label = f"&{board.external_flash[CONF_LABEL]}"
        overlay.add_chosen("nordic,pm-ext-flash", label)
        flash_external = zephyr_data()[KEY_PARTITIONS][KEY_EXTERNAL_FLASH]
        partitions = generate_dt_partitions(flash_external.get_top_level_partitions())
        ext_flash = overlay.node(board.external_flash[CONF_LABEL])
        ext_flash.add_property("/delete-node/ partitions")
        ext_flash.add_entry("partitions", partitions)


def set_overlay(config):
    mcuboot_overlay = zephyr_overlay("sysbuild/mcuboot.overlay")

    set_partitions(config, mcuboot_overlay)
    set_partitions(config, zephyr_overlay())
    mcuboot_overlay.add_chosen("zephyr,code-partition", "&boot_partition")
    zephyr_overlay().add_chosen("zephyr,code-partition", "&slot0_partition")


async def to_code(config):
    zephyr_add_sysbuild_conf("SB_CONFIG_BOOTLOADER_MCUBOOT", True)

    mode = config[CONF_MODE]
    if mode == MODE_SINGLE_BANK:
        _add_mcuboot_conf("SINGLE_APPLICATION_SLOT", True)
    else:
        _add_mcuboot_conf("BOOT_SWAP_USING_MOVE", True)

    if config[CONF_USE_EXTERNAL_FLASH]:
        zephyr_add_sysbuild_conf("SB_CONFIG_PM_EXTERNAL_FLASH_MCUBOOT_SECONDARY", True)
        flash_ext = zephyr_data()[KEY_PARTITIONS][KEY_EXTERNAL_FLASH]
        _add_mcuboot_conf(
            "BOOT_MAX_IMG_SECTORS",
            flash_ext.partitions[MCUBOOT_SECONDARY].size // DEFAULT_ERASE_BLOCK_SIZE,
        )
    else:
        flash_primary = zephyr_data()[KEY_PARTITIONS][KEY_FLASH_PRIMARY]
        _add_mcuboot_conf(
            "BOOT_MAX_IMG_SECTORS",
            flash_primary.partitions[MCUBOOT_PRIMARY].size // DEFAULT_ERASE_BLOCK_SIZE,
        )

    _add_mcuboot_conf("BOOT_VALIDATE_SLOT0", True)
    _add_mcuboot_conf("BOOT_UPGRADE_ONLY", False)
    _add_mcuboot_conf("BOOT_DIRECT_XIP", False)

    # Disable signature
    zephyr_add_sysbuild_conf("SB_CONFIG_BOOT_SIGNATURE_TYPE_NONE", True)

    # Disable serial recovery and usb
    _add_mcuboot_conf("MCUBOOT_SERIAL", False)
    _add_mcuboot_conf("BOOT_USB_DFU_NO", True)
    _add_mcuboot_conf("LOG", False)
    _add_mcuboot_conf("SERIAL", False)
    _add_mcuboot_conf("CONSOLE", False)
    _add_mcuboot_conf("USB_DEVICE_STACK", False)

    # Disable hardware crypto to save space
    # We're using tinycrypt for signature verification
    _add_mcuboot_conf("HW_CC3XX", False)

    set_overlay(config)
