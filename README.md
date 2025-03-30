# MCP Client - Streamlit UI

MCPクライアントのStreamlitベースのUIインターフェースです。

## Prerequisites

このアプリケーションを実行するには以下のパッケージが必要です：

```bash
uv venv
source .venv/bin/activate
```

```bash
uv init ./
uv add "mcp[cli]" httpx
uv add google-search-results huggingface-hub mammoth pathvalidate pdfminer-six pillow puremagic pydub python-pptx requests serpapi "smolagents[litellm]" speechrecognition transformers youtube-transcript-api anthropic
uv add streamlit
```

## Usage

1. Start the Streamlit app:

```bash
streamlit run ./mcp_client/streamlit_app.py 
```

2. ブラウザが自動的に開き、アプリのインターフェースが表示されます。
3. サイドバーの「サーバースクリプトパス」に、接続したいサーバースクリプト（.pyまたは.js）のパスを入力します。
4. 実行モードを選択します（Windows環境ではデフォルトで「Windows互換モード」が選択されます）。
5. 「サーバーに接続」ボタンをクリックします。
6. 接続が成功したら、画面下部のチャット入力欄からメッセージを送信できます。

## Execution Mode

This application has two execution modes:

1. **通常モード**: 標準のMCPクライアントを使用してサーバーに接続します。Unix系OSで動作します。
2. **Windows互換モード**: Windowsでのプロセス実行の問題を回避するためのカスタム実装を使用します。実際のサーバー起動はシミュレートし、Anthropic APIを直接呼び出して応答を生成します。

Windows環境で「NotImplementedError」エラーが発生する場合は、「Windows互換モード」を使用してください。

## Debugging Features

If a connection error occurs, you can use the debugging features to diagnose the problem:

1. **ログレベル設定**：サイドバーでログレベル（DEBUG, INFO, WARNING, ERROR）を選択できます。
2. **パス解決モード**：相対パスまたは絶対パスのどちらでサーバースクリプトを解決するか選択できます。
3. **パス検証**：サーバースクリプトパスの存在確認や詳細情報を取得できます。
4. **エラーログ履歴**：発生したエラーの詳細情報を確認できます。
5. **環境情報**：Python環境やシステムパスなどの情報を表示します。

## Troubleshooting

接続エラーが発生する場合、以下を確認してください：

1. サーバースクリプトのパスが正しいか
2. サーバースクリプトの拡張子が`.py`または`.js`であるか
3. ログレベルを「DEBUG」に設定して詳細な情報を確認
4. パス検証機能を使用してファイルの存在を確認
5. 適切なパス解決モードを選択（相対パスか絶対パス）

### Windowsでの問題

Windows環境で以下のようなエラーが表示される場合：

```
NotImplementedError: 
Traceback (most recent call last):
  File "...mcp/client/stdio/win32.py", line 72, in create_windows_process
    ...
  File "...asyncio/base_events.py", line 498, in _make_subprocess_transport
    raise NotImplementedError
```

「Windows互換モード」を使用してください。このモードではサブプロセスの起動をシミュレートし、Anthropic APIを直接呼び出して応答を生成します。

## 注意事項

- 元のコマンドライン版とは異なり、このUIバージョンではStreamlitを利用しています。
- セッションを終了する場合は、サイドバーの「切断」ボタンをクリックしてください。
- エラーメッセージはUI上に表示されます。
- Windows互換モードでは実際のサーバープロセスは起動せず、機能が制限される場合があります。

## 通常モードとWindows互換モードの主な違い
1. 実装方法
- 通常モード：MCPClientクラスを使用
  - 実際にサーバープロセスを起動して通信を行います
  - mcpライブラリのClientSessionを使用して、子プロセスとして実行されるサーバーと標準入出力（stdio）を通じて通信します
- Windows互換モード：CustomMCPClientクラスを使用
  - サーバープロセスを起動せず、同一プロセス内でサーバースクリプトの機能を直接呼び出します
  - サーバースクリプトからツール情報を静的に抽出し、サーバー機能をシミュレートします
2. 通信方法
- 通常モード：
  - 子プロセスとしてサーバースクリプトを実行し、標準入出力を通じて通信
  - StdioServerParametersを使用してプロセス間通信を確立
- Windows互換モード：
  - プロセス間通信なし（同一プロセス内で実行）
  - サーバースクリプトの関数を動的にインポートして直接呼び出し
3. ツール情報の取得方法
- 通常モード：
サーバーのlist_toolsメソッドを呼び出して実行時にツール情報を取得
- Windows互換モード：
  - サーバースクリプトのソースコードを解析して静的にツール情報を抽出
  - 正規表現を使用して@mcp.tool()デコレータで定義された関数を検索
4. ツール実行方法
- 通常モード：
  - サーバープロセスにツール呼び出しリクエストを送信
  - 結果を非同期に受信
- Windows互換モード：
  - サーバースクリプトを直接インポートし、関数を同一プロセス内で呼び出し
  - importlib.utilを使用して動的にモジュールをロード
5. 主な使用目的
- 通常モード：
  - 標準的な環境での使用（Linux、macOSなど）
  - サーバープロセスの分離が重要な場合
- Windows互換モード：
  - Windowsでのプロセス実行の問題を回避
  - 子プロセスの起動やプロセス間通信に問題がある環境で使用

### 実装の詳細
Windows互換モードでは、サーバースクリプトのコードから直接ツール情報を抽出し、実行時に関数を動的にインポートすることで、サーバープロセスを起動せずに同様の機能を提供します。これにより、Windowsでのプロセス実行に関連する問題（パスの解決、プロセス終了の処理など）を回避できます。

### デフォルト設定
アプリケーションはシステムに応じて自動的にモードを選択します：
Windowsシステムでは「Windows互換モード」がデフォルト
Linux/macOSでは「通常モード」がデフォルト
ただし、ユーザーはUIから手動でモードを切り替えることも可能です
