/* chair_core.c — see chair_core.h. State machine, attitude filter, weight position control, calibration, safety. */
#include "chair_core.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DEG (180.0f / 3.14159265f)
#define RAD (3.14159265f / 180.0f)

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
static float signf(float v) { return v > 0 ? 1.0f : (v < 0 ? -1.0f : 0.0f); }

CORE_API int core_sizeof(void) { return (int)sizeof(core_t); }

CORE_API const char *core_state_name(int s) {
  static const char *n[] = {"BOOT", "IDLE", "LOCKED", "CAL", "READY", "RUN", "RETURN", "FAULT", "ESTOP"};
  return (s >= 0 && s <= ST_ESTOP) ? n[s] : "?";
}

CORE_API void core_default_params(core_params_t *p) {
  memset(p, 0, sizeof(*p));
  for (int i = 0; i < N_AX; i++) {
    p->v_full_mm_s[i] = 41.7f;     /* 25 rpm x 100 mm/rev (ASSUMED, measure with the real motor) */
    p->v_max_mm_s[i] = 40.0f;
  }
  p->a_max_mm_s2[AX_ROLL] = 18.0f;   /* ~ v / T (T roll ~2.2 s) */
  p->a_max_mm_s2[AX_PITCH] = 20.0f;  /* ~ v / T (T pitch ~2.0 s) */
  p->duty_min = 0.10f;
  p->kp_x = 2.0f;
  p->ki_th = 4.0f;
  p->trim_max_mm = 150.0f;   /* rider leaning 3 cm ~ 5 deg roll ~ 130 mm of weight */
  p->kd_gyro = 0.0f;
  p->travel_mm[AX_ROLL] = 565.0f;
  p->travel_mm[AX_PITCH] = 600.0f;
  p->soft_margin_mm = 15.0f;
  p->k_design[AX_ROLL] = 18.61f / 27.59f / 1000.0f;   /* index.html m / Md, per mm */
  p->k_design[AX_PITCH] = 14.44f / 30.61f / 1000.0f;
  p->rate_max_deg_s[AX_ROLL] = 1.45f;
  p->rate_max_deg_s[AX_PITCH] = 1.0f;
  p->soft_lim_deg[AX_ROLL] = 18.0f;
  p->soft_lim_deg[AX_PITCH] = 14.0f;
  p->return_rate_deg_s = 0.5f;
  p->fault_angle_deg[AX_ROLL] = 24.0f;
  p->fault_angle_deg[AX_PITCH] = 19.0f;
  p->fault_angle_ms = 300;
  p->pc_timeout_ms = 500;
  p->imu_timeout_ms = 100;
  p->pos_jump_mm = 5.0f;
  p->stall_ms = 1500;
  p->stall_mm = 3.0f;
  p->cal_step_mm = 150.0f;
  p->cal_settle_ms = 4000;
  p->cal_avg_ms = 3000;
  p->cal_level_tol_deg = 0.3f;
  p->home_speed_frac = 0.5f;
  p->comp_tau_s = 0.5f;
  p->lp_tau_s = 1.0f;
}

CORE_API void core_init(core_t *c, const core_params_t *p) {
  memset(c, 0, sizeof(*c));
  if (p) c->P = *p; else core_default_params(&c->P);
  c->state = ST_BOOT;
  for (int i = 0; i < N_AX; i++) {
    c->k_tan[i] = c->P.k_design[i];
    c->max_pos_deg[i] = c->P.soft_lim_deg[i];
    c->max_neg_deg[i] = -c->P.soft_lim_deg[i];
  }
}

/* ---------------- CRC-8 (poly 0x07) over the text between '$' and '*' ---------------- */
CORE_API uint8_t core_crc8(const char *s, int n) {
  uint8_t crc = 0;
  for (int i = 0; i < n; i++) {
    crc ^= (uint8_t)s[i];
    for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  }
  return crc;
}

/* split s in place at ',' into at most n tokens */
static int split(char *s, char **tok, int n) {
  int k = 0;
  tok[k++] = s;
  for (; *s && k < n; s++) if (*s == ',') { *s = 0; tok[k++] = s + 1; }
  return k;
}

static int seq_newer(uint32_t a, uint32_t b) { return (int32_t)(a - b) > 0; }

