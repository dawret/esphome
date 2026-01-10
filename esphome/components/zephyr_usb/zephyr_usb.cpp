#ifdef USE_ZEPHYR
#include "zephyr_usb.h"

#include "esphome/core/defines.h"
#include "esphome/core/log.h"
#include <hal/nrf_power.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/usb/usbd.h>
#include <zephyr/sys/reboot.h>

namespace esphome::zephyr_usb {

static const char *const TAG = "zephyr_usb";

static USB *usb_instance = nullptr;

/* Define the USB device */
USBD_DEVICE_DEFINE(zephyr_usb, DEVICE_DT_GET(DT_NODELABEL(zephyr_udc0)), ZEPHYR_USB_VID, ZEPHYR_USB_PID);

/* Define descriptors */
USBD_DESC_LANG_DEFINE(zephyr_usb_lang);
USBD_DESC_MANUFACTURER_DEFINE(zephyr_usb_mfr, ZEPHYR_USB_MFR_NAME);
USBD_DESC_PRODUCT_DEFINE(zephyr_usb_product, ZEPHYR_USB_PRODUCT_NAME);
USBD_DESC_SERIAL_NUMBER_DEFINE(zephyr_usb_sn);

USBD_DESC_CONFIG_DEFINE(zephyr_usb_fs_cfg_desc, "FS Configuration");

static const uint8_t attributes = (IS_ENABLED(CONFIG_SAMPLE_USBD_SELF_POWERED) ? USB_SCD_SELF_POWERED : 0);

USBD_CONFIGURATION_DEFINE(zephyr_usb_fs_config, attributes, 125, &zephyr_usb_fs_cfg_desc);

static void zephyr_usb_msg_cb(struct usbd_context *const ctx, const struct usbd_msg *msg) {
  ESP_LOGV(TAG, "USBD message: %s", usbd_msg_type_string(msg->type));
  if (usbd_can_detect_vbus(ctx)) {
    if (msg->type == USBD_MSG_VBUS_READY) {
      if (usbd_enable(ctx)) {
        ESP_LOGE(TAG, "Failed to enable device support");
      }
    }

    if (msg->type == USBD_MSG_VBUS_REMOVED) {
      if (usbd_disable(ctx)) {
        ESP_LOGE(TAG, "Failed to disable device support");
      }
    }
  }
  if (msg->type == USBD_MSG_CDC_ACM_LINE_CODING) {
    if (usb_instance) {
      usb_instance->line_coding_callback_.call(msg->dev);
    }
  }
}

static int zephyr_usb_init(void) {
  int err;

  err = usbd_add_descriptor(&zephyr_usb, &zephyr_usb_lang);
  if (err)
    return err;

  err = usbd_add_descriptor(&zephyr_usb, &zephyr_usb_mfr);
  if (err)
    return err;

  err = usbd_add_descriptor(&zephyr_usb, &zephyr_usb_product);
  if (err)
    return err;

  err = usbd_add_descriptor(&zephyr_usb, &zephyr_usb_sn);
  if (err)
    return err;

  err = usbd_add_configuration(&zephyr_usb, USBD_SPEED_FS, &zephyr_usb_fs_config);
  if (err)
    return err;

  err = usbd_register_all_classes(&zephyr_usb, USBD_SPEED_FS, 1, nullptr);
  if (err)
    return err;

  err = usbd_device_set_code_triple(&zephyr_usb, USBD_SPEED_FS, USB_BCC_MISCELLANEOUS, 0x02, 0x01);
  if (err)
    return err;

  usbd_self_powered(&zephyr_usb, attributes & USB_SCD_SELF_POWERED);
  err = usbd_msg_register_cb(&zephyr_usb, zephyr_usb_msg_cb);

  err = usbd_init(&zephyr_usb);
  if (err)
    return err;

  ESP_LOGI(TAG, "USB device support enabled");

  return 0;
}

void USB::setup() {
  usb_instance = this;

  int err = zephyr_usb_init();

  // Always enable USB at boot - VBUS detection in callback handles runtime plug/unplug
  err = usbd_enable(&zephyr_usb);

  if (err) {
    ESP_LOGE(TAG, "Failed to initialize USB device: %d", err);
  }
}

}  // namespace esphome::zephyr_usb
#endif
