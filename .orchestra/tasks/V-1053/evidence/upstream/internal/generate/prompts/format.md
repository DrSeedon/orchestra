# ツアー JSON の形式

出力は 1 つの JSON オブジェクト。

```
Tour = {
  "version": 1,                    // 形式の版。必ず 1
  "title": string,                 // ツアーの題
  "base": string,                  // 指示で与えられる base のブランチ名をそのまま書く
  "head": string,                  // 指示で与えられる head のブランチ名をそのまま書く
  "chapters": [ { "title": string, "steps": Step[] } ]
}

Step = {
  "title": string,
  "question"?: true,               // 問いだけを見せる手順。答えは必ず「次の手順」に置く
  "asks"?: string[],               // この手順で読者が聞きたくなりそうな質問（0〜3 個）。読者は ? キーで選んで聞ける
  "blocks": Block[]
}
```

Block は次のどれか 1 つ（キーで種類を表す）:

| ブロック | 意味 |
|---|---|
| `{ "p": string, "basis"?: "fact" \| "inferred" \| "opinion" }` | 段落。basis は根拠。fact=コード・テスト・コミットメッセージで確かめた / inferred=コードの構造から言える / opinion=一般的な設計の見方（このリポジトリでは確かめていない） |
| `{ "quote": string }` | 引用（コミットメッセージ、レビューコメントなど）。`\n` で段落を分ける |
| `{ "list": string[] }` | 箇条書き |
| `{ "pre": string }` | 整形済みの図（処理の流れ、時系列）。1 行は全角換算でおよそ 38 文字（半角 76 文字）以内 |
| `{ "table": { "head": string[], "rows": string[][] } }` | 表 |
| `{ "code": { "file": string, "at"?: "base" \| "head", "lines": [開始, 終了], "show"?: [開始, 終了], "note"?: string, "marks"?: [ { "line": number, "text": string } ] } }` | リポジトリの実際のコード。lines は強調する行、show は表示する範囲（省略時は前後 2 行）。at の既定は head。note には「変更なし」など。marks は 1 行に付ける短い注記で、その行のすぐ下に矢印付きで描かれる（line は表示する範囲の中） |
| `{ "diff": { "file": string, "hunks"?: number[] } }` | そのファイルの差分。hunks は差分の中のハンク（`@@` で始まる塊）の 0 始まりの番号。省略時はすべて |
| `{ "snippet": { "label": string, "text": string, "lang"?: string } }` | リポジトリにないコード（素直な書き方の例、修正案など）。label に「このリポジトリにないコード」であることを必ず書く。lang は色分けに使う言語（例: "typescript"、"sql"。省略時は中身から推測） |
| `{ "schema": { "migrations": string, "tables"?: string[], "focus"?: string[] } }` | DB のスキーマ。ツールがマイグレーションの SQL を base と head で当てて、変化を表で描く。migrations はディレクトリ、focus は "テーブル.列" |
| `{ "rows": { "tag"?: string, "label": string, "head": string[], "data": string[][], "added"?: string[] } }` | データの例。tag の既定は「例」（説明用に作ったデータ）。added は今回増えた列 |
| `{ "flow": { "nodes": [ { "label": string, "kind"?: "same" \| "changed" \| "new" \| "external", "note"?: string, "next"?: string, "start"?: true } ] } }` | 処理の流れの図。ツールが箱と矢印で上から下へ描く。kind は色分け（changed=この変更で変わった、new=新しく足した、external=DB や外部のサービス、same=変更なし）。note は箱の横の補足（ファイル名など）。next は次の箱への矢印に付ける言葉（渡す値など）。start は、前の箱から呼ばれるのではなく別のきっかけ（別の要求、タイマー、バッチ）で始まる流れの先頭に付ける。付けないと、前の箱から呼ばれるように見える |
| `{ "timeline": { "lanes": string[], "events": [ { "lane": string, "to"?: string, "text": string, "mark"?: "ok" \| "bad" \| "note" } ] } }` | 時間の流れの図。ツールが lanes（要求 A、要求 B、DB など。4 つまで）を列にして、上から下へ時間を描く。to があれば lane から to への矢印（呼び出しや書き込み）、なければ lane の上で起きること。mark は ✔（ok）、✘（bad）、★（note）の印 |
| `{ "files": { "roles"?: [ { "file": string, "role": "core" \| "mechanical" \| "test" \| "config" \| "docs", "note"?: string } ] } }` | 変更したファイルの地図。ツールが git から全ファイルと増減の棒を描く。roles で読み方を付ける（core=頭を使って読む中心、mechanical=機械的な追随、test、config、docs）。file は変更したファイルだけ |
| `{ "target": true }` | 対象の変更の要約（コミット一覧と変更量）。ツールが git から作る。最初の手順に置く |

文字列の中では `` `コード` `` と `**強調**` が使える。

## 守ること

- `file` はリポジトリのルートからの相対パス（例: `src/app.ts`）。
- `lines` と `show` は、指定した時点（base / head）のファイルに**実在する行番号**にする。ツールが検証し、範囲外ならエラーとして表示される。行番号は推測せず、ファイルを読んで確かめる。
- `diff` の `hunks` は、渡された差分に実在するハンクの番号にする。
- 1 つの手順は 1 画面（およそ 40 行）に収まる量にする。
- 作業ディレクトリのファイル名（`change.diff`、`commits.txt`、`base/`、`head/`、`lessons/`）や「渡されたファイル」という言い方を、ツアーの文章に書かない。読者にとっては「このリポジトリ」「コミットメッセージ」「変更前のコード」である。
- `asks` には、この手順を見たジュニアが聞きたくなりそうな質問を、短く書く（「Node は 1 スレッドなのに、なぜ割り込めるの？」「接続を拒否されたときも 10 秒待つ？」）。書く前に、1 つずつ次を確かめ、当てはまるものは捨てる。
  - その手順と、その次の 2 手順の中（表、図、コードの注記を含む）で、もう答えている
  - このリポジトリのコードを読んでも答えられない（誰が決めたか、仕様の予定など）
  - どの変更にも言える一般的な質問（「次はどこから読めばいい？」）
  よい質問は、ツアーが確かめずに置いた前提や、読者が誤解しやすい所を突く。問いの手順（question: true）とその直前の手順には付けない（答えを示してしまうため）。合う質問がなければ付けない。
- 図はツールに描かせる。処理の流れは `flow`、時間の順（同時に 2 回、途中で落ちる、新旧が同時に動く、リトライ）は `timeline`、変更したファイルの全体は `files` を使う。`pre` は、これらで表せない図にだけ使う。
- コードの特定の行について言うことは、段落に書く代わりに `marks` で行に付ける（1 行 1 つ、短く）。段落には、その行から何が言えるかを書く。
- 全体の地図の章では、`files` で中心と機械的な変更を見せ、`flow` で処理の流れを見せる。
