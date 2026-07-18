# Profile Editor 再設計仕様書

## 1. 文書情報

- 対象：Forge Neo Resolution Presets
- 対象画面：`Settings` → `Extensions` → `Resolution Presets` → `Profile Editor`
- 状態：実装前の確定仕様案
- 作成日：2026-07-18

本仕様は、Profileと解像度Presetを初見でも迷わず編集・追加・複製・削除・保存できることを目的とする。メインのtxt2img／img2img UIと、既存のWidth／Height処理は変更しない。

## 2. 用語

| 用語 | 意味 |
| --- | --- |
| Profile | 解像度Presetをまとめたセット。例：Anima、SDXL、Flux |
| Preset | 1つのWidth／Height。例：1024×1344 |
| Main row | Profileの先頭9件。通常表示されるPreset |
| More Portrait | 10件目以降。追加表示される縦長Preset |
| Draft | ブラウザ上で編集中、まだ保存していない状態 |
| Built-in | `profiles.json`に収録された標準Profile |

## 3. 基本方針

- Profile操作とPreset操作を明確に分ける。
- ボタン名だけで対象が分かるようにする。
- 重要な削除操作は赤系で示す。ただし、色だけに意味を依存しない。
- 編集内容はDraftとして扱い、`Save changes`までファイルへ反映しない。
- 保存状態を常に小さく表示する。
- 説明文は長くせず、操作に必要な補足だけを表示する。
- 行ボタンは文字幅＋最小限の余白とし、残り幅で横に引き伸ばさない。
- `profiles.json`は読み取り専用のBuilt-inデータとして扱う。

## 4. 画面構成

### 4.1 全体レイアウト

```text
Profile Editor
Profile = 解像度Presetのセット

Profile [Anima (default) ▼]
[New profile] [Duplicate profile] [Delete profile] [Make default]

● Unsaved changes
Width × Height                         Actions
↕ Main 1  [1024] × [1024]  [Duplicate] [Delete]
↕ Main 2  [1280] × [1280]  [Duplicate] [Delete]
...

[+ Add preset]                         [Save changes]
                                        [Restore built-in profiles]

Backup / Restore
Randomize Settings
Resolution History
```

### 4.2 Profile見出し

表示内容：

- 見出し：`Profile Editor`
- 補足：`Profile = a set of resolution presets.`
- Profile選択欄：現在のProfile名と`(default)`を表示
- Profile操作ボタン：Profileを対象にすることが分かる名称を使用

Profile操作ボタンの名称：

| 表示 | 動作 |
| --- | --- |
| `New profile` | 新しいProfile名を入力して作成する |
| `Duplicate profile` | 選択中Profileを複製する |
| `Delete profile` | 選択中Profileを削除する |
| `Make default` | 選択中Profileを起動時の標準Profileにする |

`New profile`はブラウザ標準の曖昧なPromptだけに依存せず、Profile名、作成、キャンセルを含む小さな入力UIを表示する。Profile名は1～32文字、空欄不可、重複不可とする。

複製時の名前は、元が`Anima`なら`Anima Copy`、同名が存在する場合は`Anima Copy 2`のように自動調整する。複製後は複製Profileを選択状態にする。

### 4.3 説明と保存状態

Profile操作欄の下に、次の説明を小さく表示する。

```text
Edit Width / Height directly. Drag ↕ to reorder. Changes apply after Save changes.
First 9 presets appear in Main row; the rest appear in More Portrait.
```

保存状態は説明文とは別に表示する。

| 状態 | 表示例 | 色 |
| --- | --- | --- |
| 保存済み | `Saved` | 通常の補助色 |
| 編集中 | `Unsaved changes` | オレンジ／警告色 |
| 保存完了 | `Saved · backup created` | 成功色または通常色 |
| エラー | `Could not save: ...` | 赤 |

以下の操作はすべて`Unsaved changes`にする。

- Profileの追加、複製、削除
- default Profileの変更
- Width／Heightの変更
- Presetの追加、複製、削除
- ドラッグによる並べ替え

### 4.4 Preset行

1行は次の順序で表示する。

```text
[↕] [Main 1] [Width] × [Height] [Duplicate] [Delete]
```

