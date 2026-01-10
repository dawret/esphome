#include "dfu_trigger.h"

#ifdef USE_NRF52_DFU_TRIGGER
#include "esphome/core/log.h"

#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#ifdef DFU_TRIGGER_METHOD_GPREGRET
#include <zephyr/sys/reboot.h>
#include <hal/nrf_power.h>
#endif

namespace esphome {
namespace nrf52 {

static const char *const TAG = "dfu_trigger";

void DFUTrigger::setup() {
#ifdef DFU_TRIGGER_METHOD_GPIO
  this->reset_pin_->setup();
#endif
  this->zephyr_usb_->add_on_line_coding_callback([this](const struct device *dev) { this->on_cdc_line_coding(dev); });
}

void DFUTrigger::dump_config() {
#ifdef DFU_TRIGGER_METHOD_GPIO
  ESP_LOGCONFIG(TAG, "DFU TRIGGER: GPIO reset method");
  LOG_PIN("  RESET Pin: ", this->reset_pin_);
#ifdef DFU_TRIGGER_GPIO_RESET_MAGIC
  ESP_LOGCONFIG(TAG, "    Double reset magic: 0x%08X at address 0x%08X", DFU_TRIGGER_GPIO_RESET_MAGIC,
                DFU_TRIGGER_GPIO_RESET_MAGIC_ADDRESS);
#endif
#endif
#ifdef DFU_TRIGGER_METHOD_GPREGRET
  ESP_LOGCONFIG(TAG, "DFU TRIGGER: GPREGRET method");
  ESP_LOGCONFIG(TAG, "    GPREGRET reset magic: 0x%02X", DFU_TRIGGER_GPREGRET_RESET_MAGIC);
#endif
}

void DFUTrigger::on_cdc_line_coding(const struct device *dev) {
  uint32_t baudrate;
  int ret = uart_line_ctrl_get(dev, UART_LINE_CTRL_BAUD_RATE, &baudrate);
  if (ret == 0) {
    ESP_LOGD(TAG, "CDC ACM line coding changed: baudrate=%u", baudrate);
    if (baudrate == DFU_TRIGGER_BAUDRATE) {
#ifdef DFU_TRIGGER_METHOD_GPIO
      ESP_LOGI(TAG, "Reset request detected, rebooting to bootloader via GPIO");
#ifdef DFU_TRIGGER_GPIO_RESET_MAGIC
      volatile uint32_t *dbl_reset_mem = (volatile uint32_t *) DFU_TRIGGER_GPIO_RESET_MAGIC_ADDRESS;
      (*dbl_reset_mem) = DFU_TRIGGER_GPIO_RESET_MAGIC;
#endif
      this->reset_pin_->digital_write(true);
#endif
#ifdef DFU_TRIGGER_METHOD_GPREGRET
      ESP_LOGI(TAG, "Reset request detected, rebooting to bootloader via GPREGRET");
      nrf_power_gpregret_set(NRF_POWER, 0, DFU_TRIGGER_GPREGRET_RESET_MAGIC);
      sys_reboot(SYS_REBOOT_WARM);
#endif
    }
  }
}

}  // namespace nrf52
}  // namespace esphome

#endif  // USE_NRF52_DFU_TRIGGER
