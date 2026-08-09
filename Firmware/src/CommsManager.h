#pragma once

#include <Arduino.h>

class NimBLEServer;
class NimBLEService;
class NimBLECharacteristic;
class NimBLEAdvertising;

class CommsManager {
 public:
  using CommandHandler = String (*)(const String& command);

  bool begin(CommandHandler handler);
  void poll();
  void broadcast(const String& message);
  void setBluetoothEnabled(bool enabled);
  bool bluetoothEnabled() const { return bluetoothEnabled_; }
  bool bluetoothConnected() const { return bluetoothConnected_; }

  // Called by NimBLE callbacks; kept public to avoid doing application work in a callback.
  void receiveBleData(const String& data);
  void onBleConnectionChanged(bool connected);

 private:
  void processIncoming(String& buffer, bool fromBle);
  void processLine(const String& line, bool fromBle);
  void sendUsb(const String& message);
  void sendBle(const String& message);
  void sendResponse(const String& message, bool toBle);

  CommandHandler commandHandler_ = nullptr;
  String usbBuffer_;
  String bleBuffer_;
  NimBLEServer* server_ = nullptr;
  NimBLEService* service_ = nullptr;
  NimBLECharacteristic* rxCharacteristic_ = nullptr;
  NimBLECharacteristic* txCharacteristic_ = nullptr;
  NimBLEAdvertising* advertising_ = nullptr;
  bool bluetoothEnabled_ = false;
  bool bluetoothConnected_ = false;
};
