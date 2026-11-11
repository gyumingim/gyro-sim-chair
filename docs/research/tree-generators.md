# 나무 생성기 · 대규모 숲 표현 조사 (2026-11-11)

목적: 지금 3D 타일 나무(150–400 삼각형, 먼 LOD 16–32, 정점색만, 텍스처 없음)가 공중(50–1500 m)에서 "동그라미"로 보이는 문제를
싸게 고칠 방법 찾기. 부산 숲 = 소나무(Pinus densiflora: 납작한 우산형·덩어리진 수관·위쪽 줄기 주황) + 참나무류.
이미 실패: Megascans Nanite(감량 시 잎 소실, +3 ms), 손으로 만든 납작 덩어리 소나무(품질 낮음), 팔면체 임포스터(평평하고 밝은 스프라이트).

이 노트는 조사만 했다. 찾은 저장소의 코드는 내려받거나 돌리지 않았다. "확인 안 함" = 출처에서 직접 확인하지 못한 내용.
삼각형 수·비용·모양은 따로 적지 않았으면 모두 **추정**이다.

## 0. 결론 먼저

1. **1순위: 우리 Python 생성기(veg_shape.py)에 "잎 카드 덩어리(leaf-card cluster)" 잎 모드 추가** + 알파 마스크 텍스처 아틀라스
   + 덩어리별 구형 법선에 위쪽 치우침과 잡음 섞기. 지금 나무가 동그랗게 보이는 주원인은 잎이 **닫힌 매끈한 껍질 + 정점색**이라
   가장자리가 매끈하고 구멍(하늘·땅 비침)이 없다는 점이다. 이건 삼각형을 늘려도 안 고쳐지고, 알파로 깎은 카드 가장자리가 있어야 고쳐진다.
   카드는 삼각형이 적게 든다(소나무 약 200–500, 참나무 약 300–700, 추정). 대신 비용은 **오버드로·마스크 머티리얼**로 옮겨 간다.
2. **2순위: 먼 LOD를 "빌보드 클라우드"로**(Décoret 2003 / Lacewell 2006 / Simplygon foliage 모드 방식). 나무마다 3D로 놓인 6–12장의
   판(12–24 삼각형)이라 실루엣·부피·조명 방향이 남는다. 팔면체 임포스터는 화면을 향한 판 1장이라 "평평하고 밝다"는 판정이 나왔는데,
   빌보드 클라우드는 그 약점이 덜하다(추정). 1순위의 카드 나무에서 판을 뽑아 Python으로 오프라인 생성할 수 있다.
3. **3순위(장기·위험): 가까운 고리만 UE Nanite Foliage(5.7부터 실험 기능, Assemblies + Voxels)로 옮기기.** 먼 거리는 픽셀 크기의
   복셀로 바꿔서 실루엣이 남는다고 Epic 문서에 나온다. 하지만 Cesium 타일 밖의 별도 배치가 필요하고, 실험 기능이고, Nanite 잎은 이미
   +3 ms가 나왔던 기록이 있다. 1·2순위가 막힐 때만 쓴다.

외부 생성기를 그대로 쓰는 안은 순위가 낮다. Python CLI에서 glTF를 바로 뽑으면서 상용 사용이 안전하고 소나무 우산형이 되는 도구는 못 찾았다.
가지 골격만 참고할 가치가 있는 후보는 modular_tree(코어 MIT, Pine 프리셋), ez-tree(MIT, JS, GLB).

**첫 실험(제안)**: `veg_shape.py`에 카드 잎 모드를 넣어 소나무(P. densiflora) 10종을 만든다. 각 300–600 삼각형, 4–7개 납작 덩어리, 덩어리마다
알파 카드 3–5장(수평 쪽으로 기울임)을 쓰고, 512² 솔잎 뭉치 아틀라스는 Python으로 직접 렌더한다(제3자 텍스처를 쓰지 않으므로 라이선스 문제 없음).
먼저 오프라인 미리보기(100/300/800 m, 위·비스듬)로 지금 나무와 나란히 비교한다. 그보다 앞서 **관문 시험**:
Cesium for Unreal이 인스턴스 타일(EXT_mesh_gpu_instancing)에서 glTF `alphaMode: MASK` 텍스처를 제대로 그리는지 작은 타일 1개로 확인한다(확인 안 함).
자세한 절차는 6장.

## 1. 기존 비행 시뮬레이터 · 게임은 어떻게 하나

