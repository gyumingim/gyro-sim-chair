# 지도 품질 올리기 — 한국 지도 데이터 후보 조사

작성 2026-11-05. 조사만 했다 (데이터를 받지 않았고, V-World API 는 한 번도 부르지 않았다 — 공개 웹 페이지만 읽음).
공식 페이지에서 확인한 것은 그냥 쓰고, 확인 못 한 것은 **추정** 이라고 표시했다. 지금 상태(V-World 사진 줌 ≤16 로컬 프록시,
Copernicus GLO-30 자체 지형, 청주 RKTU, F-16)는 `docs/vworld-integration.md` 에 있다.

---

## 0. 결론 먼저 — 추천 순위 (품질 이득 ÷ 수고)

| 순위 | 무엇 | 왜 | 수고 | 가입 |
|---|---|---|---|---|
| **1** | **물(바다·호수·강) 마스크** — OSM 물 폴리곤으로 우리 지형 타일에 water mask 넣기 | 바다·저수지가 반짝이고 반사됨. 지금은 바다가 사진 그대로(무광). 지형 빌더가 이미 우리 코드라 한 단계만 추가. Cesium 지형 액터에 `EnableWaterMask` 속성이 이미 있음 | **작음** (1–2 일, **추정**) | 없음 |
| **2** | **청주 비행장 실제 자료 (AIP)** — 활주로 끝 좌표·표고, 접근등(ALSF-I·SSALR), PAPI, ILS 주파수 | 전투기 훈련의 핵심 장면(착륙·야간 접근)이 진짜가 됨. 공개 자료, 파일 하나 수준 | 작음–중간 | 없음 |
| **3** | **GIS건물통합정보** (국토교통부, 전국 약 1,440 만 동 윤곽 + 높이 A16) → 밀어올린 3D 건물 타일 | 도시 위 저공비행 때 가장 큰 차이. OSM 건물(한국 약 120 만 동, **추정**)보다 10 배 이상 많고 높이가 대장 값. 라이선스 공공누리 1 유형(출처표시) | 중간 (3–5 일, **추정**) | V-World 또는 공공데이터포털 로그인 (**추정**) |
| **4** | **항공 장애물 CSV** (항공교통본부 장애물정보 + 항공장애표시등 시설정보) | 송전탑·굴뚝·고층건물에 빨간 장애등 → 야간·저공 실감. 파일 하나 | 작음 | 공공데이터포털 로그인 (**추정**) |
| **5** | **국토지리정보원 항공 정사영상 25 cm (도시 12 cm)** — 비행장 주변·자주 나는 곳만 파일로 | V-World(줌 16 ≈ 2.4 m/px 로 제한해 쓰는 중)보다 훨씬 선명하고, **파일 한 번 받기라 V-World 호출·저장 약관 문제가 없음**. 단 전국은 수 TB(**추정**)라 일부 지역만 | 중간 (재투영·타일화) | 국토정보플랫폼 가입 |

그다음 (이득은 있지만 수고가 큼): 토지피복도·임상도·나무 높이로 **나무·숲 뿌리기**(저공에서만 보임), 1:5,000 수치지도
등고선으로 **비행장 주변 고해상 지형** 만들기. **하지 말 것**: V-World 3D 건물·지형 꺼내기, 국토지리정보원 5 m DEM·3D 건물모형(공개제한,
개인 반출 사실상 불가), 국토위성영상(온라인판은 좌표가 지워져 있음).

