# 외부 자료 출처와 라이선스

git 에는 **스크립트만** 들어 있다. 아래 자료는 스크립트가 받아서 `ThirdParty/`, `Content/ThirdParty/`, `Plugins/CesiumForUnreal/` 에 둔다 (모두 .gitignore).

| 자료 | 어디에 씀 | 출처 | 라이선스 | 받는 스크립트 |
|---|---|---|---|---|
| FlightGear F-16 기체·조종석 3D 모델과 텍스처 (commit `cc204ce03aa05500c4f9d904aff902efd5efaa90`) | 기체 겉모습, 조종석 안 (계기판·콘솔·사출좌석·HUD 틀), 스틱·스로틀·페달 | https://github.com/NikolaiVChr/f16 (저자: 저장소 `authors.txt`, `copyright.txt`) | **GPL-2.0-or-later**. 변환한 메시·텍스처도 GPL-2.0. 그래서 이 저장소에 올리지 않고 각자 받아서 변환한다. 남에게 배포하면 GPL 조건(원본 링크·라이선스 동봉)을 지킬 것 | `Scripts/fetch_f16_model.py` (사본 LICENSE·copyright·authors 를 `ThirdParty/f16_obj/` 에 같이 둠) |
| Poly Haven `concrete_pavement` (Charlotte Baglioni) | 활주로 콘크리트 | https://polyhaven.com/a/concrete_pavement | CC0 1.0 | `Scripts/fetch_textures.py` |
| Poly Haven `asphalt_02` | 유도로 | https://polyhaven.com/a/asphalt_02 | CC0 1.0 | `Scripts/fetch_textures.py` |
| Poly Haven `leafy_grass` | 활주로 옆 풀 | https://polyhaven.com/a/leafy_grass | CC0 1.0 | `Scripts/fetch_textures.py` |
| Sentinel-2 cloudless 2024 (EOX IT Services GmbH) | `photo` 모드일 때만 땅 위성사진 (실행 중 타일로 받음, 기본 격자 모드에선 안 씀) | https://s2maps.eu , 타일 `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/...` | **CC BY-NC-SA 4.0** (비상업 사용만). 표기: "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2024)" | 실행 중 Cesium 이 받음 |
| Cesium for Unreal 2.31.0 (UE 5.8 빌드) | 지구·지형 표시 | https://github.com/CesiumGS/cesium-unreal | Apache-2.0 | `Scripts/install_cesium.ps1` |
| Cesium World Terrain + Bing Maps Aerial (Cesium ion asset 1, 2) / Google Photorealistic 3D Tiles (2275207) | 토큰 있을 때 실제 지형·항공사진 | https://ion.cesium.com | Cesium ion 이용약관 (무료 계정, 화면에 출처 표시 — 켜 둠) | 실행 중 Cesium 이 받음 |
| 활주로 좌표 RKTU 06R/24L, 06L/24R | 활주로 위치·방향 | OpenStreetMap (Overpass `aeroway=runway`) | ODbL (© OpenStreetMap 기여자) | 값만 `sim/airfield.py` 에 적음 |
| 비행장 표고 191 ft | JSBSim 땅 높이 | OurAirports RKTU, https://en.wikipedia.org/wiki/Cheongju_International_Airport | 공개 데이터 | 값만 |
| 지오이드 높이 25.08 m (EGM2008) | 해발 ↔ 타원체 높이 | https://geographiclib.sourceforge.io/cgi-bin/GeoidEval?input=36.7154+127.4996 | — | 값만 |

로그인 없이 못 받아서 **쓰지 않은** 후보 (사용자가 원하면): Sketchfab / Fab 의 CC-BY F-16·조종석 모델 (다운로드에 계정 필요).
