# 機体制御とGround Truth

正式な機体制御APIは、KSPの実`vessel_id`へ期限付きleaseを取得してから、body frameのWrenchまたは型付きアクチュエータ指令を送ります。KSP側が所有権、SAS排他、sequence、timeout、安全上限を最終判定します。

## 制御フロー

1. `/ksp_vessel/lifecycle`で`STATE_ACTIVE`または`STATE_CHANGED`と`vessel_id`を受け取る。
2. `/ksp_vessel/control/authority/command`へ`ACTION_ACQUIRE`を送る。
3. `/ksp_vessel/control/authority/state`で同じ`controller_id`と`lease_id`の`STATE_OWNED`を確認する。
4. leaseと同じidentityを持つ指令を、timeoutより短い周期で送る。
5. 制御終了時に`ACTION_RELEASE`を送る。停止時に送れなくてもleaseは期限切れになる。

`sequence`は正の符号付き64 bit整数です。同じ`controller_id + lease_id`内で、authority、姿勢（Flight/Wrench共通）、種類とIDで区別した各アクチュエータ、各motor、各docking portを独立に比較します。同じ経路内の重複・古い値は拒否しますが、別Topicの到着順が逆転してもheartbeatや他の対象を巻き込みません。既存の全指令共通カウンタも利用できます。`last_sequence`は最後に受理した経路の値であり、全経路の最大値ではありません。`priority`が高い新規leaseだけが現在のownerをpreemptできます。同じpriorityでは先に取得したownerを維持します。

## Topic

| 方向 | Topic | 型 | QoS / 内容 |
|---|---|---|---|
| Subscribe | `/ksp_vessel/control/authority/command` | `ControlAuthorityCommand` | Reliable。取得、更新、解放、e-stop |
| Publish | `/ksp_vessel/control/authority/state` | `ControlAuthorityState` | Reliable / Transient Local。KSPが確定したowner |
| Subscribe | `/ksp_vessel/control/wrench_command` | `BodyWrenchCommand` | Reliable。lease-bound body Wrench |
| Publish | `/ksp_vessel/control/wrench_feedback` | `WrenchFeedback` | requested / allocated / achieved / residual |
| Publish | `/ksp_vessel/lifecycle` | `VesselLifecycle` | Reliable / Transient Local。機体identityとframe状態 |

`BodyWrenchCommand.header.frame_id`は空または`base_link`だけを受け付けます。座標は+X前、+Y左、+Z上、forceはN、torqueはN·mです。`timeout_sec`は0.05〜10秒です。

角速度・トルクもROSの右手系です。Unityからの変換では、位置・力の軸入替に加え、軸性ベクトルの左右反転符号を補正します。角速度はGround Truth姿勢quaternionの時間差分と同じ回転方向になります。

手動確認では、まずlifecycleから実際のIDを確認します。

```bash
ros2 topic echo --once /ksp_vessel/lifecycle
ros2 topic echo /ksp_vessel/control/authority/state
ros2 topic echo /ksp_vessel/control/wrench_feedback
```

通常の連続制御には、lease更新とsequence採番を行う`pylon_vehicle_control`を使ってください。

```bash
ros2 run pylon_vehicle_control setpoint_controller --ros-args \
  -p controller_id:=my_controller \
  -p setpoint_topic:=/my_controller/setpoint
```

共通controllerの`ATTITUDE_HOLD`と`SIX_DOF`は、姿勢誤差を`attitude_hold_rate_limit_deg_s`以下の目標body角速度へ変換して内側の角速度loopを閉じます。上限を超える回転をさらに加速するtorque成分も除き、制動を優先します。`DETUMBLE`はbody角速度と反対向きのtorqueだけを生成します。

## 「要求」と「実現」の違い

力はN、トルクはN·mで指定します。WrenchはKSPの操舵入力へ配分され、ノズル配置、推力上限、燃料、機体状態によって実現量が変わります。制御器では`WrenchFeedback`で要求値と実現量の差を確認してください。

RCS配分器は、現在有効な各ノズルについて次をKSPと同じ軸規則で評価し、12個の正負操作channelを解きます。

- `useZaxis`を含む実際のノズル噴射軸
- ノズル位置と現在のcenter of massから得るモーメントアーム
- pitch / yaw / rollとX / Y / Zのenable設定
- moduleの作動状態と現在の最大推力

`WrenchFeedback`の値は次の意味です。

| field | 意味 |
|---|---|
| `requested` | controllerが送った値 |
| `allocated` | 安全filterとアクチュエータ配分後の要求値 |
| `achieved` | 直前のKSP physics tickで観測したengine/RCS推力から再構成した値 |
| `allocation_residual` | `requested - allocated` |
| `tracking_residual` | `requested - achieved` |
| `saturation_ratio` | 配分できなかった割合 |
| `tracking_error_ratio` | 観測値との差の割合 |

