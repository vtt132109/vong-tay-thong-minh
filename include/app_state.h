#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <MAX30100.h>
#include <MAX30100_BeatDetector.h>
#include <MAX30100_Filters.h>
#include <MAX30100_SpO2Calculator.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"
#include "shared_types.h"
#include "board_config.h"
#include "secrets_config.h"

extern Adafruit_SSD1306 display;
extern Adafruit_MPU6050 mpu;
extern MAX30100 hrm;
extern BeatDetector beatDetector;
extern DCRemover irDCRemover;
extern DCRemover redDCRemover;
extern FilterBuLp1 pulseFilter;
extern SpO2Calculator spo2Calculator;
extern Preferences prefs;
extern WebServer server;

extern SemaphoreHandle_t telemetryMutex;
extern QueueHandle_t commandQueue;
extern TelemetrySnapshot gTelemetry;

extern volatile bool gWifiConnected;

extern bool oledReady;
extern bool mpuReady;
extern bool maxReady;

extern volatile bool captureActive;
extern uint32_t captureEndMs;
extern char aiLabel[16];
extern float aiConfidence;
extern float aiProbability;
extern float aiThreshold;
extern uint8_t aiWindowFill;
extern uint32_t aiInferenceCount;
extern uint32_t aiInferenceUs;
extern float aiWindowPeak;
extern bool aiFall;
extern bool ppgMotion;

extern SystemState state;
extern uint32_t stateEnteredMs;
extern uint32_t countdownEndMs;
extern uint32_t snoozeEndMs;
extern AlertType pendingAlertType;
extern char alarmReason[48];
extern float fallThreshold;
extern uint32_t fallCount;
extern uint32_t stepCount;

extern float lastTotalAcc;
extern float bpm;
extern uint8_t spo2;
extern float rawBpm;
extern uint8_t rawSpo2;
extern bool fingerDetected;
extern float batteryVoltage;
extern uint8_t batteryPercent;
extern bool buzzerActive;
extern uint32_t testBuzzerUntilMs;

extern uint32_t freeFallStartMs;
extern uint8_t freeFallLowCount;
extern uint32_t impactStartMs;
extern float impactSamples[IMPACT_SAMPLE_CAPACITY];
extern size_t impactSampleCount;
extern bool impactExtended;
extern uint32_t lastDirectImpactMs;

extern bool healthAbnormal;
extern uint32_t healthAbnormalSinceMs;

extern bool buttonDown;
extern bool buttonLongHandled;
extern uint32_t buttonDownMs;
extern uint32_t buttonTestUntilMs;

extern uint32_t lastStepMs;
extern bool stepHigh;

extern float irWave[WAVE_POINTS];
extern float redWave[WAVE_POINTS];
extern float irPeak;
extern float redPeak;

extern uint32_t loopCounter;
extern uint32_t loopSecondMs;
extern float loopFps;
extern uint32_t lastBatteryMs;
extern uint32_t lastDisplayMs;
extern uint32_t lastTelemetryMs;
extern uint32_t lastStepSaveMs;
extern uint32_t lastDebugMs;
extern uint32_t lastSavedSteps;
