// DIY flight controls -> one USB HID joystick (Arduino Pro Micro, ATmega32U4).
//
// Why one board: sim/server.py reads ONE joystick (sim/controls.json: axis 0 ail, 1 elev, 2 thr, 3 rud).
// Why a TCA9548A mux: all six AS5600 have the fixed I2C address 0x36. The mux gives each sensor its own channel,
// keeps the full 12-bit digital angle (0.088 deg) and the magnet-status check, and splits the bus so the ~1.5 m
// pedal cable does not load the stick's bus. (AS5600 analog OUT -> 10-bit ADC over 360 deg = 0.35 deg/step,
// only ~115 steps across +-20 deg of stick travel: too coarse.)
//
// Mux channels (TCA9548A at 0x70):           HID (pygame axis index = order below, verify once on the PC)
//   0  stick roll   AS5600                  X  (axis 0)  ail       right = +
//   1  stick pitch  AS5600 + PCF8574 0x20   Y  (axis 1)  elev      pushed forward = -   (controls.json invert = true)
//   2  throttle     AS5600 + PCF8574 0x21   Z  (axis 2)  thr       full forward = -1    (server: (1 - v) / 2)
//   3  rudder       AS5600                  Rx (axis 3)  rud       right pedal forward = +
//   4  toe brake L  AS5600                  Ry (axis 4)  brake L   released = -1, pressed = +1
//   5  toe brake R  AS5600                  Rz (axis 5)  brake R
// PCF8574 0x20 (stick grip):    P0 trigger, P1 thumb 1, P2 thumb 2, P3 pinky, P4..P7 hat up/right/down/left  (to GND)
// PCF8574 0x21 (throttle grip): P0 trigger, P1 thumb 1, P2 thumb 2, P3 spare,  P4..P7 hat up/right/down/left
// Buttons: 1..4 stick, 5..8 throttle. Hat 0 = stick, hat 1 = throttle.
// Pro Micro pins: D2 SDA, D3 SCL, D4 CAL button (to GND), D5 status LED (+ 1k), D6 TCA9548A RESET (optional).
//
// Calibration (stored in EEPROM, survives power-off):
//   hold CAL 2 s (or send "cal" on the USB serial port) -> LED blinks fast
//   step 1: let go of everything (stick centred by its springs, pedals centred, throttle at IDLE (back), brakes released) -> press CAL
//   step 2: move every axis to both ends 2-3 times (stick in circles, throttle idle<->full, rudder both ways, each brake fully) -> press CAL
//   LED on = saved. Serial commands: cal, dump, dz <0..20> (centre deadzone %), raw (stream raw angles), reset (defaults)
#include <Arduino.h>
#include <Wire.h>
#include <EEPROM.h>
#include <Joystick.h>

static const uint8_t MUX = 0x70, AS5600 = 0x36, PCF_STICK = 0x20, PCF_THR = 0x21;
static const uint8_t P_CAL = 4, P_LED = 5, P_MUX_RST = 6;
enum { A_ROLL, A_PITCH, A_THR, A_RUD, A_BRK_L, A_BRK_R, N_AXES };
static const uint8_t AX_CH[N_AXES] = {0, 1, 2, 3, 4, 5};
static const bool CENTERED[N_AXES] = {true, true, false, true, false, false};
// output direction of the CENTRED axes (roll, pitch, rudder): flip one if it comes out backwards (re-flash, no re-cal).
// Leave throttle / brakes at +1: their direction is fixed by the code (idle = +1, brake released = -1).
static const int8_t SIGN[N_AXES] = {+1, +1, +1, +1, +1, +1};
static const char *NAMES[N_AXES] = {"roll", "pitch", "thr", "rud", "brkL", "brkR"};

struct Cal {
  uint32_t magic;            // 'GSC1'
  int16_t rest[N_AXES];      // raw 0..4095 at the centre (centred axes) or at rest (throttle idle, brake released)
  int16_t lo[N_AXES], hi[N_AXES];   // min / max signed delta from rest seen in step 2
  uint8_t dz_centre_pct, dz_end_pct;
  uint8_t crc;
};
static Cal cal;
static const uint32_t MAGIC = 0x31435347UL;