**약관 위험 요약**
1. 한국 정부 측량 자료(정사영상·수치지도 등)는 **GitHub(해외 서버)에 올리지 않는다** — 공간정보관리법 측량성과 국외 반출 원칙 금지 (아래 9절). 공개 저장소에는 **변환 스크립트만**, 데이터·타일은 `C:\GyroSimTiles\` 등 git 밖.
2. 항공사진(국토영상정보)은 **공공누리 3 유형 = 변경금지**. 정사영상은 공공데이터포털에 "이용허락범위 제한 없음" 으로 나오지만 같은 기관 자료라 3 유형일 수 있음 → 받을 때 화면의 이용조건을 확인. 재투영·타일 자르기가 "변경" 인지 불분명 (**추정**: 형식 변환은 보통 괜찮다고 보지만 확인 필요).
3. 군 시설: V-World·국토지리정보원 사진은 기지를 가린다. 가려진 사진 위에 다른 자료(Sentinel-2 등)로 기지를 되살려 섞지 않는다 (V-World 약관 14조, `vworld-integration.md` 1절).
4. OSM(ODbL)으로 만든 타일·DB 를 배포하면 "같은 라이선스로 공유" 의무가 생김 — 이 PC 안에서만 쓰면 출처 표시만.

---

## 1. 비교표

| 자료 | 시각적 이득 | 해상도·정확도 | 형식 | 한국 크기 | 받는 법 | 가입 | 라이선스·약관 | Unreal/Cesium 넣기 |
|---|---|---|---|---|---|---|---|---|
| GIS건물통합정보 (국토교통부) | 도시 3D 건물 | 건물 윤곽(수치지형도·지적 기반), 높이 m (건축물대장) | SHP, EPSG:5174(Bessel TM, 2022 기준) | 약 6.6 GB, 1,439 만 건 (2022) | V-World 공간정보 다운로드 / 공공데이터포털 파일 (시도별) | 로그인 **추정** | 공공누리 1 유형 (출처표시) | 중간: 밀어올려 3D Tiles (pg2b3dm 등) |
| OSM 건물 (Cesium OSM Buildings 또는 Geofabrik) | 3D 건물 (거칠게) | 약 120 만 동 **추정**, 높이 대부분 없음 **추정** | PBF/SHP | 277 MB PBF (전체 OSM) | Geofabrik 파일 / ion 스트리밍 (이미 씀) | 없음 (ion 은 토큰) | ODbL | 이미 됨 |
| V-World 3D 건물 | — | — | 뷰어 내부 3D Tiles | — | **불가** | — | 공개제한 3 차원 공간정보 (약관 14·18조) | 안 함 |
| NGII 3D 건물모형 LoD1 / 건물높이DB | 정확한 건물 높이 | LoD1 전국, 1:5,000 높이DB | — | — | 공문 신청 + 보안심사, 또는 안심구역 안에서만 | 기관 | 공개제한, 학술·공공 목적 한정 | 개인 사실상 불가 |
| 공개 DEM 90 m (NGII) | 없음 (지금보다 거침) | 90 m | IMG | — | 국토정보플랫폼 | 로그인 | 이용허락 제한 없음 | 쓸 이유 없음 |
| NGII 5 m DEM / 도시 1 m DEM | 산·계곡 선명 | 5 m 전국, 1 m 도시 | — | 수십 GB **추정** | 공간정보 안심구역(센터 안 분석) | 기관·심사 | 공개제한 | 반출 불가 **추정** |
| 1:5,000 수치지도 v2 (등고선·표고점·도로·하천·건물) | 비행장 주변 고해상 지형, 하천·도로 선 | 1:5,000 (등고선 5 m 간격 **추정**) | SHP, NGI | 도엽 단위, 전국 수십 GB **추정** | 국토정보플랫폼 파일 | 로그인 | 측량성과 — 국외 반출 금지 | 중간–큼: 등고선→DEM 보간 |
| 항공 정사영상 (NGII) | 고해상 사진 | 일반 25 cm, 도시 12 cm, 2010 년 이후 | TIFF | 전국 수 TB **추정** | 국토정보플랫폼 파일 (대용량 전송 프로그램) | 로그인 | 포털 표기 "제한 없음"; 항공사진은 공공누리 3 유형(변경금지) | 중간: 재투영→웹 메르카토르 타일→프록시 |
| 국토위성영상 (CAS500-1) | — | 0.5 m | 주문 모자이크 | — | 주문 (7 일), 온라인은 좌표 제거 | 로그인 | 보안 규정 | 비추천 |
| V-World 줌 17–19 | 고해상 사진 | 줌 19 ≈ 0.3 m/px | JPEG 타일 | 전국 z19 ≈ 527 GB **추정** | API 만 (호출 수↑ 4 배씩) | 이미 있음 | 저장 금지 조항 (19조) | 이미 됨 (캐시에 있을 때만) |
| 환경부 토지피복지도 세분류 | 숲·논·밭·도시 구분 → 나무/질감 | 41 개 분류, 2024 년 영상 기준 | SHP | 큼 **추정** | 환경공간정보서비스 자료신청 → 다운로드 | 회원가입 | 출처표시 (1 유형, WMS 기준 — SHP 은 확인 필요) | 중간: 래스터화→PCG/풀 마스크 |
| ESA WorldCover 2021 | 위와 같음 (거칠게) | 10 m, 11 분류 | COG GeoTIFF 3°×3° | 한국 몇 장 (~1 GB **추정**) | AWS S3 (`--no-sign-request`) | 없음 | CC BY 4.0 | 쉬움 |
| 산림청 임상도 1:5,000 | 침엽/활엽/혼효·수종 → 나무 종류 | 1:5,000, 2025 판까지 | SHP, EPSG:5179 | 큼 **추정** | 산림청 산림공간정보 무료신청 (일반인) | 가입 **추정** | 확인 필요 | 중간 (토지피복과 함께) |
| Meta/WRI 나무 높이 (CHM) | 나무 키 | 1 m (v1), CHMv2 | GeoTIFF | 한국 수십 GB **추정** | AWS S3 (계정 없이) | 없음 | CC BY 4.0 | 중간 |
| OSM 물·해안선·도로 | 물 마스크, 강·호수 반짝임, 야간 도로 불빛 | 지역마다 다름, 해안선 대체로 좋음 **추정** | PBF/SHP | 277 MB | Geofabrik, osmdata.openstreetmap.de | 없음 | ODbL | 쉬움 (물 마스크) |
| AIP Korea (RKTU AD 2) | 활주로·등화·ILS 진짜 값 | 공표값 (0.01″, 0.1 m) | HTML/PDF 차트 | 작음 | aim.koca.go.kr eAIP | 없음 | 정부 공표물, 재배포 조건 확인 필요 | 작음–중간 |
| AMDB (비행장 매핑) | 유도로·계류장 윤곽 | — | 다운로드 **추정** | — | aim.koca.go.kr/aim/amdb.do | 로그인 **추정** | 확인 필요 | **RKTU 없음** (민간 11 곳만) |
| 항공교통본부 장애물정보 CSV | 송전탑·굴뚝·건물 | 좌표 DMS, 높이 | CSV | 작음 | 공공데이터포털 | 로그인 **추정** | 이용허락 제한 없음 | 작음 |
| 항공장애표시등·주간표지 CSV (TS) | 빨간 장애등 위치·종류 | 지면·해발 높이, 위경도 | CSV | 작음 | 공공데이터포털 | 로그인 **추정** | 이용허락 제한 없음 | 작음 |
| NASA Black Marble (VNP46A4) | 야간 도시 불빛 분포 | 500 m (15″) | HDF5 | 작음 | NASA LAADS | Earthdata 가입 | NASA 공개 자료 **추정** | 작음 (단, 거침) |
| 정밀도로지도 (NGII) | 고속도로 차선·표지 | cm 급 | 벡터·점군 | 큼 | 국토정보플랫폼 | 로그인, 기관·기업 대상 | 확인 필요 | 과함 (비행 고도에선 안 보임) |

---

## 2. 건물

### 2-1. GIS건물통합정보 (추천 3 위)

- **무엇**: 수치지형도(연속수치지도 건물 레이어)·연속지적도 건물 공간정보 + 건축행정시스템(세움터) 건축물대장 속성을 건물 단위로 합친 자료.
  전국, 공공데이터포털 "일별" 판은 매일 갱신. https://www.data.go.kr/biz/dcat/metadata/15052097.do , https://www.data.go.kr/data/15083092/fileData.do
- **라이선스**: 공공데이터포털 15083092 = "공공저작물 : 출처표시 (제 1유형)" (상업 가능, 변경 가능, 출처 표시). 일별 판 15052097 = "이용허락범위 제한 없음".
- **어디서**: V-World 공간정보 다운로드 목록 첫 줄에 "GIS건물통합정보" (SHP, 기준일 2026-10-22) 가 있다 — https://www.vworld.kr/dtmk/dtmk_ntads_s001.do .
  같은 자료가 공공데이터포털에도 있음. 이 다운로드 메뉴는 "개별 라이선스(공공누리)가 붙은 자료" 라서 V-World 약관 19조 저장 금지의 예외에 해당 (`vworld-integration.md` 1절).
  로그인 필요 여부는 페이지에 자물쇠 표시가 없었지만 실제 다운로드는 로그인일 것 (**추정**).
- **크기·좌표**: 2022 년 판 시도별 17 파일 `AL_{시도코드}_D010_YYYYMMDD`, 합계 6,605 MB, 14,391,694 건, **EPSG:5174 (Bessel TM)**. 경기 235 MB, 충북 85 MB, 서울 83 MB.
  https://gnuhacker.com/2022/04/04/01_GIS%EA%B1%B4%EB%AC%BC%ED%86%B5%ED%95%A9%EC%A0%95%EB%B3%B4/ (블로그, 국가공간정보포털 요약을 옮긴 것). 지금 판의 좌표계는 받아서 `.prj` 확인 (지적도 쪽은 EPSG:5186 이라 바뀌었을 수 있음, **추정**).
- **높이**: 필드 `A16` = 높이(m) — https://www.vw-lab.com/51 . 층수 필드 이름은 출처마다 다름(블로그 댓글은 A32 라 함, **확인 필요**) → 받으면 함께 오는 **컬럼정의서(엑셀)** 로 확인.
- **높이가 비는 비율**: 공개 자료에서 숫자를 못 찾음. 높이는 건축물대장 값이라 **대장 없는 건물(가설·무허가·창고·군 시설)은 0 또는 빈 값일 것** (**추정**). 같은 자료로 "5 년 지난 대단지 아파트가 통째로 빠진 경우도 있다" 는 사용 후기 있음 (vw-lab). 
  → 받은 뒤 첫 일: 시도별로 `A16 > 0` 비율, 층수만 있는 비율, 둘 다 없는 비율을 세서 이 문서에 적는다. 대체 규칙: 높이 → 층수 × 3.3 m → 용도별 기본값(주택 6 m, 그 밖 4 m, **임의 가정**).
- **청주 기지 안**: 군 시설은 대장·공개 지도에서 빠질 것 (**추정**) → 기지 안 건물은 따로 만들거나 비워 둠.
- **넣는 법 (계획)**: SHP → (GDAL) EPSG:4326 → 바닥 높이 = 우리 DEM 의 그 윤곽 안 최소값 → 높이만큼 밀어올림 → 3D Tiles(b3dm/glb) →
  로컬 프록시가 `tileset.json` 제공 → Unreal 에 `Cesium3DTileset`(URL 소스) 하나 추가 (지금 OSM 건물 자리를 대체).
  도구 후보: pg2b3dm (PostGIS → 3D Tiles, MIT, Polygon/MultiPolygon 입력 — 밀어올림은 직접 해서 넣어야 할 수 있음) https://github.com/Geodan/pg2b3dm ,
  또는 Python 으로 glb 직접 쓰기(지형 빌더처럼). 1,400 만 동이면 시도별·줌별 타일로 나누고 작은 건물은 먼 레벨에서 뺀다.
- **주의**: Copernicus GLO-30 은 **DSM**(건물 꼭대기 포함) 이라 아파트 단지 위에서 땅이 이미 수 m–수십 m 솟아 있을 수 있다 → 건물이 그만큼 더 높아 보임 (**추정**). 단지 위 DEM 과 건물 높이를 같이 보고 필요하면 건물 윤곽 안 DEM 을 주변 최저값으로 깎는다.

### 2-2. 다른 건물 자료

- **OSM 건물 / Cesium OSM Buildings (이미 씀, ion 96188)**: 한국 OSM 건물은 약 120 만 동이라는 HDX 내보내기 설명이 있음 (검색 요약, **추정**;
  https://geo.btaa.org/catalog/d020b777-3c0d-44f4-98aa-a70f28763601 ). 공식 1,440 만 건과 비교하면 약 1/10. `building:levels` 태그는 있지만 채워진 비율 미확인.
  전체 OSM 한국 파일 277 MB PBF, 562 MB SHP (2026-11-03 자료) https://download.geofabrik.de/asia/south-korea.html , ODbL.
- **Microsoft Global ML Building Footprints**: 한국 포함 여부·높이를 확인 못 함 https://github.com/microsoft/globalmlbuildingfootprints . 공식 자료가 있으니 우선순위 낮음.
- **V-World 3D 건물**: 2019 년 7 월 공개제한 정책으로 3D 건물 API 공개 중단 (논문 https://koreascience.kr/article/JAKO202404861569434.pdf 검색 요약),
  약관 14조 "3차원 공간정보 ... 공개제한", 18조 다른 경로 다운로드 금지 (`vworld-integration.md` 6절). **쓰지 않는다.**
  참고: V-World LOD1 은 층수 × 3 m 로 만든 것이라 실제 높이가 아니라는 설명도 있음 (검색 요약, **추정**).
- **NGII 3D 건물모형 (2021, 약 1,900 만 동, "1 단계 수준")**: 항공사진으로 높이를 읽어 만든 자료지만 **공개 제한**, "공간정보 제공 신청서" 필요
  (2021-06-29 보도, https://smartcity.go.kr 의 해당 보도 검색 요약; https://www.asiae.co.kr/en/article/2021062911045711440 ).
  국토정보플랫폼 "건물높이공간정보" 도 "공문을 통해 ... 제공 신청이 완료된 사용자에 한하여", "학술연구, 공공복리 및 안전 등의 한정된 목적",
  영리 목적은 보안심사 필요 — https://map.ngii.go.kr/bl/map/buldEncView.do . **개인 프로젝트로는 어려움.**
- **공간정보 안심구역**: 5 m DEM, 1 m 도시 DEM, 정사영상 12/25/50 cm, LoD1–4 건물, 1:5,000 건물높이DB 를 "보안이 확보된 구역" 안에서 분석하게 해 줌.
  센터 밖으로 가져가는 길은 페이지에 없음 → 시뮬레이터용으로는 못 씀 (**추정**). https://www.datafreezone.or.kr/center_01.do

---

## 3. 지형

- **지금 Copernicus GLO-30 이 개인이 쉽게 얻을 수 있는 것 중 최선에 가깝다.** 한국 공개 DEM 은 90 m 뿐이고 (국토정보플랫폼 "공개DEM", 로그인, 무료, 이용허락 제한 없음,
  https://www.data.go.kr/data/15059920/fileData.do ), 5 m 전국·1 m 도시 DEM 은 **공개제한** (안심구역 목록 https://www.datafreezone.or.kr/center_01.do ).
  → `vworld-integration.md` 5절의 "5 m DEM 넣는 법" 계획은 자료를 얻을 수 없어서 보류가 맞음.
- **대안 (비행장 주변만)**: 1:5,000 **수치지도 v2.0** (SHP/NGI, 국토정보플랫폼, 로그인, 대용량 전송 프로그램 자동 설치) 의 등고선·표고점으로 직접 DEM 보간
  (예: GDAL `gdal_grid` / TIN). 1:5,000 등고선 간격은 5 m (**추정**). 산 능선·비행장 주변이 30 m DEM 보다 나아짐. 수치지도는 측량성과라 git·해외 반출 금지.
  수치지도 제공 형식 근거: 블로그 정리 https://www.iamhy.com/12015 (**추정**, 공식 확인 필요). 수고 중간–큼, 이득은 저공 산악에서만.
- 참고: 공표 비행장 값으로 청주 활주로를 평탄화한 지금 방식이 비행장 높이 문제는 이미 해결함. AIP 의 활주로 끝 표고(06L 50.6 m, 24R 56.5 m 등, 4절)를 쓰면
  지금의 "한 높이 58.2 m 평면" 대신 **활주로 경사(약 6 m / 2.7 km)** 까지 맞출 수 있다.

---

## 4. 비행장 (AIP Korea) — 추천 2 위

- **eAIP**: https://aim.koca.go.kr/eaipPub/Package/history-en-GB.html — 현재 AIRAC AMDT 10/26 (2026-10-28 발효). AD 2 목록에 **RKTU Cheongju INTL 있음** (18 개 비행장).
  ENR 5.4 (지상 100 m 이상 항로 장애물) 항목 있음.
- **RKTU AD 2 내용 (확인함)** https://aim.koca.go.kr/eaipPub/Package/2026-10-28-AIRAC/html/eAIP/KR-AD-2.RKTU-en-GB.html :
  - 활주로 4 개 끝: 06L/24R 2,744 × 60 m, 06R/24L 2,744 × 45 m, 진방위 052.42°/232.43°, 끝 좌표 0.01″ 단위, 끝 표고 06L 50.6 / 24R 56.5 / 06R 52.2 / 24L 58.4 m.
  - 등화: 06L SSALR(717 m), 24R·24L ALSF-I(900 m), 06R SALS(291 m), 모두 PAPI 3° 양쪽.
  - ILS: 24R LOC 111.70 (ICHG), 24L 109.35 (ICHL), 06L 110.30 (ICHJ), 06R 109.15 (ICHR), CHO VOR/DME 109.00.
  - 차트: 비행장도, 지상이동도, 장애물도 A/B, 계기접근도 등 (PDF).
- **시뮬레이터에 넣을 것**: 활주로 메시 위치·길이·폭·경사 점검, 접근등 줄(ALSF-I 900 m, 시퀀스 플래셔), PAPI 4 등, 활주로 가장자리·중심선 등,
  HUD/계기 ILS 주파수·활주로 방위. 비행장도 PDF 로 유도로·계류장 윤곽을 손으로 따서 메시로 (비행장 하나라 손작업이 빠름).
- **AMDB (비행장 매핑 다운로드)**: https://aim.koca.go.kr/aim/amdb.do — RKSI, RKSS, RKPC, RKPK, RKNY, RKJY, RKPU, RKTH, RKPD, RKJB, RKTL 11 곳만, **RKTU 없음**.
  나중에 김포·김해 등을 추가할 때 유용. 형식·조건 미확인.
- **TOD (공항 주변 지형·장애물 조회)**: https://aim.koca.go.kr/etod/?language=en_US — 조회 서비스, 다운로드 여부 미확인.
- 약관: 정부 공표 항공정보. 값(좌표·주파수)을 시뮬레이터에 쓰는 것은 문제 없을 것 (**추정**). 차트 PDF 자체를 저장소에 넣지는 않는다.

---

## 5. 장애물·높은 구조물 — 추천 4 위

- **국토교통부 항공교통본부_장애물정보** (CSV, 연 1 회, 2025-08-05 판, 이용허락 제한 없음): 공항식별자, 장애물 이름, 구조물 종류, 높이·단위, 시도/시군구/읍면동, 좌표(DMS).
  https://www.data.go.kr/data/15145041/fileData.do (메타데이터 https://www.data.go.kr/biz/dcat/metadata/15145041.do ). 공항 주변 장애물 위주일 것 (**추정**).
- **한국교통안전공단_항공장애표시등 및 주간표지 시설 정보** (CSV, 2019–2026 기준, 이용허락 제한 없음): 장애물 이름·종류, 지면 높이, 해수면 높이, 위경도, 등 종류·개수.
  https://www.data.go.kr/data/15150345/fileData.do . 지방항공청에 신고된 물체 기준 → 송전탑·굴뚝·고층 건물 상당수 포함 (**추정**).
- **넣는 법**: CSV → 종류별 간단 메시(철탑·굴뚝·기둥) + 빨간 점멸등(야간), 높이는 CSV 값. 건물 위 장애등은 3D 건물과 같은 자리에 등만.
  송전선 자체(선)는 이 자료에 없음 → OSM `power=line/tower` 로 보충 (ODbL, 한국 채움 정도 미확인).

---

## 6. 사진 (영상)

- **NGII 항공 정사영상 (추천 5 위)**: 도시 12 cm, 일반 25 cm 항공사진으로 만든 정사영상, 2010 년 이후 촬영분, **TIFF**, 무료, 국토정보플랫폼에서 대용량 전송 프로그램으로 받음.
  공공데이터포털 표기 "이용허락범위 제한 없음" https://www.data.go.kr/data/15059919/fileData.do . 같은 기관의 **항공사진(국토영상정보)** 은
  "출처표시, 변경금지 (제 3유형)", 신청 → 승인 → 마이페이지 다운로드 https://www.data.go.kr/data/15015483/fileData.do .
  - 안심구역 목록에 "정사영상 25 cm 전국" 이 공개제한으로 나오므로, 일반 다운로드판은 **보안 처리(군 시설 삭제·블러)판** 일 것 (**추정**). 국토지리정보원은 보안시설을
    "삭제, 해상도 조정, 블러링" 한다고 설명 (https://www.ngii.go.kr/lib/file/pr_01.pdf 검색 요약). → 청주 기지는 여기서도 가려져 있을 것 (**추정**).
  - 크기: 25 cm 로 10 만 km² = 1.6 조 화소 ≈ 압축 전 4.8 TB (**추정**, 계산). → 비행장 20 × 20 km 하나 ≈ 64 억 화소 ≈ JPEG 타일로 수 GB (**추정**).
  - 좋은 점: 파일을 한 번 받으면 끝 → V-World 하루 호출 예산·저장 금지(19조) 문제와 무관. 비행장 접근 경로·자주 나는 지역만 받으면 됨.
  - 넣는 법: TIFF(EPSG:5186 **추정**) → `gdalwarp` EPSG:3857 → `gdal2tiles`/직접 타일링 줌 17–19 → 로컬 프록시가 V-World 타일보다 먼저 이 타일을 줌.
    V-World 와 같은 국가 보안처리 자료라 섞어도 14조 문제는 적을 것 (**추정**). 변경금지(3 유형)라면 색 보정·덧칠은 하지 않는다.
- **V-World 줌 17–19**: 이미 프록시가 캐시에 있으면 쓰는 구조. 온라인 호출은 줌마다 4 배 → 지금 규칙(온라인 ≤16) 유지가 맞음.
- **국토위성영상 (0.5 m)**: 주문형 모자이크(최대 64 장, 생산 7 일), 마이페이지 수령 https://map.ngii.go.kr/ms/map/nlipCASImgMap.do .
  2021 년 공개 때 "온라인으로는 좌표정보가 제거된" 영상 제공 (https://www.korea.kr/briefing/pressReleaseView.do?newsId=156488534 검색 요약) → 지도 맞추기 수고 큼. 비추천.

---

## 7. 땅 덮개·나무 (숲 뿌리기, 물)

- **물 마스크 (추천 1 위)**:
  - 자료: OSM 물 폴리곤(호수·저수지·강 `natural=water`, `waterway=riverbank`) + OSM 땅 폴리곤(해안선) — Geofabrik 한국 파일 하나로 됨 (ODbL).
    (국립해양조사원 해안선 자료는 이번에 공식 페이지를 찾지 못함 — 확인 필요.)
  - 방법: quantized-mesh **Water Mask 확장** (256 × 256 바이트, 0 = 땅, 255 = 물, 중간값으로 해안 부드럽게; 클라이언트가 `extensions=watermask` 로 요청)
    https://github.com/CesiumGS/quantized-mesh . 지금 `terrain_build.py` 가 타일을 쓰므로 거기에 마스크를 붙이고 `layer.json` 의 `extensions` 에 `watermask` 추가.
    Cesium for Unreal `Cesium3DTileset` 에 `EnableWaterMask` 속성 있음 (설치본 `Cesium3DTileset.h` 903 줄). 기본 Cesium 재질이 물 부분을 어떻게 그리는지는 시험 필요 (**추정**: 반사·반짝임 정도, 파도는 별도 재질).
  - 이득: 바다·대청호·충주호가 사진의 무광 대신 하늘을 반사. 저고도 해상 비행이 크게 달라짐. 수고 작음.
- **환경부 토지피복지도 세분류**: 41 개 분류(대 7 / 중 22 / 세 41), 2024 년 영상 기준 현행화. 환경공간정보서비스 회원가입 → 자료신청(도엽 종류 "세분류토지피복지도") → 설문 후 SHP 다운로드
  (블로그 절차 https://blog.daum.net/geoscience/1537 , 지도 https://aid.mcee.go.kr/map/map.do?type=land ). WMS·통계 자료는 공공누리 1 유형
  (https://www.data.go.kr/data/3045398/openapi.do ) — SHP 자체 조건은 받을 때 확인. 해상도(최소 단위 면적)는 확인 못 함.
  옛 주소 egis.me.go.kr 은 기후에너지환경부(mcee.go.kr)로 옮겨짐.
- **ESA WorldCover 10 m (2021, v200)**: 11 분류, COG, `aws s3 sync s3://esa-worldcover/v200/2021/map ... --no-sign-request`, 계정 없음, CC BY 4.0.
  https://registry.opendata.aws/esa-worldcover-vito , https://github.com/ESA-WorldCover/esa-worldcover-datasets . 환경부 자료보다 거칠지만 가입 없이 바로 됨 — 먼저 이것으로 시험.