CORE_API int core_rx_line(core_t *c, const char *line, uint32_t now_ms) {
  const char *star = strrchr(line, '*');
  if (line[0] != '$' || !star || strlen(star) < 3) { c->pkts_bad++; return 0; }
  int body = (int)(star - line - 1);
  unsigned crc = (unsigned)strtoul(star + 1, NULL, 16);
  if (core_crc8(line + 1, body) != (uint8_t)crc) { c->pkts_bad++; return 0; }
  char buf[96];
  if (body >= (int)sizeof(buf)) { c->pkts_bad++; return 0; }
  memcpy(buf, line + 1, body); buf[body] = 0;
  char *t[6];
  int nt = split(buf, t, 6);
  if (nt < 3) { c->pkts_bad++; return 0; }
  char kind = t[0][0];
  uint32_t seq = (uint32_t)strtoul(t[1], NULL, 10);
  if (c->pkt_seen && !seq_newer(seq, c->seq_last)) { c->pkts_bad++; return 0; }  /* old / duplicate */
  if (kind == 'C') {
    if (nt < 5) { c->pkts_bad++; return 0; }
    long r = strtol(t[2], NULL, 10), pch = strtol(t[3], NULL, 10), fl = strtol(t[4], NULL, 10);
    if (labs(r) > 9000 || labs(pch) > 9000) { c->pkts_bad++; return 0; }
    if (fl & 1) { c->cue[AX_ROLL] = r / 100.0f; c->cue[AX_PITCH] = pch / 100.0f; }
    else { c->cue[AX_ROLL] = 0; c->cue[AX_PITCH] = 0; }   /* sim not alive: level */
  } else if (kind == 'K') {
    const char *w = t[2];
    if (!strcmp(w, "ARM")) c->cmd_arm = 1;
    else if (!strcmp(w, "DISARM") || !strcmp(w, "STOP")) c->cmd_disarm = 1;
    else if (!strcmp(w, "CAL")) c->cmd_cal = 1;
    else if (!strcmp(w, "ZERO")) c->cmd_zero = 1;
    else if (!strcmp(w, "RESET")) c->cmd_reset = 1;
    else if (strcmp(w, "PING")) { c->pkts_bad++; return 0; }
  } else { c->pkts_bad++; return 0; }
  c->seq_last = seq; c->pkt_seen = 1; c->last_pkt_ms = now_ms; c->pkts_ok++;
  return 1;
}

CORE_API int core_tx_line(const core_t *c, char *buf, int n) {
  char body[200];
  int len = snprintf(body, sizeof(body), "T,%lu,%s,%d,%d,%lx,%x,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%ld,%ld",
                     (unsigned long)c->now_ms, core_state_name(c->state), c->cal[0].step, c->cal[1].step, (unsigned long)c->faults, (unsigned)c->sw,
                     (int)lroundf(c->th[0] * 100), (int)lroundf(c->th[1] * 100),
                     (int)lroundf(c->x[0] * 10), (int)lroundf(c->x[1] * 10), (int)c->cal_ok, (int)(c->home_ok[0] && c->home_ok[1]),
                     (int)lroundf(c->max_pos_deg[0] * 100), (int)lroundf(c->max_neg_deg[0] * 100),
                     (int)lroundf(c->max_pos_deg[1] * 100), (int)lroundf(c->max_neg_deg[1] * 100),
                     (int)lroundf(c->th_ref[0] * 100), (int)lroundf(c->th_ref[1] * 100),
                     lroundf(c->k_tan[0] * 1e7f), lroundf(c->k_tan[1] * 1e7f));
  if (len < 0 || len >= (int)sizeof(body)) return 0;
  return snprintf(buf, n, "$%s*%02X", body, core_crc8(body, len));
}

/* ---------------- helpers ---------------- */
static void stop_axis(core_t *c, int i, core_outputs_t *o) { c->v_cmd[i] = 0; o->duty[i] = 0; }