Joystick_ joy(JOYSTICK_DEFAULT_REPORT_ID, JOYSTICK_TYPE_JOYSTICK, 8, 2,
              true, true, true, true, true, true,      // X Y Z Rx Ry Rz
              false, false, false, false, false);      // rudder throttle accelerator brake steering (not used)

static uint8_t crc8(const uint8_t *p, int n) {
  uint8_t c = 0;
  while (n--) { c ^= *p++; for (int b = 0; b < 8; b++) c = (c & 0x80) ? (c << 1) ^ 0x07 : (c << 1); }
  return c;
}
static void cal_defaults() {
  cal.magic = MAGIC;
  for (int i = 0; i < N_AXES; i++) {
    cal.rest[i] = 2048;
    cal.lo[i] = CENTERED[i] ? -228 : 0;     // +-20 deg = 228 counts
    cal.hi[i] = CENTERED[i] ? 228 : 341;    // 30 deg
  }
  cal.dz_centre_pct = 2; cal.dz_end_pct = 1;
}
static void cal_save() { cal.crc = crc8((const uint8_t *)&cal, sizeof(cal) - 1); EEPROM.put(0, cal); }
static bool cal_load() {
  EEPROM.get(0, cal);
  return cal.magic == MAGIC && cal.crc == crc8((const uint8_t *)&cal, sizeof(cal) - 1);
}

// ---------------- I2C helpers ----------------
static bool mux_select(uint8_t ch) {
  Wire.beginTransmission(MUX); Wire.write(1 << ch);
  return Wire.endTransmission() == 0;
}
static int read_as5600(uint8_t ch) {               // raw 0..4095, or -1 (no answer / no magnet)
  if (!mux_select(ch)) return -1;
  Wire.beginTransmission(AS5600); Wire.write(0x0B);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(AS5600, (uint8_t)3) != 3) return -1;
  uint8_t st = Wire.read(), hi = Wire.read(), lo = Wire.read();
  if (!(st & 0x20)) return -1;                     // magnet not detected
  return ((hi & 0x0F) << 8) | lo;
}
static int read_pcf(uint8_t ch, uint8_t addr) {    // pressed bits = 1, or -1
  if (!mux_select(ch)) return -1;
  if (Wire.requestFrom(addr, (uint8_t)1) != 1) return -1;
  return (~Wire.read()) & 0xFF;
}
static void pcf_init(uint8_t ch, uint8_t addr) {   // all pins high = inputs with the weak pull-up
  if (!mux_select(ch)) return;
  Wire.beginTransmission(addr); Wire.write(0xFF); Wire.endTransmission();
}
static int hat_angle(uint8_t b) {                  // b: bit0 up, bit1 right, bit2 down, bit3 left
  static const int16_t T[16] = {-1, 0, 90, 45, 180, -1, 135, 90, 270, 315, -1, 0, 225, 270, 180, -1};
  int a = T[b & 0x0F];
  return a < 0 ? JOYSTICK_HATSWITCH_RELEASE : a;
}

// ---------------- axis processing ----------------
static int16_t delta_of(int raw, int rest) { return (int16_t)(((raw - rest + 2048) & 4095) - 2048); }   // handles the 0/4095 wrap
static float filt[N_AXES];
static int raw_now[N_AXES];

static int16_t axis_out(int i, float d) {         // signed delta from rest -> -32767..32767
  float v;
  if (CENTERED[i]) {
    float span = d >= 0 ? cal.hi[i] : -cal.lo[i];
    if (span < 20) span = 20;
    v = d / span;                                  // -1..1
    float dz = cal.dz_centre_pct / 100.0f, de = cal.dz_end_pct / 100.0f;
    float m = fabs(v);
    m = m <= dz ? 0 : (m >= 1 - de ? 1 : (m - dz) / (1 - de - dz));
    v = v < 0 ? -m : m;
  } else {
    // one end is the rest position; the travel goes to whichever side is larger
    float span = (cal.hi[i] >= -cal.lo[i]) ? cal.hi[i] : cal.lo[i];
    if (fabs(span) < 20) span = 20;
    float u = d / span;                           // 0 at rest .. 1 at the far end
    float dz = cal.dz_end_pct / 100.0f + 0.01f;
    u = u <= dz ? 0 : (u >= 1 - dz ? 1 : (u - dz) / (1 - 2 * dz));
    // throttle: idle (rest) = +1, full forward = -1  (server: thr = (1 - v) / 2)
    // brakes:   released (rest) = -1, pressed = +1
    v = (i == A_THR) ? 1 - 2 * u : 2 * u - 1;
  }
  v *= SIGN[i];
  if (v > 1) v = 1;
  if (v < -1) v = -1;
  return (int16_t)(v * 32767);
}