`achieved`にはreaction wheel、タイヤ接触力、空力は含みません。`achieved_quality`に測定遅延と除外対象を明記します。並進による回転や燃料・KSP制御則による差を隠さず、controller側で飽和を判断できます。

型付き`EngineCommand.target_thrust`、`RcsCommand.thrust_limit`、`WheelCommand.max_drive_torque`と対応するstateも同じくN/N·mです。

## SAS・emergency stop・安全上限

`suppress_sas: true`のleaseを取得すると、ownerが存在する期間を通じてKSP側がSASを停止し、解放または期限切れ時に元の状態へ戻します。個々のトルク指令の有無では切り替えません。

`ACTION_EMERGENCY_STOP`は通常のWrenchと個別overrideをゼロ化し、SASも停止したままlatchします。解除できるのはe-stopを発行した同じ`controller_id + lease_id`だけです。e-stopの状態は機体切替では自動解除されません。

e-stop自体は現在のownerでなくても、activeな`vessel_id`と一意なlease identity、正のsequenceを指定して発行できます。解除は同じidentityでsequenceを増やします。

```bash
ros2 topic pub --once /ksp_vessel/control/authority/command \
  pylon_interfaces/msg/ControlAuthorityCommand \
  "{action: 4, vessel_id: '<vessel-id>', controller_id: safety_operator, lease_id: '<unique-lease-id>', sequence: 1}"

ros2 topic pub --once /ksp_vessel/control/authority/command \
  pylon_interfaces/msg/ControlAuthorityCommand \
  "{action: 5, vessel_id: '<vessel-id>', controller_id: safety_operator, lease_id: '<unique-lease-id>', sequence: 2}"
```

KSP側の最終制限は`GameData/PyLoN/Config/ControlSafety.cfg`で設定します。

| 設定 | 既定値 | 内容 |
|---|---:|---|
| `maxForceN` | 250000 | force magnitude上限 |
| `maxTorqueNm` | 100000 | torque magnitude上限 |
| `maxAngularSpeedRadSec` | 0.35 | これを超える回転を加速する成分を除去 |
| `maxForceSlewNPerSec` | 50000 | force変化率上限 |
| `maxTorqueSlewNmPerSec` | 10000 | torque変化率上限 |
| `maxContinuousActuationSec` | 30 | 非ゼロ指令の連続時間上限 |
| `continuousResetIdleSec` | 0.5 | 連続時間limitを解除するゼロ指令時間 |

ROS側の上限よりKSP側を大きく設定し、KSP側は故障時の最終境界として使うのが基本です。

## Ground Truthとframe

| Topic | frame_id | 内容 |
|---|---|---|
| `/ksp_vessel/ground_truth/pose` | `pylon_ground_truth_enu` | 位置m、姿勢quaternion |
| `/ksp_vessel/ground_truth/nearby_vessels` | `pylon_ground_truth_enu` | 自機と近隣機体の同時刻・同原点の絶対位置・速度。差分から相対状態を算出 |
| `/ksp_vessel/ground_truth/twist` | `pylon_ground_truth_enu` | world-frame速度m/s、角速度rad/s |
| `/ksp_vessel/ground_truth/twist_body` | `base_link` | body-frame速度m/s、角速度rad/s |
| `/ksp_vessel/ground_truth/acceleration` | `pylon_ground_truth_enu` | world-frame運動学的加速度 |
| `/tf` | `pylon_ground_truth_enu -> base_link` | KSP universal time基準のdynamic TF |
| `/tf_static` | proxy fixed joint / sensor mount | 取付姿勢 |

センサーデータのtimestampはKSP universal timeからROS clockへ対応付けます。Ground Truthの最新poseを同じセンサー時刻へ最大0.1秒外挿してTFを補うため、点群より遅い姿勢周期によるfuture extrapolationを避けます。

`VesselLifecycle`は`UNAVAILABLE / ACTIVE / CHANGED / STALE`、generation、origin sequence、model readinessを公開します。display nameではなく`vessel_id`が制御identityです。機体切替時、既存leaseと不一致なproxy modelは即座に無効になります。

## 飛行デモ用の操舵・状態

`/ksp_vessel/control/flight_command`は`FlightControlCommand`を受信します。
`pitch / yaw / roll`はKSP標準の正規化入力（−1〜1）で、リアクションホイール、
エンジンジンバル、舵面に伝わります。ROSの角度・トルクではありません。
`landing_gear`はGear action groupを設定します。推力は既存の`EngineCommand`で指定します。

