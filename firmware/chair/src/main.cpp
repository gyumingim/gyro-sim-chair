// Chair controller firmware (ESP32 DevKitC). Hardware glue only — all logic is in lib/chair_core (also tested in control/sil.py).
//
// Wiring (see docs/chair-control.html):
//   I2C0  SDA 21 / SCL 22 : LSM6DSOX IMU (0x6A, on the cage near the pivot)  +  AS5600 pitch (0x36, pitch drive-shaft end)
//   I2C1  SDA 18 / SCL 19 : AS5600 roll (0x36, roll idler-pulley shaft end)   -> two buses because both AS5600 are 0x36
//   Cytron MDD10A          : roll PWM1 26 / DIR1 27, pitch PWM2 25 / DIR2 32   (3.3 V logic OK)
//   Inputs (external 10k pull-up to 3.3 V; GPIO 34-39 have no internal pull-ups):
//     34 ESTOP_OK    PC817 output: LOW = 24 V motor bus present (safety relay closed)
//     35 LIM_ROLL_R  36 LIM_ROLL_L  39 LIM_PITCH_AFT  4 LIM_PITCH_FWD   NC switches to GND: LOW = ok, HIGH = hit / wire broken
//     16 IDX_ROLL    17 IDX_PITCH   A3144 hall (open collector): LOW = magnet on the weight at the rail centre
//     23 PINS_STOWED  3 lock-pin holder switches in series to GND: LOW = all pins parked (out of the chair)
//     13 DECK_STOWED  deck parking switch to GND: LOW = deck away
//   Outputs: 33 buzzer (via transistor), 2 status LED (on board)
#include <Arduino.h>
#include <Wire.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include "chair_core.h"

// ---------------- pins ----------------
static const int SDA0 = 21, SCL0 = 22, SDA1 = 18, SCL1 = 19;
static const int PWM_PIN[N_AX] = {26, 25}, DIR_PIN[N_AX] = {27, 32};
static const int P_ESTOP = 34, P_LIM_POS[N_AX] = {35, 39}, P_LIM_NEG[N_AX] = {36, 4}, P_IDX[N_AX] = {16, 17};
static const int P_PINS = 23, P_DECK = 13, P_BUZ = 33, P_LED = 2;
// roll: + = weight toward the right (switch 35 = right end). pitch: + = weight toward the rear (switch 39 = rear end)

// ---------------- mechanical constants ----------------
static const float MM_PER_REV = 100.0f;                 // HTD5M 20T pulley
static const float POS_SIGN[N_AX] = {+1.0f, +1.0f};     // flip if the weight moves the wrong way (check once, see docs)
static const bool MOTOR_INVERT[N_AX] = {false, false};  // flip if duty + drives the weight toward -
// IMU axis map: chair x fwd, y left, z up  <-  sensor axis index and sign (mount the board flat, arrow forward = identity)
static const int IMU_AX[3] = {0, 1, 2};
static const float IMU_SG[3] = {+1, +1, +1};

static const uint32_t LOOP_US = 5000;                   // 200 Hz
static const uint32_t TELEM_MS = 50;                    // 20 Hz

static core_t core;
static core_inputs_t in;
static core_outputs_t out;
static Preferences prefs;
TwoWire &bus0 = Wire;
TwoWire &bus1 = Wire1;

