"""MPC_GyroTune: live look parameters (Content/Python/tune_look.py writes them at Play from C:/GyroSimTiles/tune/params.json).
Imported by ground_material.py / buildings_material.py (editor only). Three float4 vectors so one Custom node input each:
  TuneA = (TuneOn, GdBase, GdBaseH, GdGrad)        TuneOn 0 (default) = the materials use their own scalar parameters
  TuneB = (GdGradH, GdFloor, GdAO, GdTint)
  TuneC = (GdSat, GdGroundAO, GdCanyonAlb, GdLeanDark)
  TuneD = (PhGain, PhGamma, PhSat, PhKnee)       ground photo v2 (11-11, M_GyroGround only); default 1,1,1,1 = identity
"""
import unreal

PATH = "/Game/Materials/Ground/MPC_GyroTune"
VECS = ("TuneA", "TuneB", "TuneC", "TuneD")
DEFAULT = {"TuneD": (1.0, 1.0, 1.0, 1.0)}          # identity even before tune_look writes it


def ensure():
    EAL = unreal.EditorAssetLibrary
    mpc = unreal.load_asset(PATH) if EAL.does_asset_exist(PATH) else None
    if mpc is None:
        mpc = unreal.AssetToolsHelpers.get_asset_tools().create_asset("MPC_GyroTune", "/Game/Materials/Ground", unreal.MaterialParameterCollection,
                                                                      unreal.MaterialParameterCollectionFactoryNew())
    # add only the missing ones: re-creating a parameter gives it a new id and breaks every material already built on it
    vps = list(mpc.get_editor_property("vector_parameters"))
    have = {str(v.get_editor_property("parameter_name")) for v in vps}
    if any(n not in have for n in VECS):
        for n in VECS:
            if n not in have:
                v = unreal.CollectionVectorParameter()
                v.set_editor_property("parameter_name", n)
                v.set_editor_property("default_value", unreal.LinearColor(*DEFAULT.get(n, (0.0, 0.0, 0.0, 0.0))))
                vps.append(v)
        mpc.set_editor_property("vector_parameters", vps)
        EAL.save_asset(PATH, only_if_is_dirty=False)
    return mpc


def inputs(m, X, x=-1300, y=2900, names=("TuneA", "TuneB", "TuneC")):
    """CollectionParameter expressions for the named vectors (default TuneA..C, as M_GyroBuilding) -> [(expr, input name)]"""
    mpc = ensure()
    out = []
    for i, n in enumerate(names):
        cp = X(unreal.MaterialExpressionCollectionParameter, x, y + 100 * i)
        cp.set_editor_property("collection", mpc)
        cp.set_editor_property("parameter_name", n)
        out.append((cp, n))
    return out
