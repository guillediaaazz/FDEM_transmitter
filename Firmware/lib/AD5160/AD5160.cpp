#include "AD5160.h"

#include <SPI.h>

AD5160::AD5160(uint8_t chipSelectPin) : chipSelectPin_(chipSelectPin) {}

bool AD5160::begin() {
  pinMode(chipSelectPin_, OUTPUT);
  digitalWrite(chipSelectPin_, HIGH);
  ready_ = true;
  setWiper(wiper_);
  return true;
}

void AD5160::setWiper(uint8_t value) {
  wiper_ = value;
  if (!ready_) return;
  SPI.beginTransaction(SPISettings(4000000, MSBFIRST, SPI_MODE0));
  digitalWrite(chipSelectPin_, LOW);
  SPI.transfer(wiper_);
  digitalWrite(chipSelectPin_, HIGH);
  SPI.endTransaction();
}