// ---------------- LSM6DSOX (raw registers, no library) ----------------
static const uint8_t IMU_ADDR = 0x6A;
static bool imu_write(uint8_t reg, uint8_t v) {
  bus0.beginTransmission(IMU_ADDR); bus0.write(reg); bus0.write(v);
  return bus0.endTransmission() == 0;
}
static bool imu_init() {
  bus0.beginTransmission(IMU_ADDR); bus0.write(0x0F);
  if (bus0.endTransmission(false) != 0 || bus0.requestFrom((int)IMU_ADDR, 1) != 1) return false;
  if (bus0.read() != 0x6C) return false;                 // WHO_AM_I
  return imu_write(0x12, 0x44)                           // CTRL3_C: BDU, auto-increment
      && imu_write(0x10, 0x50)                           // CTRL1_XL: 208 Hz, +-2 g
      && imu_write(0x11, 0x50);                          // CTRL2_G: 208 Hz, 250 dps
}
static bool imu_read(float acc[3], float gyr[3]) {
  bus0.beginTransmission(IMU_ADDR); bus0.write(0x22);   // OUTX_L_G .. OUTZ_H_A
  if (bus0.endTransmission(false) != 0 || bus0.requestFrom((int)IMU_ADDR, 12) != 12) return false;
  int16_t r[6];
  for (int i = 0; i < 6; i++) { uint8_t lo = bus0.read(), hi = bus0.read(); r[i] = (int16_t)(lo | (hi << 8)); }
  float g[3], a[3];
  for (int i = 0; i < 3; i++) { g[i] = r[i] * 0.00875f; a[i] = r[3 + i] * 0.000061f; }
  for (int i = 0; i < 3; i++) { acc[i] = IMU_SG[i] * a[IMU_AX[i]]; gyr[i] = IMU_SG[i] * g[IMU_AX[i]]; }
  float n = sqrtf(acc[0] * acc[0] + acc[1] * acc[1] + acc[2] * acc[2]);
  return n > 0.7f && n < 1.3f;                           // chair accelerations are small: anything else = bad data
}

// ---------------- AS5600 multi-turn ----------------
struct Enc { TwoWire *w; int last; long turns; bool init; uint8_t bad; };
static Enc enc[N_AX] = {{&Wire1, 0, 0, false, 0}, {&Wire, 0, 0, false, 0}};
static bool as5600_read(TwoWire *w, int *raw) {
  w->beginTransmission(0x36); w->write(0x0B);           // STATUS, RAW ANGLE H, L
  if (w->endTransmission(false) != 0 || w->requestFrom(0x36, 3) != 3) return false;
  uint8_t st = w->read(), hi = w->read(), lo = w->read();
  if (!(st & 0x20) || (st & 0x18)) return false;         // magnet not detected / too weak / too strong
  *raw = ((hi & 0x0F) << 8) | lo;
  return true;
}
static bool enc_update(int i, float *mm) {
  int raw;
  if (!as5600_read(enc[i].w, &raw)) { if (enc[i].bad < 255) enc[i].bad++; return enc[i].bad < 3 && enc[i].init; }
  enc[i].bad = 0;
  if (!enc[i].init) { enc[i].last = raw; enc[i].init = true; }
  int d = raw - enc[i].last;
  if (d > 2048) enc[i].turns--; else if (d < -2048) enc[i].turns++;
  enc[i].last = raw;
  *mm = POS_SIGN[i] * (enc[i].turns * 4096L + raw) * (MM_PER_REV / 4096.0f);
  return true;
}

// ---------------- motors (Cytron MDD10A: PWM + DIR) ----------------
static void motor_set(int i, float duty) {
  if (MOTOR_INVERT[i]) duty = -duty;
  digitalWrite(DIR_PIN[i], duty >= 0 ? HIGH : LOW);
  uint32_t d = (uint32_t)(fminf(fabsf(duty), 1.0f) * 1023.0f);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PWM_PIN[i], d);
#else
  ledcWrite(i, d);
#endif
}

// ---------------- switches with a 3-sample debounce; unknown -> unsafe ----------------
struct Deb { uint8_t v, cnt; };
static Deb deb[16];
static uint8_t debounce(int k, uint8_t raw) {
  if (raw == deb[k].v) deb[k].cnt = 0;
  else if (++deb[k].cnt >= 3) { deb[k].v = raw; deb[k].cnt = 0; }
  return deb[k].v;
}

static char line[128];
static int line_n = 0;