- `↕`：ドラッグ用ハンドル。`Drag to reorder`のツールチップとアクセシブル名を付ける。
- `Main 1`／`More 10`：順番から自動生成し、直接編集不可。
- Width／Height：数値入力。現在の値を直接修正できる。
- 行の`Duplicate`：対象Presetを1件複製し、直後に挿入する。
- 行の`Delete`：対象Presetを削除する。

行ボタンの幅は`max-content`相当とし、次を満たす。

- `Duplicate`：文字列と左右の余白だけで表示する。
- `Delete`：文字列と左右の余白だけで表示する。
- 画面の残り幅を行ボタンが占有しない。
- 狭い画面でも、行ボタンが画面幅いっぱいの大きなボタンにならない。

### 4.5 Preset操作

| 操作 | 仕様 |
| --- | --- |
| `+ Add preset` | 選択中Profileの末尾に追加。14件を超える場合は無効化または理由を表示 |
| 行`Duplicate` | 直後に複製。複製後のWidth／Heightを編集して保存する流れを想定 |
| 行`Delete` | その行をDraftから削除。Profileには最低1件を残す |
| ドラッグ | 行を移動し、Main／More Portraitの境界も順番に応じて更新 |

追加するPresetの初期値は、既存と重複しない有効な解像度を選ぶ。重複する値を作った場合は行の近くに`Duplicate resolution`を表示し、保存できない理由を明示する。

### 4.6 下部アクション

推奨配置：

```text
[+ Add preset]                         [Save changes]
                                        [Restore built-in profiles]
```

- `Save changes`：唯一の主要保存ボタン。Forge NeoのPrimary色を使用する。
- `Restore built-in profiles`：Built-inへ戻す。警告色にし、実行前に確認する。
- `Restore built-in profiles`は現在のProfileだけでなく、編集対象Profile全体を標準状態へ戻すことを明示する。
- Restore実行前には、現在のProfile設定を自動Backupする。

## 5. 危険操作のデザイン

### 5.1 色

削除は通常ボタンと明確に区別する。

- 行`Delete`：薄い赤系の背景または赤系のアウトライン
- `Delete profile`：より強い赤系。Profile全体に影響するため行Deleteより目立たせる
- `Restore built-in profiles`：赤ではなくアンバー系の警告色
- `Save changes`：Forge Neo標準のPrimary色

赤色だけで意味を伝えず、必ず`Delete`という文字を表示する。アイコンだけの削除ボタンにはしない。

### 5.2 確認と取り消し

- Profile削除：Profile名を含む確認を必須にする。
- Preset削除：頻繁な編集を妨げないよう、確認ダイアログは必須にしない。削除後は`Preset deleted · Undo`を表示する。
- 最後の1件は削除不可とし、ボタンを無効化するか理由を表示する。
- Restore：確認を必須にし、未保存のDraftが失われることを表示する。
- `Reload UI`実行時に未保存Draftがある場合は、未保存内容が失われることを警告する。

## 6. 保存・バックアップ仕様

### 6.1 Draft

- Profile Editorを開いた時点でAPIから状態を読み込む。
- 画面内の編集はブラウザ上のDraftだけを変更する。
- `Save changes`を押すまで、Profile設定ファイルを変更しない。
- Profileを切り替えても、同じ画面内のDraft変更は保持する。

### 6.2 Save changes

保存時の順序：

1. 必須項目と重複を検証する。
2. 現在のProfile設定を`data/profile_backups/`へ自動保存する。
3. 有効なProfile設定を`data/profile_overrides.json`へ保存する。
4. 画面を保存後の状態へ更新する。
5. `Saved · backup created`を表示する。

Built-inの`profiles.json`は直接変更しない。

### 6.3 相対パス表示

Profile EditorまたはBackup／Restore欄に、説明を増やしすぎない小さな文字で次を表示する。

```text
Built-in: profiles.json · Edited profiles: data/profile_overrides.json · Backups: data/profile_backups/
```

## 7. バリデーション

保存前に画面内でエラーを表示し、無効な状態をサーバーへ送らない。

