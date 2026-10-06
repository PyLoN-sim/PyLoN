# PyLoNのリリース

MODはKSPをインストールしたローカル環境でビルドし、GitHub Releasesへ手動でアップロードします。CI用runnerや参照DLLのアップロードは不要です。

## ソースと生成物

- `Source/PyLoN`: C#ソース。
- `Assets/PyLoN`: 配布用CFG・モデル・画像の原本。Gitで管理します。
- `GameData/PyLoN`: ビルド時に原本とDLLから毎回作り直す配置用フォルダ。Git管理外です。
- `dist/PyLoN-vX.Y.Z.zip`と`.zip.sha256`: 配布ZIPとSHA-256チェックサム。Git管理外です。

`PyLoN.csproj`はKSPインストール内の`Assembly-CSharp.dll`とUnityのDLLをコンパイル時に参照します。これらは`Private=false`であり、配布ZIPにも入りません。パッケージ処理は`Assets/PyLoN`のCFG・MU・PNGとビルドした`PyLoN.dll`、ルートの`LICENSE`を格納します。`Development/`、`Tools/`、PDB、ROS2ワークスペースは含めません。

## 配布ZIPを作る

Linuxで.NET 8 SDK、Python 3、KSP 1.xを用意し、リリース対象のソースを確認してから実行します。

```bash
./package.sh v1.0.0 --ksp-dir "$HOME/.local/share/Steam/steamapps/common/Kerbal Space Program"
```

バージョンは例です。`v1.0.0-rc.1`形式も使えます。`KSPDIR`環境変数も指定可能です。`package.sh`はRelease構成でビルドしてからZIPを作り、KSPへのインストールは行いません。Windowsでの通常のビルドは引き続き`build.ps1`を使えます。

```bash
cd dist
sha256sum --check PyLoN-v1.0.0.zip.sha256
unzip -l PyLoN-v1.0.0.zip
```

ZIP直下は`GameData/PyLoN/`で、`LICENSE`、`Plugins/PyLoN.dll`、`Config/`、`Models/`、`Parts/`を含みます。利用者はこの`PyLoN`フォルダをKSPの`GameData`へ配置します。

## GitHubへ登録する

1. 変更をコミット・pushし、ビルドに使ったコミットをリリース対象にします。
2. [Releases](https://github.com/PyLoN-sim/PyLoN/releases)の「Draft a new release」で同じバージョンのタグを選択または作成し、対象コミットを確認します。
3. `dist/`のZIPと`.zip.sha256`を添付し、変更内容を記載して公開します。候補版はpre-releaseにします。

GitHubが自動生成する「Source code (zip/tar.gz)」はMOD配布物ではありません。利用者には添付した`PyLoN-vX.Y.Z.zip`を案内してください。

## ROS 2 Jazzyコンテナの配布（GHCR）

ビルド済みROSコンテナはGitHub PackagesのContainer registryへ配布します。Dockerfileと起動設定は`Docker/jazzy/`に置き、MODのZIPは引き続きGitHub Releasesへ添付します。ROSコンテナのビルドにKSPやゲームDLLは不要です。

`.github/workflows/jazzy-container.yml`は次の順序で実行します。

1. `test` stageをビルドし、bridgeと機体制御の回帰テストを実行する。
2. 成功した同じコミットの`runtime` stageをビルドする。
3. workflowの`GITHUB_TOKEN`（`packages: write`）で`ghcr.io/pylon-sim/pylon-bridge`へpushする。

PRはテストのみです。`main`への関連ファイルのpush、GitHub Releaseの公開、Actionsの「Jazzy container」→「Run workflow」で配布できます。手動実行は選択したrefをビルドするため、公開するソースを確認してから実行します。対象platformは実KSPで検証した`linux/amd64`です。

| タグ | 意味 |
| --- | --- |
| `jazzy` | mainの更新、手動実行、通常リリースで更新するJazzyイメージ |
| `jazzy-sha-<40桁のcommit SHA>` | ビルドしたソースのコミットを示すタグ |
| `jazzy-vX.Y.Z` | 公開したGitHub Releaseのタグに対応するイメージ |

pre-releaseの公開はバージョンタグとSHAタグだけを作り、`jazzy`を更新しません。再ビルドでapt依存が変わる可能性があるため、同じイメージを固定する用途にはタグではなくworkflowのSummaryに出る`image@sha256:...`を使用します。

### 初回公開の確認

初回のGHCRパッケージはprivateになるため、組織のPackagesで`pylon-bridge`を開き、Package settingsでvisibilityを**Public**にします。Publicにする対象がPyLoNのROSイメージであることを確認してください。公開リポジトリだけではパッケージのPublic設定は保証されません。

workflow成功後、ログインしていないDocker環境でpullできることを確認します。

```bash
mkdir -p /tmp/pylon-ghcr-anonymous
DOCKER_CONFIG=/tmp/pylon-ghcr-anonymous docker pull ghcr.io/pylon-sim/pylon-bridge:jazzy
docker run --rm ghcr.io/pylon-sim/pylon-bridge:jazzy ros2 pkg executables pylon_bridge
```

GitHubの[Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)を参照してください。利用者の起動・接続確認は[Getting Started](https://github.com/PyLoN-sim/docs/blob/main/guide/getting-started.md)にまとめます。