void setup() {
  for (int i = 0; i < N_AX; i++) { pinMode(DIR_PIN[i], OUTPUT); digitalWrite(DIR_PIN[i], LOW); pinMode(PWM_PIN[i], OUTPUT); digitalWrite(PWM_PIN[i], LOW); }
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  for (int i = 0; i < N_AX; i++) ledcAttach(PWM_PIN[i], 20000, 10);
#else
  for (int i = 0; i < N_AX; i++) { ledcSetup(i, 20000, 10); ledcAttachPin(PWM_PIN[i], i); }
#endif
  for (int i = 0; i < N_AX; i++) motor_set(i, 0);
  pinMode(P_ESTOP, INPUT); pinMode(P_PINS, INPUT_PULLUP); pinMode(P_DECK, INPUT_PULLUP);
  for (int i = 0; i < N_AX; i++) { pinMode(P_LIM_POS[i], INPUT_PULLUP); pinMode(P_LIM_NEG[i], INPUT_PULLUP); pinMode(P_IDX[i], INPUT_PULLUP); }
  pinMode(P_BUZ, OUTPUT); pinMode(P_LED, OUTPUT);
  for (int k = 0; k < 16; k++) deb[k] = {1, 0};          // start as "not ok" until read 3 times
  Serial.begin(115200);
  bus0.begin(SDA0, SCL0, 100000);                        // 100 kHz: cables up to ~1.5 m (shielded 4-core)
  bus1.begin(SDA1, SCL1, 100000);
  bus0.setTimeOut(5); bus1.setTimeOut(5);
  bool imu = imu_init();

  core_params_t P; core_default_params(&P);
  core_init(&core, &P);
  prefs.begin("chair", false);
  core.imu_zero[0] = prefs.getFloat("z_roll", 0.0f);
  core.imu_zero[1] = prefs.getFloat("z_pitch", 0.0f);
  Serial.printf("#chair fw, imu %s, zero %.2f %.2f\n", imu ? "ok" : "MISSING", core.imu_zero[0], core.imu_zero[1]);

#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t wc = {.timeout_ms = 1000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wc);
#else
  esp_task_wdt_init(1, true);                            // 1 s: a hung loop reboots -> motors off, BOOT state
#endif
  esp_task_wdt_add(NULL);
}

void loop() {
  static uint32_t next_us = micros(), last_tel = 0, imu_retry = 0;
  static bool imu_up = true;
  while ((int32_t)(micros() - next_us) < 0) {
    // serial in while waiting
    while (Serial.available()) {
      char ch = (char)Serial.read();
      if (ch == '\n' || ch == '\r') { if (line_n) { line[line_n] = 0; core_rx_line(&core, line, millis()); line_n = 0; } }
      else if (line_n < (int)sizeof(line) - 1) line[line_n++] = ch;
      else line_n = 0;                                    // too long: drop
    }
  }
  next_us += LOOP_US;
  if ((int32_t)(micros() - next_us) > (int32_t)(4 * LOOP_US)) next_us = micros() + LOOP_US;  // fell behind: resync
  esp_task_wdt_reset();

  in.now_ms = millis();
  in.imu_ok = imu_up && imu_read(in.acc, in.gyro);
  if (!in.imu_ok && in.now_ms - imu_retry > 1000) { imu_retry = in.now_ms; imu_up = imu_init(); }
  for (int i = 0; i < N_AX; i++) in.pos_ok[i] = enc_update(i, &in.pos_raw_mm[i]);
  in.estop_ok = debounce(0, digitalRead(P_ESTOP) == LOW ? 0 : 1) == 0;
  in.pins_stowed = debounce(1, digitalRead(P_PINS) == LOW ? 0 : 1) == 0;
  in.deck_stowed = debounce(2, digitalRead(P_DECK) == LOW ? 0 : 1) == 0;
  for (int i = 0; i < N_AX; i++) {
    in.lim_pos[i] = debounce(3 + i, digitalRead(P_LIM_POS[i]));     // HIGH = hit or broken
    in.lim_neg[i] = debounce(5 + i, digitalRead(P_LIM_NEG[i]));
    in.index[i] = digitalRead(P_IDX[i]) == LOW;                      // no debounce: we want the first edge
  }

  core_step(&core, &in, &out);

  for (int i = 0; i < N_AX; i++) motor_set(i, in.estop_ok ? out.duty[i] : 0.0f);
  digitalWrite(P_BUZ, out.buzzer && (in.now_ms / 250) % 2);
  digitalWrite(P_LED, out.led == 1 || (out.led == 2 && (in.now_ms / 300) % 2));
  if (out.save_nvs) { prefs.putFloat("z_roll", core.imu_zero[0]); prefs.putFloat("z_pitch", core.imu_zero[1]); }

  if (in.now_ms - last_tel >= TELEM_MS) {
    last_tel = in.now_ms;
    char buf[220];
    if (core_tx_line(&core, buf, sizeof(buf)) > 0) Serial.println(buf);
  }
}
