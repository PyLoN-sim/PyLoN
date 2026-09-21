# 配置ファイルから機体を組み立てる

JSONでパーツ名・位置・回転・親子関係・接続ノードを指定し、KSP自身の保存処理で`.craft`を生成します。KSPを起動して**SandboxのVABまたはSPH**を開いてから実行します。ROSノードや追加の建造MODは不要です。

```bash
source ~/ros2_ws/install/setup.bash
ros2 run pylon_bridge craft_builder parts --filter pylon
ros2 run pylon_bridge craft_builder validate /path/to/assembly.json
ros2 run pylon_bridge craft_builder build /path/to/assembly.json --load
ros2 run pylon_bridge craft_builder inspect
```

`--load`は空のエディタに限り読み込みます。既存の機体がある場合は先に保存して「新規」を選んでください。`--load`を省くと、現在の編集内容を維持したままファイルを生成します。生成先は応答の`craftPath`で確認でき、KSPの通常の機体ロードからも読み込めます。

ROS環境を読み込まず、リポジトリから直接実行することもできます。

```bash
PYTHONPATH=Ros2/pylon_bridge python3 -m pylon_bridge.craft_builder \
  build Assets/PyLoN/Examples/servo-stack.json --load
```

KSPの場所は`KSPDIR`、またはサブコマンドの前の`--ksp-dir`で指定します。既定は`~/.local/share/Steam/steamapps/common/Kerbal Space Program`です。`--timeout 60`で応答待ちを変更できます（1〜120秒、既定30秒）。MOD更新後はKSPを再起動してください。

## 配置ファイル

同梱の`GameData/PyLoN/Examples/servo-stack.json`は、PyLoNのサーボ2個を積む例です。編集元は`Assets/PyLoN/Examples/servo-stack.json`です。

```json
{
  "version": 1,
  "name": "My assembly",
  "facility": "VAB",
  "parts": [
    {
      "id": "base",
      "part": "pylon.servo.size0",
      "position": [0, 0, 0],
      "rotation": [0, 0, 0, 1]
    },
    {
      "id": "upper",
      "part": "pylon.servo.size0",
      "position": [0, 0.14, 0],
      "rotation": [0, 0, 0, 1],
      "parent": "base",
      "attach": { "mode": "stack", "node": "bottom", "parent_node": "top" }
    }
  ]
}
```

| フィールド | 意味 |
| --- | --- |
| `version` | `1` |
| `name` | KSPに表示する機体名。80文字以内 |
| `facility` | 現在開いている`VAB`または`SPH` |
| `parts[].id` | ファイル内で一意な識別子。親の参照に使用 |
| `part` | `parts`コマンドが返す内部名。表示名ではない |
| `position` | 共通の機体座標での位置`[x,y,z]`、単位m。親からの相対位置ではない |
| `rotation` | 共通の機体座標での単位クォータニオン`[x,y,z,w]` |
| `parent` | 親の`id`。ルートでは省略または空文字列 |
| `attach` | 子と親を結ぶ接続。ルートでは省略 |
| `stage` | 保存時のステージ初期値。省略時`-1`、指定可能範囲`-1`〜`99`。読み込み時にKSPが整理するため、表示上の番号を固定する指定ではない |
| `autostrut` | 任意。`off` / `root` / `heaviest` / `grandparent`。省略時はパーツ既定値を維持。脚などが持つ強制autostrutの上書きは拒否 |
| `rigid_attachment` | 任意。剛結合を有効にする`true`または無効にする`false`。省略時はパーツ既定値を維持 |
| `separation_force_percent` | 任意。分離力の倍率（既定の分離力に対する0〜100%）。stockの`ModuleDecouplerBase`をちょうど1個持つパーツのみ指定可能 |
| `role` | 任意。`return_engine` / `satellite_separator`などの役割。先頭は英字、以後は英数字・`_`・`-`で64文字以内。複数パーツへの同じ役割の指定も可能 |