| 대상 | 방식 | 근거 | 확인 정도 |
|---|---|---|---|
| X-Plane 12 | 나무 = 3D 메시(가까이) + 카메라를 보는 빌보드 1장(멀리). 기본 3D LOD 0–500 m. 큰 나무 **1000–2000 삼각형**, 아주 큰 노목 3000–4000. 위를 보는 삼각형은 0–500 m LOD, 아래를 보는 삼각형(가지 밑면)은 0–100 m LOD로 나누기를 "강력 권장". 잎 전용 반투명 셰이더(노멀맵 B 채널 = 투과도). 한 숲 파일의 종은 한 텍스처 시트를 공유. | https://developer.x-plane.com/article/building-custom-3-d-trees/ , https://developer.x-plane.com/article/forest-for-file-format-specification | 공식 문서를 직접 읽음 |
| MSFS 2020/2024 | 공식 기술 발표를 못 찾았다. 사전 발표에서 ML로 종을 식별해 런타임에 심는다고 했다. 포럼에서는 가까이 갈수록 고해상 메시로 페이드되고, 종 정의는 XML(TreeSpecies 등)이라고 한다. | https://news.flightsim.to/jorg-neumann-reveals-details-on-microsoft-flight-simulator , https://orbxdirect.com/product/burningbluedesign-global-vegetation , https://forums.flightsimulator.com/t/lod-problems-trees-fix-revisited/296923/92 | 렌더 기법은 확인 안 함 |
| DCS World | 포럼 사용자 말로는 오래전에 라이선스한 SpeedTree를 쓴다고 한다. 2024-01 뉴스레터에 "Vegetation Development Progress" 항목이 있지만 내용은 못 봄. | https://forum.dcs.world/topic/371743-we-need-better-trees-now-that-msfs2024-has-set-the-bar , https://www.amvi.it/news5476-dcs-world-newsletter-19012024.html | 확인 안 함 |
| Horizon Zero Dawn (GDC 2018, Gilbert Sanders) | 식생 전부 GPU 절차 배치(GDC 2017 slides), 먼 그림자는 높이장 기반 캐스케이드(자동 요약 출처). | https://www.guerrilla-games.com/media/News/Files/GDC2017_VanMuijden_GPUBasedProceduralPlacementInHorizonZeroDawn.pdf , https://gamedeveloper.com/art/video-how-guerrilla-crafted-the-lush-vegetation-of-i-horizon-zero-dawn-i- | 나무 LOD 세부 확인 안 함 |
| UE 5.7+ Nanite Foliage | Assemblies(가지 부품 인스턴스, 6.5만 개까지), Voxels(먼 거리 픽셀 크기 복셀, 빌보드·LOD 없이 부피 유지), Skinning(뼈 기반 바람). **실험 기능**. 데모 나무는 4100만 삼각형, 부품 12종, 디스크 3.5 GB → 29 MB. 50만 인스턴스 장면이 가능하다고 함. Static Mesh 설정의 Shape Preservation > Voxelize로 켠다. PCG·Foliage 도구와의 관계는 문서에 없음. | https://dev.epicgames.com/documentation/unreal-engine/nanite-foliage?lang=en-US , https://www.unrealengine.com/news/unreal-engine-5-7-is-now-available | 공식 문서를 직접 읽음 |

교훈(X-Plane): "공중에서 보이는 숲"에 쓰는 실용 예산은 가까운 나무 1–2k 삼각형에 먼 거리는 판 1장이다. 우리는 1960만 그루를 타일로 깔기
때문에 가까운 LOD를 300–700 삼각형에 맞추고, 대신 **실루엣을 알파로** 만드는 것이 맞는 방향이다(추정).

## 2. 기법별 정리