- **산림청 임상도 1:5,000**: 임종(천연·인공), 임상(침엽·활엽·혼효), 수종, 경급, 영급, 수관밀도. SHP, EPSG:5179. 산림청 산림공간정보 "무료신청 → 일반인 신청 → 대축척 임상도"
  (2025 판까지). https://www.data.go.kr/data/15093362/fileData.do (2021 판 등록본), https://www.forest.go.kr/newkfsweb/html/HtmlPage.do?pg=%2Ffgis%2FUI_KFS_5002_020100.html&mn=KFS_02_04_03_04_01&orgId=fgis .
  "항공사진 촬영시기와 제작시점의 차이로 일부 속성이 현장과 다를 수 있음". 라이선스 미확인.
- **Meta/WRI 나무 높이 (CHM)**: 1 m 전 세계 (v1, 2024), CHMv2, AWS S3 계정 없이, CC BY 4.0 https://registry.opendata.aws/dataforgood-fb-forestsv2 .
- **넣는 법**: 토지피복(어디가 숲/논/도시) + 임상도(침엽/활엽) + 나무 높이 → 래스터 마스크 → Unreal PCG 또는 Foliage 로 비행기 주변 수 km 만 나무 메시 뿌리기 (Cesium 지형 위 선 추적으로 높이).
  사진이 이미 숲을 보여 주므로 이득은 **고도 300 m 이하·헬기 시점** 에서만 큼. 수고 큼(성능·LOD). 4 순위 밖.

