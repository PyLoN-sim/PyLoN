# 月面Nav2

前輪操舵または前後輪操舵のローバーをMunに配置し、RVizのNav2 Goalで指定した位置と向きへ走行させます。3D LiDAR、IMU、車輪情報から自己位置と通行可能な地面を推定します。

## 1. デモをインストールする

[Getting Started](../guide/getting-started.md)でMODとbridgeを導入した後、PyLoNリポジトリのルートで実行します。

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths \
  Ros2/pylon_interfaces Ros2/pylon_bridge Ros2/pylon_vehicle_control \
  Ros2/pylon_perception Demo/pylon_demo_mun_rover \
  --ignore-src --rosdistro jazzy -y
./sync.sh --skip-ksp-build --skip-ksp-sync --demo mun_rover
source ~/ros2_ws/install/setup.bash
```

Nav2、RViz、点群処理に必要な依存パッケージも導入されます。

## 2. ローバーを準備する

1. 左右対称にKSP標準ホイールを4輪または6輪配置します。前輪だけ操舵、または前後輪とも操舵を有効にします。前後輪操舵では後輪を逆向きに切り、6輪の中央ペアは固定でも構いません。
2. 各ホイールのモーターとブレーキを使用できる状態にし、十分な電源を用意します。
3. 制御点を前方へ向けます。Mk2 lander canでは`Control Point: Forward`を選びます。
4. 3D LiDARを前方と地面が見える位置へ固定します。1台ならSensor IDは自動選択されます。幅の広い機体ではLiDARを高めに配置し、左右の地面も視野に入れます。
5. KSPの通常操作でMunへ配置し、全車輪の接地を確認してブレーキを掛け、静止します。

起動時にIMUの重力方向と静止バイアスを30サンプル以上取得します。静止した状態で初期化を待ってください。

`rober B`は4輪すべての操舵を有効にしたまま対応します。制御点をForwardにし、保存済みのLiDAR配置・中距離プロファイルで使用できます。LiDARのID変更や後輪操舵の無効化は不要です。制御点や車輪設定を走行中に変えず、変更後は停止してデモを再初期化してください。

## 3. Nav2とRVizを起動する

手動で起動したbridgeがあれば終了してから、次を実行します。このlaunchはbridgeも起動します。

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch pylon_demo_mun_rover demo.launch.py
```

3D LiDARが複数ある場合は`lidar_sensor_id:=lidar_3d_3bb3e35a`のように指定します。自動選択中に配信元が切り替わると走行を停止し、地図と推定を初期化します。機体ごとの旋回半径と車体外形は車輪・機体データから設定されます。前輪操舵では後軸、前後輪操舵では前後軸の中点が走行とゴール位置の基準です。

既存bridgeを使う場合は`start_bridge:=false`を付けます。bridgeは同時に1つだけ起動してください。

## 4. ゴールを指定する

RVizにURDFの機体、車体外形、白い地面領域が表示され、状態が`Ready: set Nav2 Goal`になるまで待ちます。

1. RVizの`Nav2 Goal`を選択します。
2. 通行可能な地面を押し、到着時に向けたい方向へドラッグして矢印を置きます。
3. 表示された経路と車体の動きを確認します。

写真が重なった範囲は撮影時の明暗で表示されます。通行可否を確認するときは`Surface photos`を一時的に外してください。地図の灰色は未観測領域で、走行対象になりません。最初は観測済みの近い地点を選び、旋回する空間も確保してください。前進で向きを合わせるため、近いゴールでも回り込む場合があります。最高速度は0.5 m/s、加速度は0.2 m/s²です。

到着位置と向きが許容範囲に入ると駐車ブレーキを保持し、Nav2が停止を確認してから成功になります。最初の旋回で車体後部が未観測領域へ出る場合は、まず5 m程度直進して周囲の地面を観測してから旋回目標を指定します。

自分のノードからゴールを送る場合は、公開actionの`/navigate_to_pose`を使います。`/pylon/mun_rover/navigate_to_pose`は内部用です。

## 5. 状態と地図を確認する

