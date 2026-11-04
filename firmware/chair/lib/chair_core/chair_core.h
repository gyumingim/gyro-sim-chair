/* chair_core — hardware-free logic of the weight-shift chair controller.
 *
 * Plain C99 so the same file builds in the ESP32 firmware (PlatformIO / Arduino) and as a DLL for the
 * software-in-the-loop test (control/sil.py). No Arduino calls in here: main.cpp reads the sensors, fills
 * core_inputs_t, calls core_step() every 5 ms and writes core_outputs_t to the motor driver.
 *
 * Axes: 0 = roll, 1 = pitch.
 * Sign: roll  + = right side down,  roll weight  + = toward the right
 *       pitch + = nose up,          pitch weight + = toward the rear
 * Units: angles deg, weight positions mm (from the rail centre index), time ms.
 */
#ifndef CHAIR_CORE_H
#define CHAIR_CORE_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(CORE_DLL) && defined(_WIN32)
#define CORE_API __declspec(dllexport)
#else
#define CORE_API
#endif

enum { AX_ROLL = 0, AX_PITCH = 1, N_AX = 2 };

typedef enum {
  ST_BOOT = 0, ST_IDLE, ST_LOCKED, ST_CAL, ST_READY, ST_RUN, ST_RETURN, ST_FAULT, ST_ESTOP
} core_state_t;

/* fault bits (latched until RESET) */
enum {
  F_IMU = 1 << 0, F_POS_R = 1 << 1, F_POS_P = 1 << 2, F_OVERANGLE = 1 << 3,
  F_STALL_R = 1 << 4, F_STALL_P = 1 << 5, F_LIMIT = 1 << 6, F_CAL = 1 << 7,
  F_TIMEOUT = 1 << 8, /* info only: PC packets stopped during RUN (-> RETURN, not FAULT) */
  F_INTERLOCK = 1 << 9, /* info only: lock pin / deck switch opened while moving */
  F_DIR = 1 << 10       /* motor / encoder direction mismatch (wiring or sign setting) */
};

/* calibration sub-steps (per axis) */
typedef enum { CS_NONE = 0, CS_HOME, CS_LEVEL, CS_KPLUS, CS_KMINUS, CS_BACK, CS_DONE, CS_FAIL } cal_step_t;

typedef struct {
  /* drive */
  float v_full_mm_s[N_AX];    /* weight speed at duty 1.0 (WGM40C 1/218 + 20T: ~41.7 mm/s ASSUMED, measure on the chair) */
  float v_max_mm_s[N_AX];     /* speed limit used by the controller */
  float a_max_mm_s2[N_AX];    /* weight acceleration limit (~ v_max / pendulum period -> no residual swing) */
  float duty_min;             /* static friction feed-forward (0..1) */
  float kp_x;                 /* position loop gain 1/s */
  float ki_th;                /* angle trim integral, mm per (deg s) */
  float trim_max_mm;          /* |trim| clamp */
  float kd_gyro;              /* optional swing damping, mm per (deg/s); 0 = off (default) */
  /* geometry */
  float travel_mm[N_AX];      /* weight travel from the centre index to each end (+-) */
  float soft_margin_mm;       /* stay this far from the ends */
  float k_design[N_AX];       /* design d(tan th)/dx per mm, for calibration sanity (index.html m/Md) */
  /* cue limits (firmware defence; the PC bridge limits too) */
  float rate_max_deg_s[N_AX];
  float soft_lim_deg[N_AX];   /* |cue| clamp */
  float return_rate_deg_s;    /* RETURN / watchdog ramp to level */
  /* safety */
  float fault_angle_deg[N_AX];/* |angle| beyond this for fault_angle_ms -> FAULT */
  uint32_t fault_angle_ms;
  uint32_t pc_timeout_ms;     /* no valid packet in RUN -> RETURN */
  uint32_t imu_timeout_ms;
  float pos_jump_mm;          /* max change of the weight position per step before it's called a sensor fault */
  uint32_t stall_ms;          /* |duty| > 0.4 this long with < stall_mm movement -> stall */
  float stall_mm;
  /* calibration */
  float cal_step_mm;          /* weight offset used to measure the gain */
  uint32_t cal_settle_ms;     /* wait after each move (>= 2 pendulum periods) */
  uint32_t cal_avg_ms;        /* average the angle over this (>= 1 period) */
  float cal_level_tol_deg;
  float home_speed_frac;
  /* attitude filter */
  float comp_tau_s;           /* complementary filter time constant */
  float lp_tau_s;             /* low-pass of the angle used by the trim loop */
} core_params_t;

