#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Wire.h>

constexpr uint8_t LEFT_FORWARD_PIN = 5;
constexpr uint8_t LEFT_BACKWARD_PIN = 6;
constexpr uint8_t RIGHT_FORWARD_PIN = 9;
constexpr uint8_t RIGHT_BACKWARD_PIN = 10;

constexpr uint8_t LED_PIN = 12;
constexpr uint8_t LED_COUNT = 2;

constexpr uint8_t MPU_ADDR = 0x68;
constexpr int DEFAULT_SPEED = 155;
constexpr int TURN_SPEED = 145;
constexpr float TURN_TOLERANCE_DEG = 3.0f;
constexpr unsigned long GYRO_UPDATE_MS = 5;

// Коэффициент коррекции курса при движении прямо.
// ВНИМАНИЕ: Если робота начнет резко уносить в сторону вместо выравнивания,
// просто измени знак коэффициента на минус (например: -3.5f)
constexpr float KP_STRAIGHT = 3.5f; 

Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

enum LedMode {
  LED_STARTUP,
  LED_READY,
  LED_MOVING,
  LED_STOPPED,
};

enum MotionMode {
  MOTION_STOPPED,
  MOTION_FORWARD,
  MOTION_BACKWARD,
  MOTION_MANUAL_TURN,
  MOTION_TURNING,
};

LedMode ledMode = LED_STARTUP;
MotionMode motionMode = MOTION_STOPPED;

int driveSpeed = DEFAULT_SPEED;
float yawDeg = 0.0f;
float gyroZOffset = 0.0f;
float turnTargetDeg = 0.0f;
float forwardTargetYaw = 0.0f; 
bool gyroReady = false;
unsigned long lastGyroUpdate = 0;
unsigned long lastLedUpdate = 0;

void writeMpu(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

int16_t readMpuWord(uint8_t reg) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, static_cast<uint8_t>(2));

  if (Wire.available() < 2) {
    return 0;
  }

  int16_t high = Wire.read();
  int16_t low = Wire.read();
  return (high << 8) | low;
}

bool initGyro() {
  Wire.begin();
  writeMpu(0x6B, 0x00);  
  writeMpu(0x1B, 0x00);  
  delay(100);

  Wire.beginTransmission(MPU_ADDR);
  if (Wire.endTransmission() != 0) {
    Serial.println(F("GYRO_MISSING"));
    return false;
  }

  long sum = 0;
  constexpr int samples = 500;
  for (int i = 0; i < samples; i++) {
    sum += readMpuWord(0x47);
    delay(2);
  }

  gyroZOffset = sum / static_cast<float>(samples);
  lastGyroUpdate = millis();
  Serial.println(F("GYRO_OK"));
  return true;
}

void updateGyro() {
  if (!gyroReady) {
    return;
  }

  unsigned long now = millis();
  if (now - lastGyroUpdate < GYRO_UPDATE_MS) {
    return;
  }

  float dt = (now - lastGyroUpdate) / 1000.0f;
  lastGyroUpdate = now;

  float rawZ = readMpuWord(0x47);
  float degPerSec = (rawZ - gyroZOffset) / 131.0f;
  yawDeg += degPerSec * dt;
}

uint32_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return pixels.Color(r, g, b);
}

void fillPixels(uint32_t color) {
  for (uint8_t i = 0; i < LED_COUNT; i++) {
    pixels.setPixelColor(i, color);
  }
  pixels.show();
}

void updateLeds() {
  unsigned long now = millis();
  if (now - lastLedUpdate < 25) {
    return;
  }
  lastLedUpdate = now;

  uint8_t pulse = (sin(now / 350.0f) + 1.0f) * 45.0f;

  switch (ledMode) {
    case LED_STARTUP:
      fillPixels(rgb(15 + pulse / 3, 0, 130 + pulse));
      break;
    case LED_READY:
    case LED_STOPPED:
      fillPixels(rgb(0, 120 + pulse, 18));
      break;
    case LED_MOVING:
      fillPixels(rgb(220 + pulse / 3, 155 + pulse / 2, 0));
      break;
  }
}

int clampSpeed(int speed) {
  return constrain(speed, 0, 255);
}

void setMotorPair(uint8_t forwardPin, uint8_t backwardPin, int speed) {
  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    analogWrite(forwardPin, speed);
    analogWrite(backwardPin, 0);
  } else if (speed < 0) {
    analogWrite(forwardPin, 0);
    analogWrite(backwardPin, -speed);
  } else {
    analogWrite(forwardPin, 0);
    analogWrite(backwardPin, 0);
  }
}

void tankDrive(int leftSpeed, int rightSpeed) {
  setMotorPair(LEFT_FORWARD_PIN, LEFT_BACKWARD_PIN, leftSpeed);
  setMotorPair(RIGHT_FORWARD_PIN, RIGHT_BACKWARD_PIN, rightSpeed);
}

void stopRobot() {
  tankDrive(0, 0);
  motionMode = MOTION_STOPPED;
  ledMode = LED_STOPPED;
}

void driveForward() {
  forwardTargetYaw = yawDeg; // Запоминаем текущий угол как эталон прямой линии
  tankDrive(driveSpeed, driveSpeed);
  motionMode = MOTION_FORWARD;
  ledMode = LED_MOVING;
}