/* trapezoid move toward c->x_ref[i] at <= vlim, writes duty. Honours the limit switches. */
static void drive_axis(core_t *c, int i, const core_inputs_t *in, core_outputs_t *o, float vlim, float dt) {
  const core_params_t *P = &c->P;
  float err = c->x_ref[i] - c->x[i];
  float a = P->a_max_mm_s2[i];
  float v_des = clampf(P->kp_x * err, -vlim, vlim);
  float vbrake = sqrtf(2.0f * a * fabsf(err));        /* decelerate in time */
  if (fabsf(v_des) > vbrake) v_des = signf(v_des) * vbrake;
  float dv = clampf(v_des - c->v_cmd[i], -a * dt, a * dt);
  c->v_cmd[i] += dv;
  if ((in->lim_pos[i] && c->v_cmd[i] > 0) || (in->lim_neg[i] && c->v_cmd[i] < 0)) c->v_cmd[i] = 0;
  if (fabsf(err) < 0.5f && fabsf(c->v_cmd[i]) < 1.0f) c->v_cmd[i] = 0;
  float d = c->v_cmd[i] / P->v_full_mm_s[i];
  if (fabsf(c->v_cmd[i]) > 0.3f) d += signf(d) * P->duty_min;
  o->duty[i] = clampf(d, -1.0f, 1.0f);
}

/* constant-speed search (homing): no position target */
static void drive_speed(core_t *c, int i, const core_inputs_t *in, core_outputs_t *o, float v, float dt) {
  float a = c->P.a_max_mm_s2[i];
  c->v_cmd[i] += clampf(v - c->v_cmd[i], -a * dt, a * dt);
  if ((in->lim_pos[i] && c->v_cmd[i] > 0) || (in->lim_neg[i] && c->v_cmd[i] < 0)) c->v_cmd[i] = 0;
  float d = c->v_cmd[i] / c->P.v_full_mm_s[i];
  if (fabsf(c->v_cmd[i]) > 0.3f) d += signf(d) * c->P.duty_min;
  o->duty[i] = clampf(d, -1.0f, 1.0f);
}

static float soft_lo(const core_t *c, int i) { return -c->P.travel_mm[i] + c->P.soft_margin_mm; }
static float soft_hi(const core_t *c, int i) { return c->P.travel_mm[i] - c->P.soft_margin_mm; }

static void attitude(core_t *c, const core_inputs_t *in, float dt) {
  if (!in->imu_ok) return;
  c->imu_last_ok_ms = in->now_ms;
  float fx = in->acc[0], fy = in->acc[1], fz = in->acc[2];
  /* gimbal: roll ring outside, pitch cage inside, IMU on the cage */
  float r_acc = atan2f(fy, sqrtf(fx * fx + fz * fz)) * DEG;
  float p_acc = atan2f(fx, fz) * DEG;
  float pr = c->th[AX_PITCH] * RAD;
  float r_rate = in->gyro[0] / cosf(pr);
  float p_rate = -in->gyro[1];
  if (!c->att_init) {
    c->th[0] = r_acc - c->imu_zero[0]; c->th[1] = p_acc - c->imu_zero[1];
    c->th_lp[0] = c->th[0]; c->th_lp[1] = c->th[1];
    c->att_init = 1;
    return;
  }
  float a = c->P.comp_tau_s / (c->P.comp_tau_s + dt);
  float acc_v[2] = {r_acc - c->imu_zero[0], p_acc - c->imu_zero[1]};
  float rt[2] = {r_rate, p_rate};
  for (int i = 0; i < N_AX; i++) {
    c->rate[i] = rt[i];
    c->th[i] = a * (c->th[i] + rt[i] * dt) + (1 - a) * acc_v[i];
    c->th_lp[i] += (c->th[i] - c->th_lp[i]) * dt / (c->P.lp_tau_s + dt);
  }
}

static void enter(core_t *c, uint8_t s) {
  if (c->state == s) return;
  c->state = s;
  for (int i = 0; i < N_AX; i++) { c->stall_t0[i] = 0; }
}

static void fault(core_t *c, uint32_t f) { c->faults |= f; enter(c, ST_FAULT); }