typedef struct {
  uint32_t now_ms;
  /* IMU on the cage, already remapped to x fwd, y left, z up; acc in g, gyro in deg/s */
  uint8_t imu_ok;
  float acc[3];
  float gyro[3];
  /* weight position sensors (AS5600 on the idler/drive shaft, unwrapped multi-turn), raw mm */
  uint8_t pos_ok[N_AX];
  float pos_raw_mm[N_AX];
  /* switches: 1 = condition present. Limit switches are NC: an open wire reads as "hit" (fail-safe). */
  uint8_t lim_pos[N_AX];      /* end switch on the + side hit (or wire broken) */
  uint8_t lim_neg[N_AX];
  uint8_t index[N_AX];        /* centre index sensor active */
  uint8_t estop_ok;           /* 24 V motor bus present (safety relay closed) */
  uint8_t pins_stowed;        /* all lock pins sit in their holders (series loop closed) */
  uint8_t deck_stowed;        /* boarding deck parked away (switch closed) */
} core_inputs_t;

typedef struct {
  float duty[N_AX];           /* -1..1 to the motor driver (+ = weight toward +) */
  uint8_t state;
  uint32_t faults;
  uint8_t buzzer;
  uint8_t led;                /* 0 off, 1 on, 2 blink */
  uint8_t save_nvs;           /* main.cpp should persist core_t.imu_zero now */
} core_outputs_t;

typedef struct {
  float x0, k, th_sum, cnt, xp, thp, thn, t_start, prog;
  uint32_t t_mark, n;
  uint8_t step, iter, dir, found;
} cal_axis_t;

typedef struct {
  core_params_t P;
  uint8_t state;
  uint32_t faults;
  /* attitude */
  float th[N_AX], th_lp[N_AX], rate[N_AX];
  float imu_zero[N_AX];
  float gyro_bias[3];          /* estimated while LOCKED (chair held still by the pins) */
  float zero_sum[N_AX];
  uint16_t zero_n;
  uint8_t att_init;
  uint32_t imu_last_ok_ms, over_ms;
  /* position */
  float pos_off[N_AX];
  uint8_t home_ok[N_AX];
  float x[N_AX], x_prev[N_AX];
  /* control */
  float th_ref[N_AX], cue[N_AX];
  float x_ref[N_AX], trim[N_AX], v_cmd[N_AX];
  float x0[N_AX], k_tan[N_AX], max_pos_deg[N_AX], max_neg_deg[N_AX];
  uint8_t cal_ok;
  cal_axis_t cal[N_AX];
  /* stall */
  uint32_t stall_t0[N_AX];
  float stall_x0[N_AX];
  /* comms */
  uint32_t last_pkt_ms, seq_last, pkts_ok, pkts_bad;
  uint8_t pkt_seen;
  uint8_t cmd_arm, cmd_disarm, cmd_cal, cmd_zero, cmd_reset;
  uint32_t now_ms, last_ms;
  uint8_t zero_pending;
  uint16_t sw;                /* last switch / sensor bits, for telemetry */
} core_t;

CORE_API void core_default_params(core_params_t *p);
CORE_API void core_init(core_t *c, const core_params_t *p);
CORE_API void core_step(core_t *c, const core_inputs_t *in, core_outputs_t *out);
/* feed one received line ("$C,..*HH" or "$K,..*HH", without the newline). Returns 1 if accepted. */
CORE_API int core_rx_line(core_t *c, const char *line, uint32_t now_ms);
/* write one telemetry line (with "*HH", no newline) into buf. Returns its length. */
CORE_API int core_tx_line(const core_t *c, char *buf, int n);
CORE_API uint8_t core_crc8(const char *s, int n);
CORE_API int core_sizeof(void);
CORE_API const char *core_state_name(int s);

#ifdef __cplusplus
}
#endif
#endif
