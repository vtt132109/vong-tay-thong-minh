#ifndef MPU6050_DRIVER_H
#define MPU6050_DRIVER_H

#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Arduino.h>
#include <Wire.h>
#include "Config.h"

class Mpu6050Driver {
public:
  Mpu6050Driver();

  bool begin();
  bool isReady() const { return _ready; }

  // Cập nhật lấy mẫu ở 50Hz
  void update();

  // Getters dữ liệu gia tốc
  float getAxMs2() const { return _ax_ms2; }
  float getAyMs2() const { return _ay_ms2; }
  float getAzMs2() const { return _az_ms2; }
  float getAxG() const { return _ax_g; }
  float getAyG() const { return _ay_g; }
  float getAzG() const { return _az_g; }
  float getMagnitude() const { return _a_mag_ms2; }

private:
  Adafruit_MPU6050 _mpu;
  bool _ready;
  float _ax_ms2, _ay_ms2, _az_ms2;
  float _ax_g, _ay_g, _az_g;
  float _a_mag_ms2;
};

#endif // MPU6050_DRIVER_H
