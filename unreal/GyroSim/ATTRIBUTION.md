# 외부 자료 출처와 라이선스

git 에는 **스크립트만** 들어 있다. 아래 자료는 스크립트가 받아서 `ThirdParty/`, `Content/ThirdParty/`, `Plugins/CesiumForUnreal/` 에 둔다 (모두 .gitignore).

| 자료 | 어디에 씀 | 출처 | 라이선스 | 받는 스크립트 |
|---|---|---|---|---|
| FlightGear F-16 기체 3D 모델과 텍스처 (commit `cc204ce03aa05500c4f9d904aff902efd5efaa90`) | 기체 겉모습만 (추적 시점, 캐노피 유리, 바퀴). 조종석 안은 더 이상 안 씀 | https://github.com/NikolaiVChr/f16 (저자: 저장소 `authors.txt`, `copyright.txt`) | **GPL-2.0-or-later**. 변환한 메시·텍스처도 GPL-2.0. 그래서 이 저장소에 올리지 않고 각자 받아서 변환한다. 남에게 배포하면 GPL 조건(원본 링크·라이선스 동봉)을 지킬 것 | `Scripts/fetch_f16_model.py` (사본 LICENSE·copyright·authors 를 `ThirdParty/f16_obj/` 에 같이 둠) |
| Poly Haven `concrete_pavement` (Charlotte Baglioni) | 활주로 콘크리트 | https://polyhaven.com/a/concrete_pavement | CC0 1.0 | `Scripts/fetch_textures.py` |
| Poly Haven `asphalt_02` | 유도로 | https://polyhaven.com/a/asphalt_02 | CC0 1.0 | `Scripts/fetch_textures.py` |
| Poly Haven `leafy_grass` | 활주로 옆 풀 | https://polyhaven.com/a/leafy_grass | CC0 1.0 | `Scripts/fetch_textures.py` |
| Poly Haven `curly_teddy_natural` (colormass 촬영, Rico Cilliers 처리) | 조종석 좌석 방석 (노멀 맵만, 색은 검정으로) | https://polyhaven.com/a/curly_teddy_natural | CC0 1.0 | `Scripts/fetch_textures.py` (11-05 사실감 작업) |
| Poly Haven `fabric_leather_02` (Rob Tuytel) | 스틱·스로틀 손잡이 결 (노멀 맵만) | https://polyhaven.com/a/fabric_leather_02 | CC0 1.0 | `Scripts/fetch_textures.py` (11-05) |
| Sentinel-2 cloudless 2024 (EOX IT Services GmbH) | `photo` 모드일 때만 땅 위성사진 (실행 중 타일로 받음, 기본 격자 모드에선 안 씀) | https://s2maps.eu , 타일 `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/...` | **CC BY-NC-SA 4.0** (비상업 사용만). 표기: "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2024)" | 실행 중 Cesium 이 받음 |
| Cesium for Unreal 2.31.0 (UE 5.8 빌드) | 지구·지형 표시 | https://github.com/CesiumGS/cesium-unreal | Apache-2.0 | `Scripts/install_cesium.ps1` |
| Cesium World Terrain + Bing Maps Aerial (Cesium ion asset 1, 2) / Google Photorealistic 3D Tiles (2275207) | 토큰 있을 때 실제 지형·항공사진 | https://ion.cesium.com | Cesium ion 이용약관 (무료 계정, 화면에 출처 표시 — 켜 둠) | 실행 중 Cesium 이 받음 |
| 활주로 좌표 RKTU 06R/24L, 06L/24R | 활주로 위치·방향 | OpenStreetMap (Overpass `aeroway=runway`) | ODbL (© OpenStreetMap 기여자) | 값만 `sim/airfield.py` 에 적음 |
| 비행장 표고 191 ft | JSBSim 땅 높이 | OurAirports RKTU, https://en.wikipedia.org/wiki/Cheongju_International_Airport | 공개 데이터 | 값만 |
| 지오이드 높이 25.08 m (EGM2008) | 해발 ↔ 타원체 높이 | https://geographiclib.sourceforge.io/cgi-bin/GeoidEval?input=36.7154+127.4996 | — | 값만 |
| **Copernicus DEM GLO-30** (30 m, 2021 판 COG) — 대한민국 땅이 있는 1° 칸 24 장 | `vworld` 모드의 실제 지형(Cesium 지형 타일)과 JSBSim 땅 높이 (산에 부딪히면 추락) | AWS 공개 버킷 https://copernicus-dem-30m.s3.amazonaws.com/ (https://registry.opendata.aws/copernicus-dem/ , 계정 없음) | Copernicus DEM 라이선스 (무료, 출처 표시 의무). 표기: "**© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved**" — 화면 출처 판(`sim/vworld_terrain_attribution.png`)과 지형 `layer.json` 에 넣음. 원본·타일은 저장소에 안 올림 (`C:\GyroSimTiles\terrain`) | `sim/terrain_fetch.py`, `sim/terrain_build.py` |
| **국토교통부 GIS건물통합정보** (V-World 공간정보 다운로드, 충청북도 `AL_D010_43_20261009`) | `vworld` 모드의 3D 건물 (윤곽 + 높이를 밀어 올린 블록, 청주 RKTU 30 km 안) 과 서버의 건물 충돌 | https://www.vworld.kr/dtmk/dtmk_ntads_s001.do (사용자가 직접 받음) | **CC BY** (V-World 자료 페이지 표시, 출처 표시). 표기: "**국토교통부 GIS건물통합정보 (CC BY)**" — 화면 출처 판(`sim/vworld_buildings_attribution.png`)과 `tileset.json` asset.copyright. 원본·타일은 저장소에 안 올림 (`C:\GyroSimTiles\incoming`, `C:\GyroSimTiles\buildings`) | `sim/buildings_build.py` |
| EGM2008 지오이드 2.5′ 격자 (한국 주변 창만) | 해발(DEM) → 타원체 높이(Cesium) 변환 | https://cdn.proj.org/us_nga_egm08_25.tif (PROJ 데이터, NGA 원본) | public domain (NGA) | `sim/terrain_fetch.py` |

