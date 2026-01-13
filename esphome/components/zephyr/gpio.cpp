#ifdef USE_ZEPHYR
#include "gpio.h"
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include "esphome/core/log.h"

namespace esphome {
namespace zephyr {

static const char *const TAG = "zephyr";

// Number of nRF GPIO instances with status = "okay"
enum { ZEPHYR_GPIO_PORT_COUNT = DT_NUM_INST_STATUS_OKAY(nordic_nrf_gpio) };

// Emit a device pointer for each "okay" instance, with a comma for array init
#define ZEPHYR_GPIO_ITEM(inst) [DT_PROP(inst, port)] = DEVICE_DT_GET(inst),

static const struct device *const nrf_gpio_ports[] = {DT_FOREACH_STATUS_OKAY(nordic_nrf_gpio, ZEPHYR_GPIO_ITEM)};

static gpio_flags_t flags_to_mode(gpio::Flags flags, bool inverted, bool value) {
  gpio_flags_t ret = 0;
  if (flags & gpio::FLAG_INPUT) {
    ret |= GPIO_INPUT;
  }
  if (flags & gpio::FLAG_OUTPUT) {
    ret |= GPIO_OUTPUT;
    if (value != inverted) {
      ret |= GPIO_OUTPUT_INIT_HIGH;
    } else {
      ret |= GPIO_OUTPUT_INIT_LOW;
    }
  }
  if (flags & gpio::FLAG_PULLUP) {
    ret |= GPIO_PULL_UP;
  }
  if (flags & gpio::FLAG_PULLDOWN) {
    ret |= GPIO_PULL_DOWN;
  }
  if (flags & gpio::FLAG_OPEN_DRAIN) {
    ret |= GPIO_OPEN_DRAIN;
  }
  return ret;
}

struct ISRPinArg {
  uint8_t pin;
  bool inverted;
};

ISRInternalGPIOPin ZephyrGPIOPin::to_isr() const {
  auto *arg = new ISRPinArg{};  // NOLINT(cppcoreguidelines-owning-memory)
  arg->pin = this->pin_;
  arg->inverted = this->inverted_;
  return ISRInternalGPIOPin((void *) arg);
}
ZephyrGPIOPin::ZephyrGPIOPin(int port, int gpio_size, const char *pin_name_prefix) {
  if (port < ZEPHYR_GPIO_PORT_COUNT) {
    this->gpio_ = nrf_gpio_ports[port];
  } else {
    ESP_LOGE(TAG, "Invalid GPIO port %d (max %d)", port, ZEPHYR_GPIO_PORT_COUNT - 1);
  }
  this->gpio_size_ = gpio_size;
  this->pin_name_prefix_ = pin_name_prefix;
}

void ZephyrGPIOPin::attach_interrupt(void (*func)(void *), void *arg, gpio::InterruptType type) const {
  // TODO
}

void ZephyrGPIOPin::setup() {
  if (!device_is_ready(this->gpio_)) {
    ESP_LOGE(TAG, "gpio %u is not ready.", this->pin_);
    return;
  }
  this->pin_mode(this->flags_);
}

void ZephyrGPIOPin::pin_mode(gpio::Flags flags) {
  if (nullptr == this->gpio_) {
    return;
  }
  auto ret = gpio_pin_configure(this->gpio_, this->pin_ % this->gpio_size_,
                                flags_to_mode(flags, this->inverted_, this->value_));
  if (ret != 0) {
    ESP_LOGE(TAG, "gpio %u cannot be configured %d.", this->pin_, ret);
  }
}

size_t ZephyrGPIOPin::dump_summary(char *buffer, size_t len) const {
  return snprintf(buffer, len, "GPIO%u, %s%u", this->pin_, this->pin_name_prefix_, this->pin_ % this->gpio_size_);
}

bool ZephyrGPIOPin::digital_read() {
  if (nullptr == this->gpio_) {
    return false;
  }
  return bool(gpio_pin_get(this->gpio_, this->pin_ % this->gpio_size_) != this->inverted_);
}

void ZephyrGPIOPin::digital_write(bool value) {
  // make sure that value is not ignored since it can be inverted e.g. on switch side
  // that way init state should be correct
  this->value_ = value;
  if (nullptr == this->gpio_) {
    return;
  }
  gpio_pin_set(this->gpio_, this->pin_ % this->gpio_size_, value != this->inverted_ ? 1 : 0);
}
void ZephyrGPIOPin::detach_interrupt() const {
  // TODO
}

}  // namespace zephyr

bool IRAM_ATTR ISRInternalGPIOPin::digital_read() {
  // TODO
  return false;
}

}  // namespace esphome

#endif