別ターミナルでROS環境を読み込んでから実行します。

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 topic echo /pylon/mun_rover/status
```

| 表示・出力 | Topic |
|---|---|
| 地図 | `/pylon/mun_rover/map` |
| 自己位置 | `/pylon/mun_rover/odom`、`odom_3d` |
| 点群・地面・障害物 | `/pylon/mun_rover/points`、`ground`、`obstacles` |
| 計画経路・走行軌跡 | `/pylon/mun_rover/plan`、`trajectory` |
| 機体形状 | `/pylon/mun_rover/geometry` |
| 推定位置に重ねるURDF | `/pylon/mun_rover/robot_description` |
| 蓄積した写真地図 | `/pylon/mun_rover/photo_map` |
| 元のカメラ画像・校正情報 | `/pylon/mun_rover/camera/image_raw`、`camera/camera_info` |
| 写真の枚数・面積・待機理由 | `/pylon/mun_rover/visualization_status` |

地図の範囲は120 m四方、解像度は0.25 mです。TFは`map → pylon_rover_odom → pylon_rover_base_footprint → pylon_rover_base_link`を使います。同梱RViz設定ではこの推定座標系の地図と軌跡を表示します。

`Status`に準備・走行・停止理由が表示されます。地面の白・灰を読みやすくするため、`Local costs`は既定で非表示です。Nav2のコストを調べる場合だけDisplaysで有効にします。

Navigation 2の`Navigation: active`と地図上の`Ready: set Nav2 Goal`が起動完了の目安です。このデモは独自の自己位置推定を使うため、同パネルの`Localization`欄が`inactive`でも異常ではありません。

## 6. 車体と撮影した月面を重ねて見る

`Rover URDF`はプリミティブ形状で表した機体を推定位置・姿勢へ重ねます。`Surface photos`はカメラの写真をLiDARで観測した地面へ投影し、走った場所の周囲へ残します。1台のカメラは自動選択され、複数ある場合は`camera_sensor_id:=camera_c584088f`のように指定します。

地面が写る向きにカメラを取り付け、画像配信を有効にしてください。空や未観測領域、車体で隠れる部分は貼りません。0.5 mの移動または8度の向きの変化を目安に撮影を追加します。写真地図は10 cm格子、120 m四方で、重複部分は見下ろす角度と距離が良い写真を優先します。写真の色は通行可否を示すものではなく、自動走行の判定はLiDARの地図を使います。

ライブ映像を並べるには起動時に`show_camera:=true`を付けます。映像は専用ビューア、写真地図とURDFはRVizに表示します。RVizのImageパネルは一部のHiDPI環境でクラッシュするため使用していません。写真を見やすくするため、`3D LiDAR`と`Ground`は既定では非表示です。

写真はメモリ内に蓄積し、再初期化・機体切替・テレポートで消去します。自動保存はありません。推定誤差や疎な地形観測の影響で継ぎ目や欠けは残ります。写真測量による3D復元や長距離のループ閉じ込みではありません。

## 停止と再初期化

走行中のゴールを取り消すと停止します。指令・センサーの0.5秒以上の欠測、接地喪失、制御権喪失、推定異常でも停止し、古いゴールは自動再開しません。

RVizから指定したゴールはNavigation 2の`Cancel`で取り消します。パネルの`Reset`はNav2自体の停止・後片付けです。地図と自己位置だけの再初期化には下記のサービスを使います。

地形の計算はセンサー処理と別に実行します。地図に使った観測が2秒以上古くなった場合も`terrain_timeout`で停止します。

異常の原因を解消し、停止・ゴール取消・接地を確認してから初期化します。

```bash
ros2 service call /pylon/mun_rover/reset std_srvs/srv/Trigger '{}'
```

再びReadyになったら新しいゴールを指定します。終了する場合はゴールを取り消して停止を確認し、launchのターミナルで`Ctrl-C`を押します。

## 主な起動引数

| 引数 | 既定値 | 用途 |
|---|---|---|
| `lidar_sensor_id` | `auto` | 配信中の3D LiDARが1台なら自動選択。複数ある場合はIDを明示 |
| `camera_sensor_id` | `auto` | 配信中のカメラが1台なら自動選択。複数ある場合はIDを明示 |
| `show_visualization` | `true` | 推定位置のURDFと写真地図を生成 |
| `show_camera` | `false` | ライブ映像を専用ビューアで開く |
| `start_bridge` | `true` | bridgeも起動 |
| `use_rviz` | `true` | RVizを起動 |
| `evaluate` | `false` | Ground Truthと比較する評価ノードを起動 |
| `params_file` | 同梱`config/nav2.yaml` | Nav2の設定 |
| `bt_xml` | 同梱`config/navigate.xml` | ナビゲーションの動作設定 |

真値との比較を行う場合は`evaluate:=true`を付け、`/pylon/mun_rover/evaluation`を確認します。評価は独立したノードで行います。既存bridgeを使う場合は、そちらでもGround Truth配信を有効にしてください。

## 走り出さない・途中で止まる場合

| 状態 | 確認すること |
|---|---|
| Readyにならない | Mun上で全車輪が接地し、静止しているか。制御点がForwardか。前輪または前後輪が左右対称に操舵できるか |
| 地面が灰色のまま | LiDARが前方と左右の地面を観測できているか。取付高さ・角度・距離プロファイルを調整 |
| 経路が作られない | ゴールと経路が観測済みで、車体と旋回の余裕があるか |
| 推定異常で停止 | 地形の特徴、車輪の接地、点群・IMUの受信周期を確認し、停止後にreset |

長距離のループ閉じ込みを行うSLAMではなく、局所地図を使うデモです。通行判定の初期基準は傾斜12度、段差0.25 m、凹凸0.15 mです。車体と0.5 mの余裕を含む停止距離内に未知領域・障害物がある場合も停止します。
