#include "esphome/core/defines.h"
#if defined(USE_OPENTHREAD) && defined(USE_NRF52)
#include <openthread/dataset.h>
#include <openthread/thread.h>
#include <openthread/logging.h>
#include "openthread.h"
#include <zephyr/net/openthread.h>

static const char *const TAG = "openthread";

namespace esphome::openthread {

static void on_thread_state_changed(otChangedFlags flags, struct openthread_context *ot_context, void *user_data) {
  ESP_LOGI(TAG, "Thread state changed: 0x%08x", flags);
  if (flags & OT_CHANGED_THREAD_ROLE) {
    otDeviceRole role = otThreadGetDeviceRole(ot_context->instance);
    ESP_LOGI(TAG, "New Thread role: %s", otThreadDeviceRoleToString(role));
  }
}

static struct openthread_state_changed_cb ot_state_changed_cb = {.state_changed_cb = on_thread_state_changed};

void OpenThreadComponent::setup() {
  struct openthread_context *context = openthread_get_default_context();
  otOperationalDatasetTlvs dataset = {};

#ifdef USE_OPENTHREAD_TLVS
  if (dataset.mLength == 0) {
    // If we didn't have an active dataset, and we have tlvs, parse it and pass it to esp_openthread_auto_start
    size_t len = (sizeof(USE_OPENTHREAD_TLVS) - 1) / 2;
    if (len > sizeof(dataset.mTlvs)) {
      ESP_LOGW(TAG, "TLV buffer too small, truncating");
      len = sizeof(dataset.mTlvs);
    }
    parse_hex(USE_OPENTHREAD_TLVS, sizeof(USE_OPENTHREAD_TLVS) - 1, dataset.mTlvs, len);
    dataset.mLength = len;
  }
#endif
  otError error = otDatasetSetActiveTlvs(context->instance, &dataset);
  if (error != OT_ERROR_NONE) {
    ESP_LOGE(TAG, "Failed to set active dataset: %s", otThreadErrorToString(error));
    return;
  }
  openthread_state_changed_cb_register(context, &ot_state_changed_cb);
  openthread_start(context);
}

void OpenThreadComponent::ot_main() {}

network::IPAddresses OpenThreadComponent::get_ip_addresses() {
  network::IPAddresses addresses;
  return addresses;
  /*otInstance *instance = openthread_get_default_instance();
  int addr_count = 0;
  for (otNetifAddress *addr = otIp6GetUnicastAddresses(instance); addr != nullptr; addr = addr->mNext) {
    if (addr_count + 1 >= addresses.size()) {
      break;
    }
    addresses[addr_count + 1] = network::IPAddress(reinterpret_cast<const ip_addr_t *>(&addr->mAddress));
    addr_count++;
  }
  return addresses;*/
}

std::optional<InstanceLock> InstanceLock::try_acquire(int delay) {
  if (openthread_api_mutex_try_lock(openthread_get_default_context())) {
    return InstanceLock();
  }
  return {};
}

InstanceLock InstanceLock::acquire() {
  openthread_api_mutex_lock(openthread_get_default_context());
  return InstanceLock();
}

otInstance *InstanceLock::get_instance() { return openthread_get_default_instance(); }

InstanceLock::~InstanceLock() { openthread_api_mutex_unlock(openthread_get_default_context()); }

}  // namespace esphome::openthread
#endif
