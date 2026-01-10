#pragma once
#ifdef USE_ZEPHYR
#include "esphome/core/component.h"
#include "esphome/core/helpers.h"

#include <zephyr/device.h>

namespace esphome::zephyr_usb {

class USB : public Component {
 public:
  void setup() override;
  void add_on_line_coding_callback(std::function<void(const device *)> &&callback) {
    this->line_coding_callback_.add(std::move(callback));
  }
  float get_setup_priority() const override { return setup_priority::IO; }

  LazyCallbackManager<void(const device *)> line_coding_callback_{};
};

}  // namespace esphome::zephyr_usb
#endif
