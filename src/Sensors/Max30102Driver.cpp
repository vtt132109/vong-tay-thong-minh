#include "Sensors/Max30102Driver.h"

Max30102Driver::Max30102Driver()
    : _ready(false), _ecoMode(false), _sensorTemp(0.0f), _lastTempTriggerMillis(0),
      _tempConverting(false) {}

void Max30102Driver::recoverBus() {
  pinMode(I2C_SCL_PIN, OUTPUT);
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);

  // Phát 9 xung nhịp SCL để giải phóng thiết bị đang giữ SDA LOW
  for (int i = 0; i < 9; i++) {
    digitalWrite(I2C_SCL_PIN, LOW);
    delayMicroseconds(5);
    digitalWrite(I2C_SCL_PIN, HIGH);
    delayMicroseconds(5);
  }

  // Tạo điều kiện STOP
  pinMode(I2C_SDA_PIN, OUTPUT);
  digitalWrite(I2C_SDA_PIN, LOW);
  delayMicroseconds(5);
  digitalWrite(I2C_SCL_PIN, HIGH);
  delayMicroseconds(5);
  digitalWrite(I2C_SDA_PIN, HIGH);
  delayMicroseconds(5);
}

bool Max30102Driver::writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MAX30102_I2C_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return (Wire.endTransmission() == 0);
}

uint8_t Max30102Driver::readReg(uint8_t reg) {
  Wire.beginTransmission(MAX30102_I2C_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return 0;
  }
  if (Wire.requestFrom((uint8_t)MAX30102_I2C_ADDR, (uint8_t)1) != 1) {
    return 0;
  }
  return Wire.read();
}

bool Max30102Driver::begin() {
  delay(30);

  // Đọc Part ID (0xFF) và Rev ID (0xFE)
  uint8_t partId = readReg(0xFF);
  uint8_t revId = readReg(0xFE);
  Serial.printf("[MAX30102] Part ID: 0x%02X | Rev ID: 0x%02X\n", partId, revId);

  // Reset cảm biến
  writeReg(0x09, 0x40);
  delay(30);

  // Cấu hình FIFO (0x08): Sample avg 4, rollover on (0x4F)
  writeReg(0x08, 0x4F);

  // Chế độ SpO2 (0x09): Bật cả Red và IR LED (0x03)
  writeReg(0x09, 0x03);

  // Cấu hình SpO2 (0x0A): Range 8192nA (chống tràn ADC), 100Hz, Pulse width 411us (0x47)
  writeReg(0x0A, 0x47);

  // Dòng phát LED tối ưu cho CỔ TAY & NGÓN TAY (~10.0mA, 0x32)
  writeReg(0x0C, 0x32); // Red LED
  writeReg(0x0D, 0x32); // IR LED

  // Xóa con trỏ FIFO
  writeReg(0x04, 0x00);
  writeReg(0x05, 0x00);
  writeReg(0x06, 0x00);

  uint8_t mode = readReg(0x09);
  if (partId == 0x15 || partId == 0x11 || mode == 0x03 ||
      (partId != 0x00 && partId != 0xFF)) {
    _ready = true;
    Serial.println("[+] MAX30102 khoi tao thanh cong! DSP chong nhieu san sang.");
    return true;
  } else {
    _ready = false;
    Serial.println("[-] MAX30102 khong phan hoi tren bus I2C.");
    return false;
  }
}

uint8_t Max30102Driver::availableSamples() {
  uint8_t wrPtr = readReg(0x04);
  uint8_t rdPtr = readReg(0x06);
  return (wrPtr - rdPtr) & 0x1F;
}

bool Max30102Driver::readFifo(uint32_t &red, uint32_t &ir) {
  Wire.beginTransmission(MAX30102_I2C_ADDR);
  Wire.write(0x07); // FIFO Data register
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom((uint8_t)MAX30102_I2C_ADDR, (uint8_t)6) != 6) {
    return false;
  }

  uint8_t b0 = Wire.read();
  uint8_t b1 = Wire.read();
  uint8_t b2 = Wire.read();
  uint8_t b3 = Wire.read();
  uint8_t b4 = Wire.read();
  uint8_t b5 = Wire.read();

  red = (((uint32_t)(b0 & 0x03)) << 16) | (((uint32_t)b1) << 8) | b2;
  ir = (((uint32_t)(b3 & 0x03)) << 16) | (((uint32_t)b4) << 8) | b5;
  return true;
}

float Max30102Driver::updateTemperature() {
  if (!_ready) return 0.0f;

  unsigned long now = millis();

  // Kích hoạt chu trình đo mới sau mỗi 2 giây
  if (!_tempConverting) {
    if (now - _lastTempTriggerMillis >= 2000) {
      _lastTempTriggerMillis = now;
      writeReg(0x21, 0x01); // Bit 0 TEMP_EN = 1
      _tempConverting = true;
    }
    return _sensorTemp;
  }

  // Đã kích hoạt chuyển đổi: kiểm tra xem xong chưa (không busy-wait)
  if (_tempConverting) {
    uint8_t status = readReg(0x21);
    if ((status & 0x01) == 0 || (now - _lastTempTriggerMillis >= 40)) {
      int8_t tempInt = (int8_t)readReg(0x1F);
      uint8_t tempFrac = readReg(0x20) & 0x0F;
      float t = (float)tempInt + ((float)tempFrac * 0.0625f);

      if (t > 0.0f && t < 85.0f) {
        if (_sensorTemp == 0.0f) {
          _sensorTemp = t;
        } else {
          _sensorTemp = (_sensorTemp * 0.8f) + (t * 0.2f);
        }
      }
      _tempConverting = false;
    }
  }

  return _sensorTemp;
}

void Max30102Driver::setEcoMode(bool eco) {
  if (!_ready || _ecoMode == eco) return;
  _ecoMode = eco;
  if (eco) {
    // ECO MODE: Tắt Red LED (0x00), giảm IR LED xuống mức thăm dò ~0.8mA (0x04)
    writeReg(0x0C, 0x00);
    writeReg(0x0D, MAX_LED_ECO_IR_CURRENT);
    Serial.println("[MAX30102] Chuyen sang ECO-SENSE: Tat Red LED, IR 0.8mA (Tiet kiem 94% dong LED)");
  } else {
    // ACTIVE MODE: Bật cả Red và IR LED ở dòng 10mA (0x32) để đo SpO2 chuẩn
    writeReg(0x0C, MAX_LED_ACTIVE_CURRENT);
    writeReg(0x0D, MAX_LED_ACTIVE_CURRENT);
    Serial.println("[MAX30102] Chuyen sang ACTIVE-SENSE: Bat Red & IR 10.0mA (Do SpO2 & Nhip tim)");
  }
}
