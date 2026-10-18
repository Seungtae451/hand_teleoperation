# DG-5F 오른손 모델과 좌표계

공식 모델은 `tesollodelto/tesollo_model`의 commit
`f648627be40f8df2e3df906ccf3c5d62103f3275`, `dg5f/dg5f_right.urdf`를 사용한다.
원본 SHA-256은 `86fc72a59d42bd2b866e340feb03dc864315350be3722a28626b7bd4a5a385ca`다.
초기 `tesollo_model-main/` 사본과 같은 URDF다. 초기 사본은 현재 외부 보관했고 pinned 공식 checkout을 사용한다. 라이선스는 BSD-3-Clause다.

## 관절과 프레임

- 로봇 root/base: `rl_dg_mount`, 고정 base. free joint 없음.
- palm: `rl_dg_palm`. world에서 위치 `(0,0,0.0738)` m, 영 자세의 축 방향은 world와 동일.
- 실제 URDF: 28 links, 27 joints = revolute 20 + fixed 7. mimic/coupled joint 없음.
- canonical order: thumb, index, middle, ring, pinky 순서로 각 손가락 joint 1~4.
- fingertip order: 위 손가락 순서의 `rl_dg_1_tip` ~ `rl_dg_5_tip` 링크 원점.
- m/rad/s를 사용한다. 좌표계는 URDF/MuJoCo의 오른손 좌표계다.
  사람 손과의 정렬은 각 adapter가 별도로 수행한다. 현재 정의는 [METHODS.md](METHODS.md)를 따른다.

| canonical index | joint | local axis | lower rad | upper rad |
|---|---|---|---:|---:|
| 0 | rj_dg_1_1 | X | -0.383972 | 1.343904 |
| 1 | rj_dg_1_2 | Z | -2.705260 | 0 |
| 2 | rj_dg_1_3 | X | -1.570796 | 1.570796 |
| 3 | rj_dg_1_4 | X | -1.570796 | 1.570796 |
| 4 | rj_dg_2_1 | X | -0.541052 | 0.349066 |
| 5 | rj_dg_2_2 | Y | 0 | 2.007129 |
| 6 | rj_dg_2_3 | Y | -1.570796 | 1.570796 |
| 7 | rj_dg_2_4 | Y | -1.570796 | 1.570796 |
| 8 | rj_dg_3_1 | X | -0.436332 | 0.436332 |
| 9 | rj_dg_3_2 | Y | 0 | 2.007129 |
| 10 | rj_dg_3_3 | Y | -1.570796 | 1.570796 |
| 11 | rj_dg_3_4 | Y | -1.570796 | 1.570796 |
| 12 | rj_dg_4_1 | X | -0.261799 | 0.558505 |
| 13 | rj_dg_4_2 | Y | 0 | 1.919862 |
| 14 | rj_dg_4_3 | Y | -1.570796 | 1.570796 |
| 15 | rj_dg_4_4 | Y | -1.570796 | 1.570796 |
| 16 | rj_dg_5_1 | Z | 0 | 1.047198 |
| 17 | rj_dg_5_2 | X | -0.261799 | 1.570796 |
| 18 | rj_dg_5_3 | Y | -1.570796 | 1.570796 |
| 19 | rj_dg_5_4 | Y | -1.570796 | 1.570796 |

표는 읽기 편하도록 반올림했다. 코드는 URDF 전체 정밀도 제한을 읽고 MJCF에도 그대로 넣는다.
20개 joint의 URDF effort는 7.5 N·m, velocity는 π rad/s다. effort는 actuator force limit으로
반영한다. velocity는 현재 목표 생성기의 hard limit으로 적용하지 않는다.

영 자세의 world fingertip 위치(m):

| finger | X | Y | Z |
|---|---:|---:|---:|
| thumb | 0.02575 | 0.12510 | 0.08660 |
| index | 0.01055 | 0.02700 | 0.26950 |
| middle | 0.01055 | 0.00250 | 0.27350 |
| ring | 0.01055 | -0.02200 | 0.26550 |
| pinky | 0.01030 | -0.04750 | 0.23620 |

tip은 최종 구동 joint/마지막 링크 원점과 다르다. 예를 들어 index tip은 joint 4에서
local Z로 0.0255 m 떨어진 fixed link다. 엄지는 tip frame에 Z축 π 회전도 있다.
**패드 표면 중심·접촉점은 URDF가 명시한 이 원점과 별개**이며 아직 보정하지 않았다.

