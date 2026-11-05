"""Rebuild our cockpit art: textures (PIL) then geometry (Blender, background) -> unreal/GyroSim/Art/Cockpit/.
    python Scripts/cockpit/build_cockpit.py [--blender <path to blender.exe>] [--no-preview]
Blender 4.5 LTS (portable zip is fine, no install): https://download.blender.org/release/Blender4.5/
Default path: $BLENDER or C:/Users/<you>/tools/blender/blender-4.5.*/blender.exe or blender on PATH.
model_blender.py writes to the STAGING folder Art/Cockpit_v2 by default (cockpit v3, 11-05; the live Art/Cockpit is
only replaced by hand, see IMPORT.md); --out <dir> passes an output folder through (e.g. --out ../../Art/Cockpit).
Then import into Unreal: editor CLOSED -> build_level.py (README), or for asset-only changes in the open editor:
    exec(open(r"<project>/Scripts/cockpit/ck_reimport.py").read())
"""
import glob, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def find_blender(argv):
    if "--blender" in argv:
        return argv[argv.index("--blender") + 1]
    if os.environ.get("BLENDER"):
        return os.environ["BLENDER"]
    c = sorted(glob.glob(os.path.expanduser("~/tools/blender/blender-4.5*/blender.exe")))
    if c:
        return c[-1]
    return shutil.which("blender")


if __name__ == "__main__":
    subprocess.check_call([sys.executable, os.path.join(HERE, "make_textures.py")])
    b = find_blender(sys.argv)
    if not b:
        sys.exit("Blender not found (--blender <path> or BLENDER env var)")
    args = [b, "-b", "--factory-startup", "-P", os.path.join(HERE, "model_blender.py"), "--"]
    for flag in ("--no-preview", "--no-bake"):
        if flag in sys.argv:
            args.append(flag)
    if "--out" in sys.argv:
        args += ["--out", os.path.abspath(sys.argv[sys.argv.index("--out") + 1])]
    subprocess.check_call(args)
