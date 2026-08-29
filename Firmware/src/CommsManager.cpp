#include "CommsManager.h"

#include <NimBLEDevice.h>

#include "Config.h"

namespace {
class ServerCallbacks final : public NimBLEServerCallbacks {
 public:
  explicit ServerCallbacks(CommsManager& owner) : owner_(owner) {}

  void onConnect(NimBLEServer*, NimBLEConnInfo&) override { owner_.onBleConnectionChanged(true); }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override { owner_.onBleConnectionChanged(false); }

 private:
  CommsManager& owner_;
};

class ReceiveCallbacks final : public NimBLECharacteristicCallbacks {
 public:
  explicit ReceiveCallbacks(CommsManager& owner) : owner_(owner) {}

  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    owner_.receiveBleData(String(characteristic->getValue().c_str()));
  }

 private:
  CommsManager& owner_;
};
}  // namespace

bool CommsManager::begin(CommandHandler handler) {
  commandHandler_ = handler;
  Serial.begin(Config::SERIAL_BAUD);
  usbTelemetryEnabled_ = Config::USB_TELEMETRY_ENABLED_AT_BOOT;

  NimBLEDevice::init(Config::BLE_DEVICE_NAME);
  server_ = NimBLEDevice::createServer();
  server_->setCallbacks(new ServerCallbacks(*this));
  service_ = server_->createService(Config::NUS_SERVICE_UUID);
  rxCharacteristic_ = service_->createCharacteristic(
      Config::NUS_RX_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  txCharacteristic_ = service_->createCharacteristic(
      Config::NUS_TX_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  rxCharacteristic_->setCallbacks(new ReceiveCallbacks(*this));
  advertising_ = NimBLEDevice::getAdvertising();
  advertising_->addServiceUUID(Config::NUS_SERVICE_UUID);
  setBluetoothEnabled(Config::BLE_ENABLED_AT_BOOT);
  return true;
}

void CommsManager::poll() {
  while (Serial.available() > 0) {
    const char character = static_cast<char>(Serial.read());
    // Terminals differ: Tera Term may send CR, LF, or CRLF for Enter. Treat
    // either character as a line terminator; an LF after a CR then becomes an
    // empty line and is harmlessly ignored by processLine().
    usbBuffer_ += (character == '\r') ? '\n' : character;
    if (usbBuffer_.length() > Config::MAX_COMMAND_LENGTH) {
      sendUsb("ERR:COMMAND_TOO_LONG");
      usbBuffer_ = "";
    }
  }
  processIncoming(usbBuffer_, false);
  processIncoming(bleBuffer_, true);
}

void CommsManager::broadcast(const String& message) {
  sendUsb(message);
  sendBle(message);
}

void CommsManager::broadcastTelemetry(const String& message) {
  if (usbTelemetryEnabled_) sendUsb(message);
  sendBle(message);
}

void CommsManager::setBluetoothEnabled(bool enabled) {
  bluetoothEnabled_ = enabled;
  if (advertising_ == nullptr) return;
  if (enabled) {
    advertising_->start();
  } else {
    advertising_->stop();
  }
}

void CommsManager::receiveBleData(const String& data) {
  bleBuffer_ += data;
  if (bleBuffer_.length() > Config::MAX_COMMAND_LENGTH) {
    sendBle("ERR:COMMAND_TOO_LONG");
    bleBuffer_ = "";
  }
}

void CommsManager::onBleConnectionChanged(bool connected) {
  bluetoothConnected_ = connected;
  if (!connected && bluetoothEnabled_ && advertising_ != nullptr) advertising_->start();
}

void CommsManager::processIncoming(String& buffer, bool fromBle) {
  int newline = buffer.indexOf('\n');
  while (newline >= 0) {
    String line = buffer.substring(0, newline);
    buffer.remove(0, newline + 1);
    processLine(line, fromBle);
    newline = buffer.indexOf('\n');
  }
}

void CommsManager::processLine(const String& line, bool fromBle) {
  String command = line;
  command.trim();
  if (command.isEmpty()) return;
  if (commandHandler_ == nullptr) {
    sendResponse("ERR:COMMAND_HANDLER_UNAVAILABLE", fromBle);
    return;
  }
  sendResponse(commandHandler_(command), fromBle);
}

void CommsManager::sendResponse(const String& message, bool toBle) {
  if (toBle) {
    sendBle(message);
  } else {
    sendUsb(message);
  }
}

void CommsManager::sendUsb(const String& message) {
  // Use CRLF for conventional terminal rendering. LF-only output makes some
  // terminals, including common Tera Term configurations, display each new
  // line one column farther to the right.
  String line = message;
  while (line.endsWith("\r") || line.endsWith("\n")) line.remove(line.length() - 1);
  Serial.print(line);
  Serial.print("\r\n");
}

void CommsManager::sendBle(const String& message) {
  if (server_ == nullptr || txCharacteristic_ == nullptr || !bluetoothConnected_) return;

  // BLE notifications preserve packet boundaries, but the controller protocol
  // is line based and may span several packets when a peer uses the minimum
  // ATT MTU. Terminate every logical response and split it to fit each peer.
  String line = message;
  while (line.endsWith("\r") || line.endsWith("\n")) line.remove(line.length() - 1);
  line += '\n';
  txCharacteristic_->setValue(line.c_str());

  const std::vector<uint16_t> peers = server_->getPeerDevices();
  for (const uint16_t connectionHandle : peers) {
    const uint16_t mtu = server_->getPeerMTU(connectionHandle);
    const size_t maximumChunkLength = mtu > 3 ? static_cast<size_t>(mtu - 3) : 1;
    size_t offset = 0;
    while (offset < line.length()) {
      const size_t remaining = line.length() - offset;
      const size_t chunkLength = remaining < maximumChunkLength ? remaining : maximumChunkLength;
      txCharacteristic_->notify(
          reinterpret_cast<const uint8_t*>(line.c_str() + offset), chunkLength, connectionHandle);
      offset += chunkLength;
    }
  }
}