| 기법 | 핵심 | 소나무/참나무 1그루 삼각형 (추정) | 공중에서의 장점 | 비용·위험 | 출처 |
|---|---|---|---|---|---|
| 잎 카드 덩어리 (leaf-card clusters) | 잎·솔잎 뭉치 사진(알파)을 붙인 사각형 몇 장을 가지 끝에 교차 배치. SpeedTree·X-Plane·대부분 게임의 표준 | 소나무 200–500 (줄기·가지 80–150 + 카드 20–60장×2), 참나무 300–700 | 들쭉날쭉한 가장자리, 구멍, 덩어리 사이 그늘이 생긴다. "동그라미" 문제를 직접 겨냥 | 알파 마스크 → 오버드로, UE에서 masked는 early-Z 이득 감소. 아틀라스 텍스처가 타일에 들어가야 함 | https://developer.x-plane.com/article/building-custom-3-d-trees/ , https://developer.nvidia.com/gpugems/GPUGems3/gpugems3_ch04.html |
| 구형 법선 + 잡음 (foliage normals) | 카드 법선을 감싸는 구(또는 원뿔·반구) 법선으로 옮겨 덩어리가 입체로 음영. 원래 법선과 섞거나, 아래가 너무 어두우면 구를 원뿔로 바꾼다 | 0 (법선만 바꿈) | 카드가 판처럼 안 보이고 덩어리로 보임 | 나무 전체를 구 하나로 하면 지금처럼 "공"이 된다 → **덩어리별** 구 + 위쪽 치우침 + 카드별 잡음이 핵심. 소나무는 쉽고 자작나무는 어렵다는 경험담 | https://forums.unrealengine.com/t/spherical-normals-for-trees-blender/98732 , https://forums.unrealengine.com/t/leaves-cards-too-flat/74192 , https://polycount.com/discussion/comment/1920395 |
| 빌보드 클라우드 | 원래 나무를 잘 근사하는 3D 평면 몇 장을 고르고 각 평면에 잎을 투영해 텍스처로 굽는다. 잎 모드는 서로 교차하는 판으로 부피 유지 | 6–12장 = 12–24 | 실루엣·부피 유지, 판마다 법선이 있어서 빛 방향이 남는다. 먼 LOD 후보 | 텍스처 공간(아틀라스) 증가, 판 선택 알고리즘 구현 필요(간단판: 수평 판 2–3장 + 교차 수직 판 3–4장) | Décoret et al. 2003 TOG https://history.siggraph.org/?p=99877 (INRIA RR-4485), Lacewell et al. 2006 JGT https://dblp.uni-trier.de/rec/journals/jgtools/LacewellEST06.html , Behrendt et al. EG 2005, Simplygon https://simplygon.com/posts/b9c254b6-9ee1-47d3-b6aa-9418743e1f2a |
| 팔면체 임포스터 | 여러 방향에서 구운 그림 중 하나를 판 1장에 표시 | 2 | 매우 쌈 | **이미 시도해 실패**(평평·밝음). 단, 9bdb48d 커밋에서 구형 법선 등을 고친 상태 | (기존 docs/trees-impostor-busan.md) |
| 셸 / 부피 텍스처 | 지형 위에 숲을 3D 텍스처 슬라이스 더미(프리즘)로 깔기. 슬라이스는 지형과 평행, 실루엣 근처는 화면과 평행 | 나무 단위 아님 | 아주 먼 숲을 연속된 캐노피로 표현 | 3D 텍스처·슬라이스 렌더 = Cesium 타일 파이프라인 밖, 큰 작업 | Decaudin & Neyret EGSR 2004 https://evasion.inrialpes.fr/Publications/2004/DN04/?lg=en , https://phildec.users.sourceforge.net/Research/Forest.php |
| z-field + 셰이더 맵 | 가까운 나무는 라이트필드·높이장 개체, 먼 숲은 지형에 입힌 시점·광원 의존 셰이더로 서브픽셀 효과(빽빽한 숲의 어두움, 역광 핫스팟)를 누적 | 가까운 나무 소수 | 1500 m 쪽 숲의 색·밝기를 맞추는 데 유용(지금의 "숲이 너무 밝음" 류 문제) | 연구 코드, UE 이식 큰 작업. 아이디어(먼 숲은 지형 셰이더로 어둡게·거칠게)만 차용 가능 | Bruneton & Neyret CGF 2012 https://diglib.eg.org/handle/10.1111/v31i2pp373-382 |
| 실루엣 유지 메시 LOD | 일반 감량은 흩어진 잎에서 무너진다(우리 Megascans 실패 원인과 같음). 잎은 감량하지 말고 카드 수를 줄이거나 카드를 키움 | — | — | — | Simplygon vegetation https://www.simplygon.com/features/vegetationoptimization , Décoret 2003 |
| Nanite Voxels | 위 1장 참고 | 원본 고해상 | 실루엣 유지 | 실험 기능, Cesium 밖 | 위 1장 |

## 3. 생성기 후보

라이선스: MIT/BSD/Apache/CC0 = 공개 저장소에 코드 포함 가능. GPL = 별도 도구로만 실행하고 결과 메시만 사용(우리 저장소에 코드 포함 금지).
CeCILL-C = LGPL 비슷함(수정한 그 라이브러리만 공개 의무, 링크는 자유). CeCILL(무접미사) = GPL 호환 카피레프트.

