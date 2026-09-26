#include "Sensors/Mpu6050Driver.h"

Mpu6050Driver::Mpu6050Driver()
    : _ready(false), _ax_ms2(0.0f), _ay_ms2(0.0f), _az_ms2(9.81f),
      _ax_g(0.0f), _ay_g(0.0f), _az_g(1.0f), _a_mag_ms2(9.81f) {}

bool Mpu6050Driver::begin() {
  if (!_mpu.begin(MPU6050_I2C_ADDR, &Wire)) {
    Serial.println("[-] Khong tim thay GY-521 (MPU6050) tai 0x68 tren bus I2C!");
    _ready = false;
    return false;
  }

  _ready = true;
  _mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
  _mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  _mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  // Đưa Gyroscope vào Standby (0x07) để tiết kiệm 87% điện năng (chỉ chạy Accel ~0.5mA)
  Wire.beginTransmission(MPU6050_I2C_ADDR);
  Wire.write(0x6C); // PWR_MGMT_2
  Wire.write(0x07); // STBY_XG=1, STBY_YG=1, STBY_ZG=1 (Gyro OFF, Accel ON)
  Wire.endTransmission();

  Serial.println("[+] GY-521 (MPU6050) khoi tao thanh cong! (Gyro Standby ECO: 0.5mA)");
  return true;
}

void Mpu6050Driver::update() {
  if (_ready) {
    sensors_event_t a, g, temp;
    _mpu.getEvent(&a, &g, &temp);

    _ax_ms2 = a.acceleration.x;
    _ay_ms2 = a.acceleration.y;
    _az_ms2 = a.acceleration.z;

    _ax_g = _ax_ms2 / 9.80665f;
    _ay_g = _ay_ms2 / 9.80665f;
    _az_g = _az_ms2 / 9.80665f;

    _a_mag_ms2 = sqrtf(_ax_ms2 * _ax_ms2 + _ay_ms2 * _ay_ms2 + _az_ms2 * _az_ms2);
  } else {
    // Giá trị mô phỏng khi chưa kết nối phần cứng
    unsigned long now = millis();
    _ax_ms2 = sin(now / 1000.0f) * 1.5f;
    _ay_ms2 = cos(now / 1200.0f) * 1.2f;
    _az_ms2 = 9.81f;
    _ax_g = _ax_ms2 / 9.80665f;
    _ay_g = _ay_ms2 / 9.80665f;
    _az_g = _az_ms2 / 9.80665f;
    _a_mag_ms2 = sqrtf(_ax_ms2 * _ax_ms2 + _ay_ms2 * _ay_ms2 + _az_ms2 * _az_ms2);
  }
}
