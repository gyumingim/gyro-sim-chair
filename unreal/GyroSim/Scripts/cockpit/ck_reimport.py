"""Developer helper: re-import the cockpit assets (Art/Cockpit) into the OPEN editor without rebuilding the map
(placement / pivots unchanged - after a manifest change run the full build_level.py with the editor closed).
In the editor:  exec(open(r"<project>/Scripts/cockpit/ck_reimport.py").read())"""
import os, unreal
_proj = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
_bl = os.path.join(_proj, "Scripts", "build_level.py")
_src = open(_bl, encoding="utf-8").read()
_src = _src[:_src.index("OBSOLETE = [")]          # imports, constants and helpers only
_g = {"__name__": "ck_reimport"}
exec(compile(_src, _bl, "exec"), _g)
_g["CK_PLACE"] = False
_p = os.path.join(_proj, "Scripts", "cockpit", "ue_cockpit.py")
exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), _g)