たとえば分離器には`"autostrut": "grandparent", "rigid_attachment": true, "separation_force_percent": 15, "role": "satellite_separator"`を指定できます。`role`はKSPの保存可能なカスタムパーツデータに保持され、craftの再読み込み・通常のセーブ・分離で機体が変わった後もパーツに付随します。`parts` / `build` / `inspect`の応答にもこれらの設定を返します。`EngineState.role`・`SeparationState.role`から制御対象のパーツを識別できます。`separation_force_percent`は対象外または複数の分離モジュールを持つ場合`null`です。`role`未設定は空文字列です。

役割は`Part.customPartData`の`pylon.role=`項目に保存し、他のカスタム項目を保持します。追加のPartModuleやModuleManagerは不要です。更新後はKSPを再起動してください。役割は識別用のメタデータで、自動的に制御権やステージ動作を変更しません。

座標系は**KSP/Unityのエディタ座標**です。ROSの`base_link`とは異なります。+Yが上方向で、+X/+Zはエディタの水平軸です。`inspect`はルートの位置・姿勢を基準に計測値を返します。ルートは位置`[0,0,0]`、回転`[0,0,0,1]`で指定してください。エディタ全体での中心合わせによる移動とは独立に、パーツ間の配置を保ちます。

`parts --filter TEXT`は内部名と表示名を検索し、接続ノードの`id`・パーツローカル位置・方向と接続可否を返します。接続ノード位置はモデル原点からのオフセットなので、接続面を合わせる場合は回転後のノード位置も考慮してください。

プローブなどステージ対象外のパーツに`stage`を指定しても、エディタ読み込み時にKSPが`-1`へ戻す場合があります。発進前に通常のステージUIで確認してください。

スタック接続では子の`node`と親の`parent_node`を指定します。表面接続は次のように指定します。

```json
"attach": { "mode": "surface", "node": "srfAttach", "parent_node": "" }
```

**座標を接続ノードへ自動スナップしません。** エディタのオフセット操作のように、指定した位置を保って接続します。ファイルの親子関係は単一の木とし、接続ノードの二重使用は拒否します。ファイル内のパーツ順序は親より先に子を書いても構いません。

## 保存と検証

生成時はインストール済みのパーツを使用し、既定のモジュール・リソースと明示した設定をKSPの保存処理へ渡します。保存データをKSPで再読み込みし、個数・パーツ種別・親子関係・接続・位置・回転、および指定したautostrut・剛結合・分離力・役割を検証してから、現在のセーブの`Ships/VAB`または`Ships/SPH`へ保存します。検証の位置許容差は0.5mm、回転は0.05度です。

保存名は`PyLoN_<request-id>.craft`で、既存ファイルを上書きしません。表示名はJSONの`name`です。`build`の結果は仕様中の`id`、`inspect`はKSPのcraft IDに`p`を付けた識別子を返します。

v1の制限:

- Sandboxのエディタ専用。Flight中のスポーンや自動発進は行いません。
- 1〜256パーツ、入力1MiB以内、位置の各成分は±1000m以内。
- 上記の設定以外はパーツの既定バリアント・既定状態を使用します。リソース量や任意のPartModule設定、対称配置、ストラット／燃料ラインの追加ターゲット、ロボティクスの初期角度などの個別指定は未対応です。
- 接続と幾何配置の検証は、物理的な安定性、干渉のなさ、飛行可能性を保証しません。配置が重なる場合も自動修正しません。
- 同じ環境・指定での配置を対象とします。KSPやMODが発行するID等を含むファイル全体のバイト一致は保証しません。

## 通信とエラー

コマンドは同じPCの`<KSP>/PluginData/PyLoN/CraftBuilder/`で要求・応答を受け渡します。外部ネットワークの待受はありません。エディタ起動ごとのセッションIDと期限を検証し、古い要求を別の編集セッションで実行しません。要求は一度だけ処理し、自動再送しません。

