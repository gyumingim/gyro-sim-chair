import sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simcore import Sim
from training.autopilot import Autopilot, hdg_err
def run(mode, goals, secs, label):
    sim = Sim(mode); ap = Autopilot(); t = 0; out = []
    gi = 0
    while t < secs:
        s = sim.packet()
        g = goals(s, t)
        sim.ctrl.update(ap.update(s, g, 1/60)); sim.frame(); t += 1/60
        if int(t*60) % 60 == 0: out.append((round(t), round(s['alt_m']/0.3048), round(s['kts']), round(s['phi'],1), round(s['theta'],1), round(s['psi']), round(s['vs_fpm']), round(s.get('cross_m',0),1), round(s['nz'],1), s['wow']))
    print(label); [print(' ', o) for o in out[::max(1,len(out)//14)]]
run('air', lambda s,t: dict(alt=6000, hdg=0, spd=350), 30, 'hold level')
run('air', lambda s,t: dict(alt=6000, hdg=90, spd=350), 40, 'turn to 090')
run('air', lambda s,t: dict(alt=8000, hdg=0, spd=350, vs_max=3000), 50, 'climb 8000')
run('air', lambda s,t: dict(alt=6000, hdg=0, spd=300), 40, 'slow to 300')
run('runway', lambda s,t: dict(thr=1.0, ground=True, rotate_kt=150, pitch=10, gear=1 if s['agl_m']<15 else 0), 45, 'takeoff')
run('approach', lambda s,t: dict(vs=-750, hdg=52.4, spd=160, gear=1), 40, 'approach')