// Корректировка курса при движении по прямой
void updateForwardCorrection() {
  if (motionMode != MOTION_FORWARD) {
    return;
  }

  float error = forwardTargetYaw - yawDeg;
  int correction = static_cast<int>(error * KP_STRAIGHT);

  int leftSpeed = constrain(driveSpeed + correction, 0, 255);
  int rightSpeed = constrain(driveSpeed - correction, 0, 255);

  setMotorPair(LEFT_FORWARD_PIN, LEFT_BACKWARD_PIN, leftSpeed);
  setMotorPair(RIGHT_FORWARD_PIN, RIGHT_BACKWARD_PIN, rightSpeed);
}

void driveBackward() {
  tankDrive(-driveSpeed, -driveSpeed);
  motionMode = MOTION_BACKWARD;
  ledMode = LED_MOVING;
}

void manualTurnLeft() {
  tankDrive(-driveSpeed, driveSpeed);
  motionMode = MOTION_MANUAL_TURN;
  ledMode = LED_MOVING;
}

void manualTurnRight() {
  tankDrive(driveSpeed, -driveSpeed);
  motionMode = MOTION_MANUAL_TURN;
  ledMode = LED_MOVING;
}

void startTurn(float degrees) {
  if (!gyroReady) {
    Serial.println(F("NO_GYRO"));
    stopRobot();
    return;
  }

  yawDeg = 0.0f; // СБРОС УГЛА: теперь мы считаем поворот строго от 0
  turnTargetDeg = degrees;
  motionMode = MOTION_TURNING;
  ledMode = LED_MOVING;

  if (degrees > 0) {
    tankDrive(TURN_SPEED, -TURN_SPEED); // Крутим вправо
  } else {
    tankDrive(-TURN_SPEED, TURN_SPEED); // Крутим влево
  }
}

// Обновленная логика контроля контролируемого поворота
void updateTurn() {
  if (motionMode != MOTION_TURNING) {
    return;
  }

  // Берем значения по модулю (abs), чтобы направление осей гироскопа нас больше не волновало
  float currentRotation = abs(yawDeg);
  float targetRotation = abs(turnTargetDeg);

  // Проверяем, повернулись ли мы на нужный угол с учетом погрешности
  if (currentRotation >= (targetRotation - TURN_TOLERANCE_DEG)) {
    stopRobot();
    Serial.println(F("TURN_DONE"));
    return;
  }

  // Динамическое замедление: если до конца поворота осталось меньше 25 градусов, притормаживаем
  float remaining = targetRotation - currentRotation;
  int speed = remaining < 25.0f ? max(90, TURN_SPEED - 35) : TURN_SPEED;

  if (turnTargetDeg > 0) {
    tankDrive(speed, -speed); // Продолжаем вращение вправо
  } else {
    tankDrive(-speed, speed); // Продолжаем вращение влево
  }
}

void handleCommand(String command) {
  command.trim();
  command.toUpperCase();

  if (command.length() == 0) {
    return;
  }

  if (command.startsWith("SPEED ")) {
    driveSpeed = clampSpeed(command.substring(6).toInt());
    Serial.print(F("SPEED "));
    Serial.println(driveSpeed);
  } else if (command == "READY") {
    stopRobot();
    ledMode = LED_READY;
    Serial.println(F("READY_OK"));
  } else if (command == "FORWARD") {
    driveForward();
    Serial.println(F("FORWARD_OK"));
  } else if (command == "BACKWARD") {
    driveBackward();
    Serial.println(F("BACKWARD_OK"));
  } else if (command == "TURN_LEFT") {
    manualTurnLeft();
    Serial.println(F("TURN_LEFT_OK"));
  } else if (command == "TURN_RIGHT") {
    manualTurnRight();
    Serial.println(F("TURN_RIGHT_OK"));
  } else if (command == "STOP") {
    stopRobot();
    Serial.println(F("STOP_OK"));
  } else if (command == "LEFT") {
    startTurn(-90.0f); 
    Serial.println(F("LEFT_OK"));
  } else if (command == "RIGHT" || command == "TIGHT") {
    startTurn(90.0f);  
    Serial.println(F("RIGHT_OK"));
  } else if (command == "BRICK") {
    startTurn(180.0f); 
    Serial.println(F("BRICK_OK"));
  } else {
    Serial.print(F("UNKNOWN "));
    Serial.println(command);
  }
}

void setup() {
  pinMode(LEFT_FORWARD_PIN, OUTPUT);
  pinMode(LEFT_BACKWARD_PIN, OUTPUT);
  pinMode(RIGHT_FORWARD_PIN, OUTPUT);
  pinMode(RIGHT_BACKWARD_PIN, OUTPUT);

  Serial.begin(9600);
  Serial.setTimeout(30);

  pixels.begin();
  pixels.clear();
  pixels.show();

  stopRobot();
  ledMode = LED_STARTUP;
  gyroReady = initGyro();
  Serial.println(F("BOOT_OK"));
}

void loop() {
  updateGyro();
  updateTurn();
  updateForwardCorrection(); // Стабилизация движения по прямой
  updateLeds();

  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    handleCommand(command);
  }
}