標準出力はJSONで、成功は`ok: true`・終了コード0です。失敗は`ok: false`・終了コード1です。タイムアウト時は結果が不明な場合があるため、表示された要求IDの`results/<id>.json`と生成済みファイルを確認してください。処理済み応答はこのディレクトリに残ります。

`Editor status heartbeat is stale`の場合はKSPが起動中で、エディタが動作しているか確認してください。`facility`が一致しない場合は指定のVAB/SPHを開きます。パーツ名やノード名は`parts`コマンドで確認できます。

## 公開インターフェースの根拠

確認日: 2026-09-21。KSP本体の逆コンパイル、非公開メンバーへのreflectionアクセス、メソッド差し替えは使用していません。ローカルのKSP DLLをコンパイル時に参照し、通常の公開メンバーを呼び出します。公開メンバーの利用可能性と公式な互換性保証は別です。

次の公開MODはAPI呼び出しの使用例として確認しました。実装コードのコピーや、これらのMODへの実行時依存はありません。

| 対象・所有者 | 確認した呼び出し・用途 | 公開例 |
| --- | --- | --- |
| Unity / KSP | `Object.Instantiate(partPrefab)`、`ShipConstruct`、`SaveShip()`でパーツから保存データを作る | [Extraplanetary Launchpads / PartEditorView](https://github.com/taniwha/Extraplanetary-Launchpads/blob/0bb3c5b0bf083e4284611682cc4f65f6b4a9d77b/Source/UI/PartEditorView.cs)（GPLv3以降） |
| KSP | `ShipConstruct.LoadShip(ConfigNode)`と一時オブジェクトの破棄 | [Extraplanetary Launchpads / BuildControl](https://github.com/taniwha/Extraplanetary-Launchpads/blob/0bb3c5b0bf083e4284611682cc4f65f6b4a9d77b/Source/BuildControl.cs)（GPLv3以降） |
| KSP | `EditorLogic.LoadShipFromFile`とエディタの初期化状態確認 | [kRPC / Editor](https://github.com/krpc/krpc/blob/8cfe77a515f39495e6c2c10b42010b2d206f0729/service/SpaceCenter/src/Services/Editor.cs)（SpaceCenter部分はGPLv3以降） |
| KSP | `ShipConstruction.ShipConfig`の退避・復元 | [VesselMover / VesselSpawn](https://github.com/jrodrigv/VesselMover/blob/875bbcef2ec00501ebe673daecc0ae21263e9e6b/VesselSpawn.cs)（MITの宣言あり） |
| KSP | `Part.autoStrutMode`・`Part.rigidAttachment`で構造設定を適用 | [EditorExtensionsRedux](https://github.com/linuxgurugamer/EditorExtensionsRedux/blob/bc7430b4e061987e847230e163986ed8bb68192c/EditorExtensionsRedux/EditorExtensionsRedux.cs)（MIT） |

分離力の設定はKSPの公開フィールド`ModuleDecouplerBase.ejectionForcePercent`を使用します。役割は保存と読み込みを目的に公開されている`Part.customPartData`へ名前付き項目を追加します。これらも本番のコンパイル時参照と通常の公開アクセスであり、非公開reflectionは使用しません。[Part公開メンバー一覧](https://kspmoddinglibs.github.io/KSPDocsSite/class_part.html)、[ModuleDecouple公開メンバー一覧](https://kspmoddinglibs.github.io/KSPDocsSite/class_module_decouple.html)（コミュニティのAPI文書。公式な互換性保証を意味しません）。

`PartLoader`、`Part.parent/children`、`AttachNode.attachedPart`、パーツの姿勢・接続ルール等へのアクセスも本番側の通常の公開メンバー呼び出しです。接続グラフ構築は自作実装で、KSPでの保存・再読み込みと実機試験で確認します。調査用ソース・試験コード・ログはGit管理外の`Development/`に保管し、本番ビルドには含めません。