로그인 없이 못 받아서 **쓰지 않은** 후보 (사용자가 원하면): Sketchfab / Fab 의 CC-BY F-16·조종석 모델 (다운로드에 계정 필요).

## 조종석 안 (우리가 만든 것 — git 에 들어 있음)
`Art/Cockpit/` (FBX, PNG), `Content/Cockpit/` 는 `Scripts/cockpit/*.py` 가 **처음부터 생성**한 우리 형상·텍스처다 (남의 모델·텍스처를 복사·변환하지 않음).
글자는 Windows 의 Bahnschrift 글꼴로 그린 그림만 들어간다 (글꼴 파일은 배포하지 않음).
11-05 사실감 작업: AO·모서리·때 마스크(`tex/T_CkShellMasks.png`, Blender Cycles 로 우리 형상에서 구움), 페인트 결 노멀(`T_CkPaintN`),
캐노피 긁힘·얼룩(`T_CkCanopyScratch`), 빈 판의 흐린 디테일·경고 줄무늬·명판(`T_CkPanels`) 도 모두 우리 코드가 그린 것. 실물 사진은 텍스처로 쓰지 않음. 도구: Blender 4.5 LTS (GPL, 도구로만 사용 — 만든 결과물은 우리 것), Pillow.

배치·비율을 볼 때 참고한 **공개(public domain) 사진** — 미국 정부 기관 사진, 형태만 참고하고 이미지는 쓰지 않음:
| 참고 | 출처 |
|---|---|
| T-7A Red Hawk 조종석 (가운데 스틱 훈련기, USAF) | https://www.aetc.af.mil/News/Photos/igphoto/2003361327 , https://www.eglin.af.mil/News/Photos/igphoto/2003706611/ |
| F/A-18 조종석 (NASA Armstrong) | https://www.nasa.gov/image-detail/amf-afrc2018-0212-019 , https://www.nasa.gov/image-article/hd-display-mounted-rear-instrument-panel-sra/ |
상용 시뮬레이터(DCS, MSFS)는 눈으로만 비교했고 자산은 전혀 쓰지 않았다. 위치·치수 근거는 우리 의자 모델(`index.html`)과 `hardware/` 의 조종 장치.

## 강의 내용·교관 말 (sim/training/, 11-04)
강의 순서와 요령은 아래 공개 자료를 참고해 **우리 말로 새로 쓴 것** (문장 복사 없음). 숫자는 시뮬레이터 F-16 (JSBSim) 에 맞춰 봇 시험으로 조정.
| 참고 | 쓴 곳 | 출처 | 라이선스 |
|---|---|---|---|
| FAA Airplane Flying Handbook (FAA-H-8083-3C) | 강의 순서, 수평·선회·상승강하·장주·안정 접근·플레어 요령 | https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/airplane_handbook | 미국 정부 저작물 (public domain) |
| FAA Pilot's Handbook of Aeronautical Knowledge (FAA-H-8083-25C) | 계기 설명 (속도계·고도계·승강계·자세계), G·받음각 설명 | https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/phak | public domain |
| General Dynamics F-16 (Wikipedia) | 9 G 한계, 플래퍼론 | https://en.wikipedia.org/wiki/General_Dynamics_F-16_Fighting_Falcon | 사실만 인용 |
| RKTU 청주 활주로 06R | 활주로 이름·방향 | 위 활주로 좌표 줄, 대한민국 항공정보간행물 (AIP, 링크 확인 안 함) | 사실만 |
교관 음성: Windows 에 들어 있는 SAPI 한국어 음성 (Microsoft Heami) 으로 실행 중 읽음 — 음성 파일을 배포하지 않음.
한글 화면 글자: 맑은 고딕으로 그린 그림만 (글꼴 파일 배포 안 함).
