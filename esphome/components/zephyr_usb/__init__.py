from dataclasses import dataclass, field

import esphome.codegen as cg
from esphome.components.zephyr import zephyr_add_prj_conf, zephyr_overlay
import esphome.config_validation as cv
from esphome.const import Framework
from esphome.core import CORE

CODEOWNERS = ["@dawret"]
CONFLICTS_WITH = ["usb_host", "tinyusb"]

DOMAIN = "zephyr_usb"


@dataclass
class ZephyrUSBData:
    usb_cdc_devices: list[str] = field(default_factory=list)


def _get_data() -> ZephyrUSBData:
    if DOMAIN not in CORE.data:
        CORE.data[DOMAIN] = ZephyrUSBData()
    return CORE.data[DOMAIN]


CONF_USB_VID = "usb_vid"
CONF_USB_PID = "usb_pid"
CONF_MFR_NAME = "manufacturer_name"
CONF_PRODUCT_NAME = "product_name"
CONF_ON_LINE_CODING = "on_line_coding"
CONF_ZEPHYR_USB_ID = "zephyr_usb_id"

zephyr_usb_ns = cg.esphome_ns.namespace("zephyr_usb")
USB = zephyr_usb_ns.class_("USB", cg.Component)


def _final_validate(config):
    return config


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(CONF_ZEPHYR_USB_ID): cv.declare_id(USB),
            cv.Optional(CONF_USB_VID, default=0x1209): cv.hex_uint16_t,
            cv.Optional(CONF_USB_PID, default=0xF000): cv.hex_uint16_t,
            cv.Optional(CONF_MFR_NAME, default="ESPHome"): cv.string,
            cv.Optional(CONF_PRODUCT_NAME, default="ESPHome"): cv.string,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.only_with_framework(Framework.ZEPHYR),
)

FINAL_VALIDATE_SCHEMA = _final_validate


def zephyr_usb_add_cdc_acm(config):
    id = len(_get_data().usb_cdc_devices)
    dev_name = f"cdc_acm_uart{id}"
    _get_data().usb_cdc_devices.append(dev_name)

    zephyr_overlay().node("zephyr_udc0").add_entry(
        dev_name,
        'compatible = "zephyr,cdc-acm-uart";',
        label=dev_name,
    )

    zephyr_add_prj_conf("USBD_CDC_ACM_CLASS", True)
    return dev_name


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ZEPHYR_USB_ID])
    await cg.register_component(var, config)
    cg.add_define("ZEPHYR_USB_VID", config[CONF_USB_VID])
    cg.add_define("ZEPHYR_USB_PID", config[CONF_USB_PID])
    cg.add_define("ZEPHYR_USB_MFR_NAME", config[CONF_MFR_NAME])
    cg.add_define("ZEPHYR_USB_PRODUCT_NAME", config[CONF_PRODUCT_NAME])

    zephyr_add_prj_conf("USB_DEVICE_STACK_NEXT", True)
    zephyr_add_prj_conf("USB_DEVICE_STACK", False)
    zephyr_add_prj_conf("HWINFO", True)  # for serial number

    # Add at least one cdc acm device, if there's none
    if len(_get_data().usb_cdc_devices) == 0:
        zephyr_usb_add_cdc_acm(config)

    zephyr_add_prj_conf("SERIAL", True)
    zephyr_add_prj_conf("UART_LINE_CTRL", True)
    zephyr_add_prj_conf("USBD_CDC_ACM_CLASS", True)
    zephyr_add_prj_conf("CDC_ACM_SERIAL_INITIALIZE_AT_BOOT", False)
