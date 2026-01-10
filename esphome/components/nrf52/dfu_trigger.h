#pragma once

#include "esphome/core/defines.h"
#ifdef USE_NRF52_DFU_TRIGGER
#include "esphome/components/zephyr_usb/zephyr_usb.h"
#include "esphome/core/component.h"
#include "esphome/core/gpio.h"

namespace esphome {
namespace nrf52 {
class DFUTrigger : public Component {
 public:
  void setup() override;
  void set_reset_pin(GPIOPin *reset) { this->reset_pin_ = reset; }
  void set_zephyr_usb(zephyr_usb::USB *usb) { this->zephyr_usb_ = usb; }
  void dump_config() override;

 protected:
  GPIOPin *reset_pin_;
  zephyr_usb::USB *zephyr_usb_;

 private:
  void on_cdc_line_coding(const struct device *dev);
};

}  // namespace nrf52
}  // namespace esphome

#endif  // USE_NRF52_DFU_TRIGGER