| 후보 | URL | 라이선스 | 유지보수 | 출력 | 방식 | 소나무 우산형? | 우리 파이프라인 적합 | 노력 |
|---|---|---|---|---|---|---|---|---|
| **modular_tree** (MTree의 유지보수 포크) | https://github.com/GoodPie/modular_tree , https://extensions.blender.org/add-ons/modular-tree/ | 애드온 GPLv3, **코어 라이브러리 MIT** | 활발(v5.6.0, 2026-10-20) | Blender 메시, UE용 Pivot Painter 2 내보내기 | 노드 기반 가지 + 절차 잎(Superformula 외곽선, 공간 식민화 잎맥). 프리셋 Oak/Pine/Willow…, 수관 Conical/Hemispherical | Pine 프리셋은 원뿔형(가문비 쪽). 반구형 수관 + 파라미터로 우산형 근접 가능(확인 안 함) | Blender 안에서 돌아감. `blender -b --python`으로 일괄 실행되는지 확인 안 함. 잎이 실제 메시라 우리 예산(수백 삼각형)을 넘음 → 골격만 참고하거나, MIT 코어의 가지 알고리즘을 참고 | 중 |
| **ez-tree** | https://github.com/dgreenheck/ez-tree | MIT | 활동 중(커밋 134, 최근 날짜 확인 안 함) | 웹앱에서 GLB/PNG 내보내기. 라이브러리는 three.js BufferGeometry | 재귀 가지 + 잎 = 단면/교차 2면 사각형(billboard 옵션) — **카드 방식 그대로** | 프리셋은 Ash 등 활엽수. 소나무 프리셋 없음(확인한 범위) | JS라 Node 일괄 실행 + GLTFExporter가 필요(헤드리스 동작 확인 안 함). 매개변수 설계와 카드 배치 방식 참고용으로 좋음 | 중 |
| tree-gen (friggog) | https://github.com/friggog/tree-gen | GPL-3.0 (생성 모델은 에셋 직판 외 자유 사용) | 확인 안 함 | Blender 메시 | Weber-Penn 계열 Blender 애드온(학부 논문) | 확인 안 함 | GPL·Blender 의존. 별도 도구로만 | 중 |
| Sapling Tree Gen | https://docs.blender.org/manual/en/4.1/addons/add_curve/sapling.html | GPL-2.0+ | Blender 4.2부터 번들 애드온이 아니라 extension으로 바뀜(확인 안 함) | Blender 커브/메시 | Weber-Penn | 소나무 예시 있음(포럼) | GPL, Blender 필요. 별도 도구로만 | 중 |
| openalea.weberpenn | https://macs4plants.cirad.fr/software/weberpenn , https://anaconda.org/channels/openalea3/packages/openalea.weberpenn/overview | CeCILL-C (GitHub 메타데이터에는 라이선스 없음 → LICENSE 파일 확인 필요) | 확인 안 함 | OpenAlea PlantGL 장면(OBJ 내보내기 확인 안 함) | Weber & Penn 1995 순수 Python | 매개변수로 가능(확인 안 함) | Python이라 잘 맞지만 conda·PlantGL 의존. 알고리즘은 논문만 보고 직접 짜도 됨 | 중 |
| L-Py (OpenAlea) | https://github.com/openalea/lpy | CeCILL (GPL 호환) | CI 배지 있음, 커밋 936(최근 날짜 확인 안 함) | PlantGL 장면(메시 내보내기 형식은 페이지에 없음) | L-system + Python | 가능하지만 직접 문법을 짜야 함 | 연구용으로 무거움. 우리 목적에 과함 | 상 |
| proctree.js | https://github.com/supereggbert/proctree.js | 라이선스 표시 못 찾음 → 사용 불가로 간주 | 커밋 9개 | 배열(줄기 + 잔가지 메시) | 아주 단순한 절차 나무 | 아니오 | 참고만 | — |
| SpeedTree (상용) | https://store.speedtree.com/ | Indie 월 $19(연매출 10만 달러 미만, Unity 지원 문서 기준) | 상용·유지됨 | FBX/OBJ 등, 카드 + 빌보드 자동 | 업계 표준(카드, 실루엣 감량, 빌보드) | 라이브러리에 소나무류 있음(P. densiflora는 확인 안 함) | GUI 도구라 Python 일괄 생성과 안 맞음. 결과 메시는 라이선스상 공개 저장소에 넣지 않는 편이 안전 | 하(돈) |
| Tree-D Fusion (ECCV 2024) | https://arxiv.org/abs/2407.10330v1 | 데이터·코드 라이선스 확인 안 함 | — | 공간 식민화로 만든 3D 나무 60만 개(북미 Street View 기반) | 단일 이미지 → 확산 모델 → 외피 → 종 조건 공간 식민화 | 북미 종 위주, 한국 소나무 없음(추정) | "이미지 → 외피 → 공간 식민화" 흐름은 우리도 흉내 낼 수 있음(소나무 사진 외곽 → 외피) | 상 |
| TreeON (CGF 2026) | https://angelikigram.github.io/treeON , https://github.com/AngelikiGram/TreeON | 라이선스 표시 없음 | 2026 공개 | **점구름** | 정사영상 + DSM 한 장 → 신경망으로 나무 점구름 | — | 흥미로움: 우리에게 V-World 정사영상과 DSM이 있다. 그러나 점구름 → 메시 → 카드 변환이 더 필요하고 라이선스가 불명 | 상 |
| Botanical trees from single images (Li, Pirk, Benes et al., SIGGRAPH Asia 2021) | https://par.nsf.gov/biblio/10378392 | 코드 공개 확인 안 함 | — | 절차 나무 | 사진 → 종 분류 + 반경 외피 → 생장 시뮬 | — | 참고 논문 | — |
| Space colonization Blender 애드온 | https://extensions.blender.org/add-ons/space-colonization-tree-generator/ | 확인 안 함 | 확인 안 함 | Blender 골격 | Runions et al. 2007 | — | 알고리즘 참고(직접 numpy로 짜는 게 빠름) | — |