すべての指令に同じlease identityと増加sequenceが必要です。`timeout_sec`は0.05〜1秒。
非有限・範囲外入力、他機体・他ownerからの指令は拒否します。操舵とBody Wrenchは
同じ姿勢軸を同時に所有せず、後から受理された方式が優先されます。
timeout、lease喪失、e-stop、機体変更で操舵を解除します。着陸脚の展開状態は維持します。
Body Wrench用の力・トルクフィルターとは別の、stock入力を使う低水準APIです。

`/ksp_vessel/ground_truth/flight`は`FlightState`（Best Effort / depth 10）を配信します。
`--disable-ground-truth`では配信しません。高度はASLと機体基準のAGL、質量はkg、
速度はm/s、動圧はPa、緯度経度は度です。燃料・酸化剤・電力はKSPのresource unitです。
遠点・近点高度、遠点までの秒数、接地・着水状態も含みます。
`up_body / east_body / north_body`は現在位置の地表座標軸を`base_link`で表した単位ベクトル、
速度・軌道速度・角速度も`base_link`です。`universal_time`はKSPの計測時刻です。

この出力はシミュレータ真値です。地形高度は脚先からの距離ではないため、
着陸制御では機体寸法・重心移動を考慮してください。利用例は[衛星分離・逆噴射着陸](../demos/reusable-launch.md)。

## 順序付き飛行指令

`/ksp_vessel/control/batch` (`ControlBatch`) は、1つのROSメッセージを1つのUDP datagramへ変換します。実行順序は **lease更新 → 姿勢 → engines配列順 → 分離1件** です。分離は機体世代を変え得るため必ず最後です。最大16エンジン、各入力のtimeoutは0.05〜1秒です。

外側の`vessel_id / controller_id / lease_id / sequence`を内側の全指令に適用します。`has_flight / has_separation`がfalseの項目は実行しません。`renew_lease=true`で制御と同じtickにheartbeatを送れます。取得・解放・e-stopには引き続きauthority Topicを使用します。同じleaseではbatchと個別の操作Topicを混在させず、取得・batch・解放を通じて1つの増加カウンタを使ってください。

UDPでは内側の指令を`flightJson / engineJson[] / separationJson`のJSON文字列として格納し、KSPが全件を明示的にデコード・検証してから実行します。ROS側のメッセージ構造は変わりません。

KSPは古いbatch全体を拒否し、受理したbatchを1つのmain-thread callbackで順に処理します。UDPの再送・配送保証や、物理操作失敗時のrollbackを提供するものではありません。分離の完了は下記の結果APIで確認してください。

## 分離結果と再照会

`SeparationCommand`の`operation_id`には操作ごとに一意なIDを指定します。`original_runtime_instance / original_runtime_epoch / original_vessel_id`は初回に省略するとbridgeが現在のidentityを補います。再照会では初回の値をそのまま使います。

結果Topicは`/ksp_vessel/actuators/separation/result` (`SeparationResult`, Reliable / Transient Local, depth 128) です。`completed && success && retained`で完了を確認します。旧epoch・generation、新epoch・generation、現在の機体ID、元のパーツ群から観測した分離後の機体ID一覧を含みます。機体manifestからパーツが消えただけでは成功にしません。

KSPは完了結果をプロセス内で10分間、最大128件保持します。満杯の場合は新しい分離を拒否し、保存済み結果を追い出しません。同じ操作ID・元identityの再受信は保持中の結果を返し、再実行しません。別の対象・controllerへのID使い回しは拒否します。結果は現在の通信epochで再送するため、分離でepochが変わっても取得できます。プロセス再起動で保持内容は失われます。

再照会は`/ksp_vessel/actuators/separation/get_result` (`GetSeparationResult`)。初回の操作identityを渡します。bridgeに結果があれば`found=true`、なければ読み取り専用問い合わせをKSPへ送り`query_sent=true`を返します。結果Topicの更新後に再照会してください。未完了のcacheがある場合も再問い合わせします。新たなleaseは再照会には不要ですが、KSPへの通信には現在のunpackedセッションが必要です。cache済み結果はpacked時も照会できます。`result_not_retained`は未実行の証明ではありません。

## シミュレータ状態と一貫した観測

`/ksp_vessel/simulator/state` (`SimulatorState`) は10 Hzの実時間heartbeatから生成します。pause、warp倍率、physics warp、packed、操作可能性、UT進行、最後にUTが進んでからの実時間を区別します。状態は`INITIALIZING / ADVANCING / PAUSED / STALLED / UNAVAILABLE / STALE`です。`STALLED`はheartbeatが届いているのにUTが0.5秒以上進まない状態、`STALE`はheartbeat欠測です。通信途絶だけからKSP停止とネットワーク断を区別することはできません。`communication_alive=false`の場合、pause等の値は最後の観測値です。