- Profile名：1～32文字、空欄不可、重複不可
- Profile数：1件以上
- Preset数：1～14件
- Width／Height：整数、16～16384、8の倍数
- 同一Profile内のWidth×Height重複不可
- `NaN`、空欄、負数、浮動小数を保存不可
- エラーは対象行の近くに表示し、画面上部のステータスにも要約する
- 保存失敗時はDraftを保持し、入力内容を消さない

## 8. Backup／Restore、Randomize、History

Profile Editor本体の操作を邪魔しないよう、下部の各セクションは現在の独立構成を維持する。

### Backup／Restore

- `Create backup`：現在の設定を手動Backupする。
- `Restore selected`：選択したBackupを復元する。確認必須。
- Backupの選択欄が空の場合はボタンを実行不可にする。
- 保存前に自動Backupが作成されることを明示する。

### Randomize Settings

- `Start Randomize ON`：起動時のRandomize初期状態を設定する。
- `Include custom presets`：ユーザープリセットを抽選対象に含める。
- `Save Randomize settings`で保存し、次回`Reload UI`から反映する。

### Resolution History

- 履歴は参照専用。
- `Clear history`は確認必須。
- 履歴がない場合は`No resolution history`を表示する。

## 9. アクセシビリティとレスポンシブ

- すべてのボタンに対象が分かる可視テキストを付ける。
- 削除の意味を色だけで伝えない。
- Width／Height入力にはアクセシブルなラベルを付ける。
- ドラッグハンドルには`Drag to reorder`のアクセシブル名を付ける。
- ドラッグできない環境向けに、キーボードで順番を変更できる代替操作を用意する。
- フォーカスリングを消さない。
- 800px以下では入力欄を縮小または折り返すが、Duplicate／Deleteを画面幅いっぱいにしない。
- 行の情報順序はWidth、Height、操作の順を維持する。

## 10. メインUIとの境界

- Profile EditorはSettingsページだけに存在する。
- txt2img／img2imgの通常表示高さを増やさない。
- 保存後のProfile内容をメインUIへ反映するには`Reload UI`を使用する。
- Width／Height、縦横入れ替え、Randomizeの生成処理は既存実装を再利用する。
- Profile EditorのCSSは`#fnp_settings_editor`配下に限定する。
- 画像処理、アップスケール、モデル解析、チェックポイント変更は行わない。

## 11. 受け入れ条件

### 初見操作

- 初見ユーザーがProfileとPresetの違いを説明文だけで理解できる。
- 選択中Profile、編集対象のWidth／Height、保存状態が一目で分かる。
- Profile複製とPreset複製の対象を取り違えない。
- Deleteが削除操作であることを色と文字の両方で認識できる。

### 編集操作

- Width／Heightを直接編集できる。
- Presetを追加、複製、削除、並べ替えできる。
- Profileを追加、複製、削除、default変更できる。
- Main 1～9とMore Portraitの区分が順番変更後も正しく更新される。
- 14件上限、1件未満禁止、重複禁止が分かりやすく表示される。

### 保存と復元

- 未保存変更が`Unsaved changes`になる。
- 無効な内容は保存できず、入力内容が保持される。
- 保存前に自動Backupが作成される。
- 保存後にReload UIを行うとtxt2img／img2imgへ反映される。
- Restoreは確認後に実行され、実行前の状態へ戻せる。

### 回帰確認

- txt2img／img2imgのWidth／Heightが表示される。
- 標準の縦横入れ替えボタンが動作する。
- Main UIの通常表示高さが増えない。
- Settings以外の拡張のボタン幅・配色・レイアウトを変更しない。
- ブラウザコンソールに本拡張固有のエラーがない。

## 12. 実装対象ファイル

- `scripts/forge_neo_resolution_presets_settings.py`：HTML構造、初期値、Settings登録
- `javascript/forge_neo_resolution_presets_settings.js`：Draft、操作、検証、API呼び出し、ステータス表示
- `style.css`：Profile Editor専用レイアウト、ボタン色、レスポンシブ対応
- `README_ja.md`：操作方法、保存先、Reload UI、削除とBackupの注意事項

実装時は、Profile Editor以外のメイン解像度UIとデータ形式を変更しない。