`forward_kinematics(q, frame="palm")`은 `R_palm.T @ (p_world - t_palm)`을 반환한다.
실제 시뮬레이션 MjData와 FK MjData가 분리되어 있으므로 기구학 평가가 상태를 순간 이동시키지 않는다.
Jacobian은 world frame의 translational `(5,3,20)` 배열이다.

## 별도 변환 파이프라인

1. 원본 URDF를 읽고 config의 20개 joint와 palm/tip 링크가 실제로 존재하는지 검사한다.
2. 별도 normalized URDF에서 package URI를 해석한다. DAE visual을 제외하고 공식 collision
   STL 28개를 사용한다. 원본 geometry 축척, joint origin/axis 및 inertial 입력은 유지한다.
3. MuJoCo URDF importer에서 `fusestatic=false`로 fixed palm/tip 링크를 보존한다.
4. 생성 MJCF에 joint별 position actuator, tip별 site와 scene 조명/카메라를 추가한다.
5. URDF full-precision joint bounds를 다시 기록하고 상대경로 mesh bundle과 출처를 저장한다.

기존 공식 `dg5f_right.xml`도 제공되지만 고정 링크가 합쳐진 형태여서, 이번 실행 경로는
URDF로부터 직접 만들었다. 원본 XML을 편집하거나 교체하지 않았다.
MuJoCo의 XML serializer가 inertial/mesh 관련 값을 canonical 형태로 변환하고 일부 수치를
반올림할 수 있다. FK는 독립 URDF chain으로 검증했으며 하드웨어 동역학 식별을 수행한 것은 아니다.
collision은 MuJoCo mesh convex hull에 따른 근사이므로 정밀 접촉 모델로 간주하지 않는다.

## 제어와 측정 조건

`configs/tesollo_right.json`의 기본값:

| 항목 | 값 |
|---|---|
| physics timestep | 0.002초, 500 Hz |
| demo 제어 주기 | 0.02초, 50 Hz |
| integrator | implicitfast |
| position kp / velocity kv | 12 / 0.2 |
| 추가 armature / damping | 0.001 / 0.01 |
| 중력 | `(0,0,-9.81)` m/s² |
| 중력 보상 | 모든 body에 gravcomp=1 |
| contact | 기본 비활성: 개별 제어/FK 검증용 자유 운동 |

gain·armature·damping·중력 보상은 프로젝트의 시뮬레이션 설정이며 제조사의 실기 제어값이 아니다.
접촉을 실험하려면 새 config에서 `simulation.contacts=true`로 만들고 별도 출력 경로로 build한다.
이 전환만으로 자기충돌이나 파지 성능을 검증한 것으로 취급하지 않는다.

목표각은 기본적으로 초과값을 거부한다. `clip=True`를 명시하면 한계에 맞춰 자르면서
raw `q_target`과 적용한 `q_command`, 실제 `q_actual`을 모두 남긴다. NaN/Inf 및 잘못된
shape는 clipping 옵션과 관계없이 거부한다. MuJoCo joint limit는 soft constraint이므로
실제 상태가 경계를 조금 넘을 수 있다. 측정값은 잘라내지 않는다.

로그의 `tips_command_world`는 제한 적용 명령의 FK이고 `tips_actual_world`는 동역학 실제 상태다.
raw 출력이 제한 초과인 경우 그 사실은 q_target/clipped로 기록한다.

## Quest 좌표계 확장 계약

`HandFrame`은 실제 전송 layout `(21,3)`과 optional `(21,4)` xyzw 회전을 사용한다.
HTS에서는 관절 회전이 없으므로 `joint_rotations=None`이다. `coordinate_frame`과
`timestamp_domain`을 명시하고 wrist pose와 local joint positions를 섞지 않는다.

Phase 3에서는 SDK의 basis 변환, wrist/world 정합, palm frame 정의와 좌우손 처리를 추가한다.
SDK의 기본 Unity LH → RH 변환은 Y reflection이며 position/rotation에 동일 basis를 적용한다.
해당 변환만으로 Tesollo palm 정렬이 완료되는 것은 아니다. 현재 구현된 `select_hts_joints()`는
전체 OpenXR 배열의 점 선택만 수행하며 좌표 변환이나 실시간 수신을 수행하지 않는다.