---

## 8. 그 밖

- **도로·하천 선 (OSM, 수치지도)**: 사진에 이미 보이므로 낮 비행 이득은 작음. **야간**에 도로 가로등·도시 불빛을 만들 때 씀 (OSM `highway=*` + 건물 밀도).
- **NASA Black Marble 야간 불빛 (VNP46A4, 연간 500 m)**: NASA LAADS, **Earthdata Login 가입·토큰 필요** (https://worldbank.github.io/blackmarblepy/_sources/README.md ,
  https://catalog.data.gov/dataset/viirs-npp-lunar-brdf-adjusted-nighttime-lights-yearly-l3-global-15-arc-second-linear-lat-l ). 500 m 라 고공 야간의 "도시 빛 덩어리" 용. 저공은 OSM 도로·건물로 만든 불빛이 낫다 (**추정**).
- **정밀도로지도**: 고속국도·일반국도 차선·표지 3D, "민·관 기관, 기업 무상 제공" https://map.ngii.go.kr/ms/pblictn/preciseRoadMap.do — 비행 시뮬레이터에는 과함.
- **국토통계지도 건물 격자 (100 m 등)**: 건물 높이·층수 격자 통계, SHP, 공공누리 1 유형 https://www.data.go.kr/data/15062298/fileData.do — 건물 윤곽이 없을 때 "먼 도시 밀도" 표현용 대안.

---

## 9. 약관·법 정리

| 위험 | 내용 | 대응 |
|---|---|---|
| 국외 반출 | 공간정보관리법: 국가안보·국익 우려 측량성과는 원칙적으로 국외 반출 금지, 국토부·국정원 등 협의체 결정 때만 예외 (2014 개정 설명; 2026-02 구글 1:5,000 지도 조건부 허가 사례 — https://www.mofa.go.kr/www/brd/m_24815/view.do?seq=147 검색 요약). 정확한 조문은 law.go.kr 에서 확인 | 정부 측량 자료·그 파생 타일을 GitHub(해외)·클라우드에 올리지 않음. 저장소엔 스크립트와 출처 문서만 |
| 공개제한 자료 | 5 m DEM, 3D 건물, 건물높이DB, V-World 3D | 쓰지 않음 |
| 변경금지 (공공누리 3 유형) | 항공사진(국토영상정보) | 형식 변환·자르기만, 색 덧칠·합성 안 함. 받을 때 실제 유형 확인 |
| 출처 표시 | 공공누리 1·3 유형, CC BY 4.0, ODbL, Copernicus | 화면 오른쪽 아래 출처 판 + `unreal/GyroSim/ATTRIBUTION.md` 에 추가 (예: "건물: 국토교통부 GIS건물통합정보", "영상: 국토지리정보원", "© OpenStreetMap contributors", "ESA WorldCover") |
| 군사시설 | V-World 약관 14조: 군사시설이 포함된 지도와 함께 쓰면 해지 사유 | 가려진 기지를 다른 사진으로 되살리지 않음. 기지 안 건물·시설은 시뮬레이터 자체 모델(활주로 등 공표 AIP 값)만 |
| 계정 | 모두 사용자 본인 가입. 에이전트는 가입하지 않음 | 아래 "사용자 할 일" |

## 10. 사용자 할 일 (가입)

| 사이트 | 필요한 자료 | 비고 |
|---|---|---|
| V-World (이미 있음) | GIS건물통합정보 SHP | 다운로드 메뉴 로그인 (**추정**) |
| 공공데이터포털 data.go.kr | 장애물 CSV 2 개, (대안) 건물통합정보 | 파일 다운로드에 로그인 (**추정**) |
| 국토정보플랫폼 map.ngii.go.kr | 정사영상, 1:5,000 수치지도 | 대용량 전송 프로그램 설치 필요 (설치 창이 뜸 — 사용자가 직접) |
| 환경공간정보서비스 (기후에너지환경부) | 토지피복 세분류 | 자료신청·설문 후 다운로드 |
| 산림청 산림공간정보 | 임상도 1:5,000 | 일반인 무료신청 |
| NASA Earthdata | 야간 불빛 (선택) | 토큰 |
| 가입 없음 | OSM(Geofabrik), ESA WorldCover, Meta 나무 높이, AIP | 바로 가능 |

## 11. 다음 단계 제안 (순서)

1. 물 마스크: Geofabrik 한국 PBF → 물/땅 폴리곤 → `terrain_build.py` 에 watermask → 언리얼 `EnableWaterMask` 켜고 대청호·서해에서 보기 (가입 없음).
2. RKTU AIP 값으로 활주로 끝 좌표·표고·폭 점검, 접근등·PAPI 추가.
3. (사용자 가입 후) GIS건물통합정보 충북 한 파일로 시험: 높이 빈 비율 세기 → 청주 시내 3D Tiles → OSM 건물과 나란히 비교 사진.
4. 장애물 CSV 두 개 → 장애등.
5. 정사영상: 청주 기지 주변 20 km 만 받아서 V-World z16 과 비교, 기지가 가려졌는지 확인.

## 출처 (모음)

- V-World 공간정보 다운로드: https://www.vworld.kr/dtmk/dtmk_ntads_s001.do
- GIS건물통합정보: https://www.data.go.kr/data/15083092/fileData.do , https://www.data.go.kr/biz/dcat/metadata/15052097.do , https://gnuhacker.com/2022/04/04/01_GIS%EA%B1%B4%EB%AC%BC%ED%86%B5%ED%95%A9%EC%A0%95%EB%B3%B4/ , https://www.vw-lab.com/51 , https://winniestory.com/349
- 국토통계지도 건물: https://www.data.go.kr/data/15062298/fileData.do
- NGII DEM: https://www.data.go.kr/data/15059920/fileData.do ; 정사영상: https://www.data.go.kr/data/15059919/fileData.do ; 항공사진: https://www.data.go.kr/data/15015483/fileData.do
- 국토정보플랫폼: https://map.ngii.go.kr/ , 건물높이공간정보 https://map.ngii.go.kr/bl/map/buldEncView.do , 국토위성영상 https://map.ngii.go.kr/ms/map/nlipCASImgMap.do , 정밀도로지도 https://map.ngii.go.kr/ms/pblictn/preciseRoadMap.do
- 공간정보 안심구역: https://www.datafreezone.or.kr/center_01.do
- 3D 건물모형 보도: https://www.asiae.co.kr/en/article/2021062911045711440 ; V-World 3D API 중단 논문: https://koreascience.kr/article/JAKO202404861569434.pdf
- 국토위성 보도자료: https://www.korea.kr/briefing/pressReleaseView.do?newsId=156488534 ; NGII 보안처리 설명: https://www.ngii.go.kr/lib/file/pr_01.pdf
- eAIP Korea: https://aim.koca.go.kr/eaipPub/Package/history-en-GB.html , RKTU AD 2: https://aim.koca.go.kr/eaipPub/Package/2026-10-28-AIRAC/html/eAIP/KR-AD-2.RKTU-en-GB.html , AMDB: https://aim.koca.go.kr/aim/amdb.do
- 장애물: https://www.data.go.kr/data/15145041/fileData.do , 장애표시등: https://www.data.go.kr/data/15150345/fileData.do
- 토지피복: https://aid.mcee.go.kr/map/map.do?type=land , https://www.data.go.kr/data/3045398/openapi.do , https://blog.daum.net/geoscience/1537
- 임상도: https://www.data.go.kr/data/15093362/fileData.do , 산림청 임상도 소개(위 URL)
- ESA WorldCover: https://registry.opendata.aws/esa-worldcover-vito , https://github.com/ESA-WorldCover/esa-worldcover-datasets
- Meta 나무 높이: https://registry.opendata.aws/dataforgood-fb-forestsv2
- OSM 한국: https://download.geofabrik.de/asia/south-korea.html
- Black Marble: https://worldbank.github.io/blackmarblepy/_sources/README.md
- quantized-mesh Water Mask: https://github.com/CesiumGS/quantized-mesh ; pg2b3dm: https://github.com/Geodan/pg2b3dm
- 국외 반출 사례: https://www.mofa.go.kr/www/brd/m_24815/view.do?seq=147