static void cal_begin(core_t *c) {
  for (int i = 0; i < N_AX; i++) {
    memset(&c->cal[i], 0, sizeof(cal_axis_t));
    c->cal[i].step = c->home_ok[i] ? CS_LEVEL : CS_HOME;
    c->cal[i].dir = 0;                       /* decided in CS_HOME after watching the angle for 2.5 s */
    c->cal[i].t_mark = c->now_ms;
    c->cal[i].x0 = c->home_ok[i] ? (c->cal_ok ? c->x0[i] : 0.0f) : 0.0f;
    c->cal[i].t_start = c->x[i];             /* homing: where the search started */
    c->x_ref[i] = c->x[i];
    c->trim[i] = 0;
  }
  c->cal_ok = 0;
  enter(c, ST_CAL);
}

/* one axis of the calibration. Returns the step. phase in cal.n: 0 moving, 1 settling, 2 averaging */
static void cal_axis(core_t *c, int i, const core_inputs_t *in, core_outputs_t *o, float dt) {
  cal_axis_t *k = &c->cal[i];
  const core_params_t *P = &c->P;
  uint32_t now = in->now_ms;
  if (k->step == CS_HOME) {
    if (in->index[i]) {                       /* found the centre mark */
      c->pos_off[i] = in->pos_raw_mm[i];
      c->x[i] = 0; c->x_prev[i] = 0; c->home_ok[i] = 1;
      c->v_cmd[i] = 0; o->duty[i] = 0;
      k->step = CS_LEVEL; k->x0 = 0; k->n = 0; k->iter = 0;
      c->x_ref[i] = 0;
      return;
    }
    if (k->n == 0) {                          /* watch the angle first: tilted + means the weight sits on the + side */
      stop_axis(c, i, o);
      k->th_sum += c->th[i]; k->cnt += 1.0f;
      if (in->now_ms - k->t_mark < 2500) return;
      k->dir = (k->th_sum / k->cnt) < -0.3f ? 1 : 0;   /* 0 = search negative first, 1 = positive */
      k->n = 1; k->t_start = c->x[i];
    }
    float v = P->home_speed_frac * P->v_max_mm_s[i] * (k->dir ? 1.0f : -1.0f);
    if (!k->dir && in->lim_neg[i]) { k->dir = 1; k->found++; c->v_cmd[i] = 0; }
    else if (k->dir && in->lim_pos[i]) { k->dir = 0; k->found++; c->v_cmd[i] = 0; }
    if (k->found >= 2) { k->step = CS_FAIL; stop_axis(c, i, o); return; }   /* both ends seen, no index */
    if (fabsf(c->x[i] - k->t_start) > 2.5f * P->travel_mm[i] + 50) { k->step = CS_FAIL; stop_axis(c, i, o); return; }
    drive_speed(c, i, in, o, v, dt);
    return;
  }
  if (k->step == CS_DONE || k->step == CS_FAIL) { c->x_ref[i] = k->step == CS_DONE ? k->x0 : c->x[i]; drive_axis(c, i, in, o, P->v_max_mm_s[i], dt); return; }
  /* target of this step */
  float tgt = k->x0;
  if (k->step == CS_KPLUS) tgt = clampf(k->x0 + P->cal_step_mm, soft_lo(c, i), soft_hi(c, i));
  if (k->step == CS_KMINUS) tgt = clampf(k->x0 - P->cal_step_mm, soft_lo(c, i), soft_hi(c, i));
  c->x_ref[i] = clampf(tgt, soft_lo(c, i), soft_hi(c, i));
  drive_axis(c, i, in, o, P->v_max_mm_s[i], dt);
  if (k->n == 0) {                            /* moving */
    if (fabsf(c->x[i] - c->x_ref[i]) < 1.0f && c->v_cmd[i] == 0) { k->n = 1; k->t_mark = now; }
    return;
  }
  if (k->n == 1) {                            /* settle */
    if (now - k->t_mark >= P->cal_settle_ms) { k->n = 2; k->t_mark = now; k->th_sum = 0; k->cnt = 0; }
    return;
  }
  /* averaging */
  k->th_sum += c->th[i]; k->cnt += 1.0f;
  if (now - k->t_mark < P->cal_avg_ms) return;
  float th_avg = k->th_sum / k->cnt;
  k->n = 0;
  if (k->step == CS_BACK) { k->step = CS_DONE; return; }
  if (k->step == CS_LEVEL) {
    if (fabsf(th_avg) < P->cal_level_tol_deg) { k->step = CS_KPLUS; return; }
    if (++k->iter > 5) { k->step = CS_FAIL; return; }
    k->x0 -= tanf(th_avg * RAD) / P->k_design[i];
    k->x0 = clampf(k->x0, soft_lo(c, i), soft_hi(c, i));
    return;
  }
  if (k->step == CS_KPLUS) { k->thp = th_avg; k->xp = c->x[i]; k->step = CS_KMINUS; return; }
  if (k->step == CS_KMINUS) {
    k->thn = th_avg;
    float xp = k->xp, xn = c->x[i];
    float kk = (tanf(k->thp * RAD) - tanf(k->thn * RAD)) / (xp - xn);
    if (!(kk > 0.5f * P->k_design[i] && kk < 1.8f * P->k_design[i])) { k->step = CS_FAIL; return; }
    k->k = kk;
    k->x0 = 0.5f * (xp + xn) - (tanf(k->thp * RAD) + tanf(k->thn * RAD)) / (2.0f * kk);
    k->x0 = clampf(k->x0, soft_lo(c, i), soft_hi(c, i));
    k->step = CS_BACK;
    return;
  }
}