공간 식민화 원 논문: Runions, Lane, Prusinkiewicz, "Modeling Trees with a Space Colonization Algorithm", Eurographics NPH 2007 (URL 확인 안 함 — 위 Blender 애드온 페이지가 인용).
Weber & Penn, "Creation and Rendering of Realistic Trees", SIGGRAPH 1995 (위 openalea 문서가 인용).

정리: 우리 조건(Python 오프라인, 종마다 수십 변종, glTF 인스턴스, 공개 저장소)에 **그대로 맞는 기성 생성기는 없다**.
가지 골격(공간 식민화 또는 Weber-Penn 축약판)은 numpy로 200–400줄이면 직접 짤 수 있고(추정), 이미 veg_shape.py에 줄기·가지 코드가 있다.
진짜 빠진 것은 생성기가 아니라 **잎 표현(알파 카드 + 법선)** 이다.

## 4. 왜 지금 나무가 "동그라미"인가 (코드를 읽고 내린 판단)

- `sim/veg_v2.py`·`veg_shape.py`: 잎 덩어리 = 닫힌 타원체 메시, **텍스처 없음**(정점색 + 틴트 + AO). 가장자리는 기하 그 자체라 300 m 밖에서는 매끈한 원이 된다.
- 덩어리 사이 틈은 veg_shape에서 늘렸지만 덩어리 안은 꽉 차 있어서 하늘·땅이 안 비친다. 실제 소나무 수관은 위에서 보면 솔잎 뭉치 사이로 그림자 구멍이 많다.
- 그러니 삼각형을 2–3배 늘려도 껍질이 울퉁불퉁해질 뿐이다. **알파로 깎인 가장자리와 안쪽 구멍**이 있어야 덜 동그랗게 보인다(추정, 업계 표준이 근거).

## 5. 추천 (순위·이유·예상)