// ---------------- calibration state ----------------
static uint8_t cal_step = 0;          // 0 normal, 1 waiting at rest, 2 sweeping
static long rest_sum[N_AXES];
static int16_t sw_lo[N_AXES], sw_hi[N_AXES];
static bool stream_raw = false;

static void cal_start() { cal_step = 1; Serial.println(F("CAL 1: let go of everything (stick/pedals centred, throttle IDLE, brakes released), press CAL")); }
static void cal_button() {
  if (cal_step == 1) {
    // average around the first good sample (no 0/4095 wrap problem), count only good reads
    int ref[N_AXES], n[N_AXES];
    for (int i = 0; i < N_AXES; i++) { ref[i] = -1; n[i] = 0; rest_sum[i] = 0; }
    for (int k = 0; k < 32; k++) {
      for (int i = 0; i < N_AXES; i++) {
        int r = read_as5600(AX_CH[i]);
        if (r < 0) continue;
        if (ref[i] < 0) ref[i] = r;
        rest_sum[i] += delta_of(r, ref[i]); n[i]++;
      }
      delay(5);
    }
    for (int i = 0; i < N_AXES; i++) {
      if (n[i] < 16) { Serial.print(F("  ! sensor not reading: ")); Serial.println(NAMES[i]); cal_step = 0; if (!cal_load()) cal_defaults(); return; }
      cal.rest[i] = (int16_t)((ref[i] + rest_sum[i] / n[i] + 4096) % 4096); sw_lo[i] = 0; sw_hi[i] = 0;
    }
    cal_step = 2;
    Serial.println(F("CAL 2: move every axis to both ends 2-3 times, then press CAL"));
  } else if (cal_step == 2) {
    bool ok = true;
    for (int i = 0; i < N_AXES; i++) {
      int range = sw_hi[i] - sw_lo[i];
      Serial.print(NAMES[i]); Serial.print(F(" rest ")); Serial.print(cal.rest[i]); Serial.print(F(" lo ")); Serial.print(sw_lo[i]);
      Serial.print(F(" hi ")); Serial.println(sw_hi[i]);
      if (range < 100) { ok = false; Serial.print(F("  ! too little travel on ")); Serial.println(NAMES[i]); }
      if (CENTERED[i] && (sw_hi[i] < 40 || sw_lo[i] > -40)) { ok = false; Serial.print(F("  ! not moved both ways: ")); Serial.println(NAMES[i]); }
    }
    if (ok) { for (int i = 0; i < N_AXES; i++) { cal.lo[i] = sw_lo[i]; cal.hi[i] = sw_hi[i]; } cal_save(); Serial.println(F("CAL saved")); }
    else { if (!cal_load()) cal_defaults(); Serial.println(F("CAL NOT saved (old values kept) - run again")); }
    cal_step = 0;
  }
}

static char cmd[24]; static uint8_t cmd_n = 0;
static void serial_cmd() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch != '\n' && ch != '\r') { if (cmd_n < sizeof(cmd) - 1) cmd[cmd_n++] = ch; continue; }
    if (!cmd_n) continue;
    cmd[cmd_n] = 0; cmd_n = 0;
    if (!strcmp(cmd, "cal")) cal_start();
    else if (!strcmp(cmd, "next")) cal_button();          // same as pressing CAL
    else if (!strcmp(cmd, "raw")) stream_raw = !stream_raw;
    else if (!strcmp(cmd, "reset")) { cal_defaults(); cal_save(); Serial.println(F("defaults saved")); }
    else if (!strncmp(cmd, "dz ", 3)) { int v = atoi(cmd + 3); if (v >= 0 && v <= 20) { cal.dz_centre_pct = v; cal_save(); Serial.println(F("ok")); } }
    else if (!strcmp(cmd, "dump")) {
      for (int i = 0; i < N_AXES; i++) {
        Serial.print(NAMES[i]); Serial.print(F(" raw ")); Serial.print(raw_now[i]); Serial.print(F(" rest ")); Serial.print(cal.rest[i]);
        Serial.print(F(" lo ")); Serial.print(cal.lo[i]); Serial.print(F(" hi ")); Serial.print(cal.hi[i]);
        Serial.print(F(" out ")); Serial.println(axis_out(i, filt[i]));
      }
      Serial.print(F("deadzone centre % ")); Serial.println(cal.dz_centre_pct);
    } else Serial.println(F("commands: cal next dump raw dz <0..20> reset"));
  }
}

