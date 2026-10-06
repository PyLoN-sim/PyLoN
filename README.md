![PyLoN](Assets/OGP.png)

# PyLoN

PyLoNは、Kerbal Space Program 1.xのセンサーと機体をROS2から扱うためのMODです。KSPとROS2 bridgeを接続し、点群・画像を使う認識ノードや、ローバー・宇宙機の制御アプリケーションを開発できます。

## リポジトリ構成

| リポジトリ | 内容 |
|---|---|
| [PyLoN](https://github.com/PyLoN-sim/PyLoN) | KSP MOD、ROS2 bridge、共通パッケージ、ビルド・配布ツール |
| [demos](https://github.com/PyLoN-sim/demos) | センサー・制御APIを使う5つのデモと起動スクリプト |
| [docs](https://github.com/PyLoN-sim/docs) | 導入ガイド、APIリファレンス、VitePressサイト |

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/PyLoN-sim/PyLoN.git
git clone https://github.com/PyLoN-sim/demos.git  # デモを使う場合
cd PyLoN
./sync.sh
# 必要なデモだけ追加（既定で隣のdemosを参照）
./sync.sh --skip-ksp-build --skip-ksp-sync --demo reusable
```

デモの場所を変える場合は`PYLON_DEMOS_DIR=/path/to/demos`を指定します。本体のビルドにはdemos・docsのcloneは不要です。

## 導入

[Getting Started](https://github.com/PyLoN-sim/docs/blob/main/guide/getting-started.md)で、Ubuntu 24.04とDockerの準備、MODのインストール、Docker内のJazzy bridgeの起動、機体情報と3D LiDARの受信まで説明しています。

導入後は[ROS2アプリケーションを作る](https://github.com/PyLoN-sim/docs/blob/main/guide/application-development.md)へ進んでください。[システム概要](https://github.com/PyLoN-sim/docs/blob/main/guide/overview.md)では通信経路、Topicの寿命、IDと座標系を確認できます。

Dockerの構成・ローカルビルド・Composeでの起動は[Dockerの構成・運用](https://github.com/PyLoN-sim/docs/blob/main/guide/docker.md)を参照してください。Dockerfileは`Docker/jazzy/`、GHCRの初回公開手順は[RELEASING.md](RELEASING.md)にあります。

Space ROSを使用する場合は[Space ROSで動かす](https://github.com/PyLoN-sim/docs/blob/main/guide/space-ros.md)を参照してください。公式イメージ内でPyLoNをビルドし、ホストのKSPと接続できます。

配布版MODは[Releases](https://github.com/PyLoN-sim/PyLoN/releases)の`PyLoN-vX.Y.Z.zip`を展開し、`GameData/PyLoN`をKSPの`GameData`へコピーします。更新前にインストール先の`Config/Runtime.cfg`を控えてください。「Source code」アーカイブにはビルド済みMODは含まれません。ROS2パッケージはGHCRのJazzyイメージを使うか、Dockerfileからビルドします。初回のイメージ公開とPackagesのPublic設定が完了するまではローカルビルドを使用してください。

## APIリファレンス

| 目的 | 参照先 |
|---|---|
| 入出力とメッセージ型を調べる | [Topic一覧](https://github.com/PyLoN-sim/docs/blob/main/api/topics.md) |
| 機体の制御権を取得し、力・トルクを指令する | [機体制御とGround Truth](https://github.com/PyLoN-sim/docs/blob/main/api/vehicle-control.md) |
| 機体モデルとTFを受信し、RVizで表示する | [Active vesselモデル](https://github.com/PyLoN-sim/docs/blob/main/api/vessel-model.md) |
| 距離・画像・姿勢を取得する | [LiDAR](https://github.com/PyLoN-sim/docs/blob/main/parts/lidar.md)、[RGBカメラ](https://github.com/PyLoN-sim/docs/blob/main/parts/camera.md)、[スタートラッカー](https://github.com/PyLoN-sim/docs/blob/main/parts/star-tracker.md) |
| 関節・車輪・推進系を操作する | [モーターと可動フィン](https://github.com/PyLoN-sim/docs/blob/main/parts/motors.md)、[ホイール](https://github.com/PyLoN-sim/docs/blob/main/parts/wheels.md)、[エンジン・RCS](https://github.com/PyLoN-sim/docs/blob/main/parts/propulsion.md) |
| 切離しやドッキングポートを操作する | [分離機構](https://github.com/PyLoN-sim/docs/blob/main/parts/separation.md)、[ドッキングポート](https://github.com/PyLoN-sim/docs/blob/main/parts/docking.md) |

各APIページにTopic名、型、単位、座標系、設定値、指令の条件を記載しています。

## 設定と運用

- [Bridge起動オプション](https://github.com/PyLoN-sim/docs/blob/main/reference/bridge-options.md)：受信アドレス、指令の送信先、Topic名、タイムアウト
- [パーツ設定](https://github.com/PyLoN-sim/docs/blob/main/reference/part-config.md)：センサー・モーターの設定と共通の`Runtime.cfg`
- [トラブルシュート](https://github.com/PyLoN-sim/docs/blob/main/reference/troubleshooting.md)：Topicの受信、モーター制御、画像・機体モデル表示の確認
- [移行ガイド](Migration/README.md)：既存セーブ・機体・ワークスペースの更新

## デモ

[デモ一覧・共通準備](https://github.com/PyLoN-sim/docs/blob/main/demos/index.md)から、使うセンサーと目的に合うデモを選べます。各ページに機体の準備から起動、動作確認、停止までをまとめています。

- [軌道上のデブリ周回・撮影](https://github.com/PyLoN-sim/docs/blob/main/demos/debris-orbit.md)
- [2D LiDARとSLAM](https://github.com/PyLoN-sim/docs/blob/main/demos/lidar-slam.md)：地図作成・保存・Nav2走行
- [月面Nav2](https://github.com/PyLoN-sim/docs/blob/main/demos/mun-nav2.md)
- [衛星分離・逆噴射着陸](https://github.com/PyLoN-sim/docs/blob/main/demos/reusable-launch.md)：Space ROS lifecycleと専用機体Phoenix（実飛行未検証）

## PyLoN本体への貢献

MOD、ROS2 bridge、メッセージ定義、ドキュメントへの変更は[本体開発ガイド](https://github.com/PyLoN-sim/docs/blob/main/contributing/index.md)を参照してください。ビルド・同期、変更の検証、コミットに含める内容、ドキュメントのプレビュー方法をまとめています。

内部構成は[アーキテクチャ](https://github.com/PyLoN-sim/docs/blob/main/contributing/architecture.md)、変更箇所の案内は[ソース案内](https://github.com/PyLoN-sim/docs/blob/main/contributing/source-map.md)にあります。

配布資産の原本は`Assets/PyLoN`、`GameData/`はビルドごとに作り直す生成物です。ソースからのビルドには`./build.sh --ksp-dir "$KSPDIR"`（Windowsでは`build.ps1`）を使います。配布ZIPの作成と手動公開は[リリース手順](RELEASING.md)、通信境界は[Bridge設計](Ros2/pylon_bridge/ARCHITECTURE.md)を参照してください。

## ライセンス

[MIT License](LICENSE)。配布物には著作権表示とライセンス本文を同梱します。