`FlightState / EngineState / SeparationState`には共通の`vessel_id / runtime_instance / runtime_generation / runtime_epoch / observation_sequence`があります。観測番号はUnity frame番号で、epoch内だけで比較します。`/ksp_vessel/control/snapshot` (`ControlSnapshot`) は同じframe・UTの飛行状態、全エンジン、現在の全分離器を1つのメッセージで返します。部分欠測・異なるepoch/frame/UTの混合は拒否します。UDP上限に収まらない巨大なsnapshotは部分配信せず省略します。真値を含むため`--disable-ground-truth`ではsnapshotも配信しません。

## 共通checkpointと再開検証

`pylon_vehicle_control.application.checkpoint`の`MissionCheckpoint.capture`は、真空の無推力軌道で機体identity、構成ID、資源、質量、天体、軌道、未完了操作、旧leaseを記録します。`to_dict / from_dict`でJSON保存・復元でき、復元時にもschema・型・上限を検証します。

`validate_resume`へ現在のsnapshot、SimulatorState、authority、最も古い受信時刻を渡すと、再開可否と理由を返します。新しい観測、同じ機体・epoch・構成・軌道、資源の許容差、ゼロ推力、未完了操作の解決、他owner不在を確認します。許可後は新しいleaseを取得し、取得結果も再検証してください。旧leaseの復元・再使用は拒否します。再使用デモの軌道HOLD復帰はこの共通処理を使用します。

このAPIはKSPセーブの作成・ロードやwarp実行を行いません。quicksaveのロード・packed/unpackedなどでepochが変わった場合は再開を拒否します。別epochへの再対応付けと軌道セーブからの自動runnerは別途必要です。

## 入力軸・適用結果・熱と電力

正のbody軸入力とstock入力の対応は次の通りです。共通関数`pylon_vehicle_control.application.flight_axes.stock_inputs_for_body_axes`と軸ごとのテストで固定しています。応答の大きさは機体・速度・可動部の状態に依存します。

| body軸の正方向 | stock入力 |
|---|---|
| +X回転 | roll + |
| +Y回転 | pitch − |
| +Z回転 | yaw − |

`FlightState.applied_pitch / applied_yaw / applied_roll`はPyLoNが最後に`OnFlyByWire`へ書いた入力です。`applied_input_sequence / applied_input_age / applied_input_valid / flight_command_active`を併せて確認します。`input_at_limit`は正規化入力が上限に達していることを示し、実トルク飽和の測定ではありません。個別エンジンのジンバル入力は`EngineState`の既存フィールドを使います。舵面の実偏角・各装置の寄与トルクは未計測です。

`/ksp_vessel/health/thermal` (`PartThermalState`) は各パーツの内部・表面温度と上限（K）、空力遮蔽、電力残量・容量を2 Hzで配信します。`/ksp_vessel/health/power` (`VehicleHealth`) は機体全体の電力残量・容量と、そのUT差分から求めた収支推定（EC/s）です。`net_charge_rate_valid`と推定区間を確認してください。epochや容量の変更直後・pause中は推定を無効にします。発電量と消費量を別々には復元できないため、両方のvalid flagはfalseです。電池が満杯でも発電ゼロとは限りません。

## 型付きアクチュエータの共通条件

`EngineCommand`、`RcsCommand`、`WheelCommand`、`MotorCommand`、`SeparationCommand`も同じ`vessel_id`、`controller_id`、`lease_id`、`sequence`を必須とします。ownerでない指令はKSPが拒否します。不可逆な分離操作もlease外では実行されません。


## Bridge起動引数

| 引数 | 既定値 |
|---|---|
| `--body-wrench-command-topic` | `/ksp_vessel/control/wrench_command` |
| `--control-authority-command-topic` | `/ksp_vessel/control/authority/command` |
| `--control-authority-state-topic` | `/ksp_vessel/control/authority/state` |
| `--wrench-feedback-topic` | `/ksp_vessel/control/wrench_feedback` |
| `--vessel-lifecycle-topic` | `/ksp_vessel/lifecycle` |
| `--ground-truth-prefix` | `/ksp_vessel/ground_truth` |
| `--actuators-prefix` | `/ksp_vessel/actuators` |
| `--vehicle-command-timeout-sec` | `0.5` |

共通setpoint controllerは制御権喪失・入力欠測・実行中の世代変更で目標を破棄します。復旧時は新たな`MODE_IDLE`を受けてから、後続の新しいsetpointを受理します。