| 순위 | 안 | 이유 | 예상 모양 (추정) | 예상 비용 (추정) |
|---|---|---|---|---|
| 1 | veg_shape.py에 카드 잎 모드 추가: 덩어리마다 알파 카드 3–6장(소나무는 수평에 가깝게, 참나무는 무작위 교차), 덩어리별 구형 법선 0.4–0.6 + 위쪽 치우침 + 카드별 잡음, 솔잎/잎 뭉치 아틀라스는 Python으로 직접 렌더(1 장, 512²–1024², 종 4–6칸) | 원인(매끈한 닫힌 껍질)을 직접 고침. 기존 파이프라인(Python → glTF 인스턴스 → 3D Tiles)을 그대로 쓰고 생성기 라이선스 문제가 없음 | 50–500 m에서 들쭉날쭉한 수관 가장자리, 덩어리 사이 그늘·구멍, 소나무 층 구조. 1000 m 이상에서는 지금과 큰 차이가 없음 | 삼각형은 지금과 비슷하거나 1.5배. GPU 비용은 masked 오버드로가 지배: 지금 대비 +0.5–2 ms(근거: 임포스터 시험 p99 +1.8 ms, 기존 커밋 9bdb48d). 반드시 측정 |
| 2 | 먼 LOD = 빌보드 클라우드(1순위 카드 나무에서 오프라인으로 굽기: 수평 판 2–3장 + 수직 교차 판 3–4장) | 팔면체 임포스터보다 3D 부피·조명이 남아 "평평·밝음" 문제가 덜함. 16–32 삼각형 먼 LOD 예산 안에 들어감 | 300–1500 m에서 덩어리 모양과 그늘이 남음 | 삼각형은 같은 수준, 텍스처 아틀라스가 늘어남. 오버드로는 1순위보다 적음 |
| 3 | 가까운 고리(< 300 m)만 UE Nanite Foliage(Assemblies + Voxels)로 별도 배치 | 품질 상한이 가장 높음, 먼 거리 복셀로 실루엣 유지 | 최고(추정) | 실험 기능, Cesium 밖의 별도 배치 시스템 필요, 이전 Nanite 시도에서 +3 ms. 1·2가 막힐 때만 |

참고로 함께 할 만한 작은 것: 먼 숲 색은 Bruneton–Neyret 식으로 거리에 따라 더 어둡고 거칠게(밝은 스프라이트 판정 대응). X-Plane처럼 아래를 보는
삼각형(줄기 밑면·카드 밑면)은 가까운 LOD에만 넣는다.

## 6. 첫 실험 (구체적)

0. **관문 (30분짜리, 먼저):** glTF `alphaMode: MASK` + `alphaCutoff` + baseColor 텍스처 + EXT_mesh_gpu_instancing을 쓴 작은 타일 1개를 만들어
   Cesium for Unreal(현재 버전)에서 투명 구멍이 제대로 나오는지, 인스턴스마다 머티리얼이 하나로 묶이는지 본다. Cesium의 인스턴싱 지원은
   v2.6.0부터라고 나오지만(https://community.cesium.com/t/from-i3dm-to-ext-mesh-gpu-instancing/19731) 인스턴스와 알파 마스크를 함께 쓰는 경우는 확인 안 함.
   안 되면 → 머티리얼 오버라이드(Cesium의 사용자 머티리얼)로 마스크를 거는 길을 확인한다.
1. **아틀라스:** Python(numpy 래스터라이저 또는 기존 미리보기 렌더러)으로 솔잎 뭉치(소나무), 활엽 잎 뭉치(참나무) 텍스처를 그린다.
   RGB + 알파 + (선택) 투과 마스크, 512², 밉맵에서 알파가 사라지지 않게 밉별 커버리지 보존(alpha-to-coverage 보정).
2. **소나무 10종:** 기울고 휜 줄기(위쪽 주황 정점색 유지), 가지 3–5개, 끝마다 납작한 덩어리 4–7개, 덩어리 = 수평에서 ±25° 카드 3–5장 + 위 카드 1장.
   목표 300–600 삼각형(가까이), 먼 LOD 빌보드 클라우드 6–8장(12–16 삼각형). 참나무 5종도 같이 만든다(덩어리 5–7개, 카드 4–6장).
3. **오프라인 비교:** `veg_shape_preview.py` 방식으로 지금 나무 / 카드 나무를 100·300·800 m, 위에서·30° 비스듬히·역광으로 나란히 렌더한다.
   소나무 사진 몇 장과 같이 놓고 사용자에게 보여 준다(UE 들어가기 전에 판정).
4. **UE 측정:** 통과하면 타일 한 구역(같은 비행 경로, 같은 설정)에서 GPU ms 평균·p99를 기존 나무와 비교한다. 기준선 먼저, 같은 경로, 3회 반복.
   합격선(제안): p99 +1.0 ms 이하, 사용자 육안 판정 "덜 동그랗다".

## 7. 남은 불확실성

- Cesium for Unreal + 인스턴싱 + 알파 마스크 조합 (관문 시험으로 확인).
- 1960만 그루 중 한 화면에 실제로 보이는 수와 오버드로 → 비용은 측정 전까지 추정.
- MSFS·DCS의 실제 기법은 공식 자료를 못 찾음.
- modular_tree·ez-tree의 헤드리스 일괄 실행 여부, openalea.weberpenn의 LICENSE 파일, Tree-D Fusion·TreeON 라이선스: 확인 안 함.