void setup() {
  pinMode(P_CAL, INPUT_PULLUP); pinMode(P_LED, OUTPUT);
  pinMode(P_MUX_RST, OUTPUT); digitalWrite(P_MUX_RST, LOW); delay(2); digitalWrite(P_MUX_RST, HIGH);
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);                 // 100 kHz: pedal cable ~1.5 m. 400 kHz is fine if all cables are short.
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setWireTimeout(3000, true);       // a stuck bus must not freeze the joystick
#endif
  if (!cal_load()) { cal_defaults(); }
  pcf_init(1, PCF_STICK); pcf_init(2, PCF_THR);
  for (int i = 0; i < N_AXES; i++) filt[i] = 0;
  joy.setXAxisRange(-32767, 32767); joy.setYAxisRange(-32767, 32767); joy.setZAxisRange(-32767, 32767);
  joy.setRxAxisRange(-32767, 32767); joy.setRyAxisRange(-32767, 32767); joy.setRzAxisRange(-32767, 32767);
  joy.begin(false);                      // send manually once per loop
}

void loop() {
  static uint32_t cal_down = 0, last_raw = 0;
  static uint8_t bad_mask = 0;
  serial_cmd();
  // CAL button: hold 2 s to start, short press for the next step
  bool down = digitalRead(P_CAL) == LOW;
  if (down && !cal_down) cal_down = millis();
  if (!down && cal_down) {
    uint32_t held = millis() - cal_down; cal_down = 0;
    if (held > 2000 && cal_step == 0) cal_start();
    else if (held > 30 && cal_step) cal_button();
  }

  bad_mask = 0;
  for (int i = 0; i < N_AXES; i++) {
    int r = read_as5600(AX_CH[i]);
    raw_now[i] = r;
    if (r < 0) { bad_mask |= 1 << i; filt[i] += (0 - filt[i]) * 0.2f; continue; }   // lost sensor: drift to rest/centre
    float d = delta_of(r, cal.rest[i]);
    if (fabs(d - filt[i]) > 1.0f) filt[i] += (d - filt[i]) * 0.5f;                   // 1-count hysteresis + light smoothing
    if (cal_step == 2) { if (d < sw_lo[i]) sw_lo[i] = (int16_t)d; if (d > sw_hi[i]) sw_hi[i] = (int16_t)d; }
  }
  int bs = read_pcf(1, PCF_STICK), bt = read_pcf(2, PCF_THR);
  if (bs < 0) bs = 0;
  if (bt < 0) bt = 0;

  joy.setXAxis(axis_out(A_ROLL, filt[A_ROLL]));
  joy.setYAxis(axis_out(A_PITCH, filt[A_PITCH]));
  joy.setZAxis(axis_out(A_THR, filt[A_THR]));
  joy.setRxAxis(axis_out(A_RUD, filt[A_RUD]));
  joy.setRyAxis(axis_out(A_BRK_L, filt[A_BRK_L]));
  joy.setRzAxis(axis_out(A_BRK_R, filt[A_BRK_R]));
  for (int b = 0; b < 4; b++) { joy.setButton(b, (bs >> b) & 1); joy.setButton(4 + b, (bt >> b) & 1); }
  joy.setHatSwitch(0, hat_angle(bs >> 4));
  joy.setHatSwitch(1, hat_angle(bt >> 4));
  joy.sendState();

  // LED: on = ok, fast blink = calibrating, slow blink = a sensor is missing
  uint32_t t = millis();
  digitalWrite(P_LED, cal_step ? (t / 100) % 2 : (bad_mask ? (t / 500) % 2 : 1));
  if (stream_raw && t - last_raw > 100) {
    last_raw = t;
    for (int i = 0; i < N_AXES; i++) { Serial.print(raw_now[i]); Serial.print(' '); }
    Serial.print(bs, HEX); Serial.print(' '); Serial.println(bt, HEX);
  }
}
