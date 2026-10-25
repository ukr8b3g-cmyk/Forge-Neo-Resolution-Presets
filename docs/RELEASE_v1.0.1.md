## Settings editor fixes / 設定画面の修正

- Clearing resolution history preserves unsaved Profile edits, selection and preset Undo.
- Edits made during a save remain in the draft after the response. The editor distinguishes saved submitted changes from newer unsaved edits and prevents overlapping saves/restores.
- Unicode-equivalent Profile names such as `Strasse` / `Straße` cause a clear save error. The whole request is rejected before backup or writing, preserving both the saved file and the draft.
- Duplicate names reserve room for `Copy` and numeric suffixes within the 32-character limit. Japanese and emoji names use the same Unicode codepoint count as the server.

- 履歴削除で未保存のProfile編集・選択・PresetのUndoが失われる問題を修正しました。
- 保存中に追加した編集を応答で上書きせず、未保存のまま保持します。保存・復元の重複操作も抑止します。
- `Strasse` / `Straße`などUnicode名が衝突する場合は、Profileを黙って除去せず保存全体をエラーにします。既存ファイルと編集中の内容を保持します。
- 長い名前の複製はCopy・連番を含め32文字以内で生成します。日本語・絵文字の文字数の扱いもサーバーと統一しました。

## Updating / 更新

Keep the existing `data/` directory, personal presets, Profile overrides and behavior settings. This release does not migrate or rewrite them during installation. Existing built-in profiles, including all 15 MOSS presets, are unchanged.

既存の`data/`、個人プリセット、Profile編集内容、動作設定は保持してください。インストール時の移行・設定書き換えはありません。MOSSの15件を含め、同梱Profileの内容は変更していません。

The updated Python routes become active after your next normal Forge Neo/reForge restart and browser refresh. This release does not restart the host automatically.

更新したPythonの処理は、次回ご自身でForge Neo／reForgeを通常どおり再起動し、ブラウザを再読み込みすると反映されます。自動再起動は行いません。

## Validation / 検証

- 39 Python tests (33 existing + 6 save regressions), 18 JavaScript state tests: passed.
- 10 isolated Edge browser groups using the real FastAPI save routes and temporary files: passed, no JavaScript exceptions. Includes delayed responses, save failure, Unicode rejection, long/emoji names, reload and MOSS preservation.
- Python/JavaScript/JSON syntax and whitespace checks passed.
- The isolated browser fixture stubs Forge/Gradio registration. Live host integration, theme rendering and GPU generation are separate checks and were not performed for this fix.

Python39件・JavaScript18件・独立Edge＋実保存APIの10グループが成功しました。実Forge内の統合画面・テーマ・GPU生成は今回の検証対象に含みません。