/* ---------------- main step ---------------- */
CORE_API void core_step(core_t *c, const core_inputs_t *in, core_outputs_t *o) {
  const core_params_t *P = &c->P;
  float dt = c->last_ms ? (in->now_ms - c->last_ms) / 1000.0f : 0.005f;
  if (dt <= 0 || dt > 0.1f) dt = 0.005f;
  c->last_ms = c->now_ms = in->now_ms;
  memset(o, 0, sizeof(*o));

  attitude(c, in, dt);
  c->sw = (uint16_t)((in->estop_ok ? 1 : 0) | (in->pins_stowed ? 2 : 0) | (in->deck_stowed ? 4 : 0) | (in->imu_ok ? 8 : 0) |
                     (in->pos_ok[0] ? 16 : 0) | (in->pos_ok[1] ? 32 : 0) | (in->lim_pos[0] ? 64 : 0) | (in->lim_neg[0] ? 128 : 0) |
                     (in->lim_pos[1] ? 256 : 0) | (in->lim_neg[1] ? 512 : 0) | (in->index[0] ? 1024 : 0) | (in->index[1] ? 2048 : 0));

  /* positions */
  int pos_bad = 0;
  for (int i = 0; i < N_AX; i++) {
    if (!in->pos_ok[i]) { pos_bad |= 1 << i; continue; }
    float x = in->pos_raw_mm[i] - c->pos_off[i];
    if (c->state != ST_BOOT && fabsf(x - c->x[i]) > P->pos_jump_mm) pos_bad |= 1 << i;
    c->x_prev[i] = c->x[i]; c->x[i] = x;
  }

  /* commands (one-shot flags) */
  uint8_t arm = c->cmd_arm, disarm = c->cmd_disarm, cal = c->cmd_cal, zero = c->cmd_zero, reset = c->cmd_reset;
  c->cmd_arm = c->cmd_disarm = c->cmd_cal = c->cmd_zero = c->cmd_reset = 0;

  if (c->state == ST_BOOT) {
    if (in->now_ms >= 1500 && c->att_init) {
      for (int i = 0; i < N_AX; i++) { c->pos_off[i] = in->pos_raw_mm[i]; c->x[i] = 0; }
      enter(c, ST_IDLE);
    }
    o->state = c->state; o->led = 2; return;
  }

  int interlock_ok = in->pins_stowed && in->deck_stowed;
  int moving_state = c->state == ST_CAL || c->state == ST_READY || c->state == ST_RUN || c->state == ST_RETURN;

  /* 1. E-stop: motor power is already cut by the safety relay; we just follow */
  if (!in->estop_ok && c->state != ST_ESTOP) enter(c, ST_ESTOP);
  if (c->state == ST_ESTOP) {
    if (in->estop_ok && reset) {
      c->faults = 0;
      if (c->cal_ok && interlock_ok) { c->th_ref[0] = c->th_lp[0]; c->th_ref[1] = c->th_lp[1]; enter(c, ST_RETURN); }
      else enter(c, ST_IDLE);
    }
    o->state = c->state; o->faults = c->faults; o->led = 2; o->buzzer = 0;
    for (int i = 0; i < N_AX; i++) stop_axis(c, i, o);
    return;
  }

  /* 2. interlocks (lock pin in, boarding deck present): no motion at all */
  if (!interlock_ok && c->state != ST_LOCKED && c->state != ST_FAULT) {
    if (moving_state && (fabsf(c->v_cmd[0]) > 0 || fabsf(c->v_cmd[1]) > 0)) c->faults |= F_INTERLOCK;
    enter(c, ST_LOCKED);
  }

  /* 3. sensor / angle faults while the weights may move */
  if (moving_state) {
    if (in->now_ms - c->imu_last_ok_ms > P->imu_timeout_ms) fault(c, F_IMU);
    if (pos_bad & 1) fault(c, F_POS_R);
    if (pos_bad & 2) fault(c, F_POS_P);
    int over = fabsf(c->th[0]) > P->fault_angle_deg[0] || fabsf(c->th[1]) > P->fault_angle_deg[1];
    if (over) { if (!c->over_ms) c->over_ms = in->now_ms; else if (in->now_ms - c->over_ms > P->fault_angle_ms) fault(c, F_OVERANGLE); }
    else c->over_ms = 0;
    for (int i = 0; i < N_AX; i++) {
      int homing = c->state == ST_CAL && c->cal[i].step == CS_HOME;
      if (!homing && c->home_ok[i] && (in->lim_pos[i] || in->lim_neg[i])) fault(c, F_LIMIT);
    }
  }

  float vmax[N_AX] = {P->v_max_mm_s[0], P->v_max_mm_s[1]};
  switch (c->state) {
    case ST_LOCKED:
      for (int i = 0; i < N_AX; i++) stop_axis(c, i, o);
      c->cal_ok = 0;                                  /* new rider -> calibrate again (home is kept) */
      if (zero && in->imu_ok && c->att_init) {        /* pins in = mechanically level: this is 0 deg */
        c->imu_zero[0] += c->th[0]; c->imu_zero[1] += c->th[1];
        c->th[0] = c->th[1] = 0; c->th_lp[0] = c->th_lp[1] = 0;
        o->save_nvs = 1;
      }
      if (interlock_ok) enter(c, ST_IDLE);
      o->led = 1;
      break;

    case ST_IDLE:
      for (int i = 0; i < N_AX; i++) stop_axis(c, i, o);
      if (cal && in->imu_ok && in->pos_ok[0] && in->pos_ok[1]) cal_begin(c);
      o->led = 0;
      break;

    case ST_CAL: {
      if (disarm) { c->cal_ok = 0; for (int i = 0; i < N_AX; i++) stop_axis(c, i, o); enter(c, ST_IDLE); break; }
      int done = 1, fail = 0;
      for (int i = 0; i < N_AX; i++) {
        cal_axis(c, i, in, o, dt);
        if (c->cal[i].step == CS_FAIL) fail = 1;
        if (c->cal[i].step != CS_DONE) done = 0;
      }
      if (fail) { for (int i = 0; i < N_AX; i++) stop_axis(c, i, o); fault(c, F_CAL); break; }
      if (done && fabsf(c->x[0] - c->cal[0].x0) < 1.5f && fabsf(c->x[1] - c->cal[1].x0) < 1.5f) {
        for (int i = 0; i < N_AX; i++) {
          c->x0[i] = c->cal[i].x0; c->k_tan[i] = c->cal[i].k;
          c->max_pos_deg[i] = atanf(c->k_tan[i] * (soft_hi(c, i) - c->x0[i])) * DEG;
          c->max_neg_deg[i] = atanf(c->k_tan[i] * (soft_lo(c, i) - c->x0[i])) * DEG;
          c->th_ref[i] = 0; c->trim[i] = 0;
        }
        c->cal_ok = 1;
        enter(c, ST_READY);
      }
      o->led = 2;
      break;
    }

    case ST_READY:
    case ST_RUN:
    case ST_RETURN: {
      if (c->state == ST_READY && arm && c->pkt_seen && in->now_ms - c->last_pkt_ms < P->pc_timeout_ms) enter(c, ST_RUN);
      if (c->state == ST_READY && cal) { cal_begin(c); break; }
      if (c->state == ST_RUN && disarm) enter(c, ST_RETURN);
      if (c->state == ST_RUN && in->now_ms - c->last_pkt_ms > P->pc_timeout_ms) { c->faults |= F_TIMEOUT; enter(c, ST_RETURN); }
      int settled = 1;
      for (int i = 0; i < N_AX; i++) {
        float tgt = 0, rate = P->return_rate_deg_s;
        if (c->state == ST_RUN) {
          float lim_hi = fminf(P->soft_lim_deg[i], c->max_pos_deg[i] - 1.0f);
          float lim_lo = fmaxf(-P->soft_lim_deg[i], c->max_neg_deg[i] + 1.0f);
          tgt = clampf(c->cue[i], lim_lo, lim_hi);
          rate = P->rate_max_deg_s[i];
        }
        c->th_ref[i] += clampf(tgt - c->th_ref[i], -rate * dt, rate * dt);
        float x_ff = c->x0[i] + tanf(c->th_ref[i] * RAD) / c->k_tan[i];
        /* slow trim on the measured angle (rider moved, k a bit off) — only when the weight has caught up */
        if (fabsf(c->x_ref[i] - c->x[i]) < 10.0f) {
          c->trim[i] += P->ki_th * (c->th_ref[i] - c->th_lp[i]) * dt;
          c->trim[i] = clampf(c->trim[i], -P->trim_max_mm, P->trim_max_mm);
        }
        float xr = x_ff + c->trim[i] - P->kd_gyro * c->rate[i];
        float xr_c = clampf(xr, soft_lo(c, i), soft_hi(c, i));
        if (xr != xr_c) c->trim[i] -= (xr - xr_c) * 0.5f * dt;     /* anti-windup at the rail ends */
        c->x_ref[i] = xr_c;
        drive_axis(c, i, in, o, vmax[i], dt);
        if (fabsf(c->th_ref[i]) > 0.05f || fabsf(c->x[i] - c->x_ref[i]) > 2.0f) settled = 0;
      }
      if (c->state == ST_RETURN && settled) enter(c, ST_READY);
      o->led = c->state == ST_RUN ? 1 : 2;
      break;
    }

    case ST_FAULT:
      /* bring the weights back to level by position only (no IMU trust), half speed; stop an axis whose sensor failed */
      for (int i = 0; i < N_AX; i++) {
        int pos_fail = (i == 0 ? (c->faults & (F_POS_R | F_STALL_R)) : (c->faults & (F_POS_P | F_STALL_P))) || !in->pos_ok[i];
        if (pos_fail || !c->home_ok[i] || !interlock_ok) { stop_axis(c, i, o); continue; }
        float home = c->cal_ok ? c->x0[i] : 0.0f;
        c->x_ref[i] = clampf(home, soft_lo(c, i), soft_hi(c, i));
        drive_axis(c, i, in, o, 0.5f * vmax[i], dt);
      }
      if (reset && in->imu_ok && in->pos_ok[0] && in->pos_ok[1] && !(in->lim_pos[0] && in->lim_neg[0]) && !(in->lim_pos[1] && in->lim_neg[1])) {
        c->faults = 0; c->cal_ok = 0;
        for (int i = 0; i < N_AX; i++) stop_axis(c, i, o);
        enter(c, interlock_ok ? ST_IDLE : ST_LOCKED);
      }
      o->buzzer = 1; o->led = 2;
      break;
    default:
      for (int i = 0; i < N_AX; i++) stop_axis(c, i, o);
  }

  /* stall detection on any commanded motion */
  for (int i = 0; i < N_AX; i++) {
    if (fabsf(o->duty[i]) > 0.4f) {
      if (!c->stall_t0[i]) { c->stall_t0[i] = in->now_ms ? in->now_ms : 1; c->stall_x0[i] = c->x[i]; }
      else if (in->now_ms - c->stall_t0[i] > P->stall_ms) {
        if (fabsf(c->x[i] - c->stall_x0[i]) < P->stall_mm) { o->duty[i] = 0; c->v_cmd[i] = 0; fault(c, i == 0 ? F_STALL_R : F_STALL_P); }
        c->stall_t0[i] = 0;
      }
    } else c->stall_t0[i] = 0;
  }
  o->state = c->state;
  o->faults = c->faults;
}
