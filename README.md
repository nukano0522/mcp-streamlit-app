# MCP Client - Streamlit UI

MCPクライアントのStreamlitベースのUIインターフェースです。

## 必要条件

このアプリケーションを実行するには以下のパッケージが必要です：

```
uv init ./
uv add "mcp[cli]" httpx
uv add google-search-results huggingface-hub mammoth pathvalidate pdfminer-six pillow puremagic pydub python-pptx requests serpapi "smolagents[litellm]" speechrecognition transformers youtube-transcript-api anthropic
uv add streamlit
```

## インストール方法

1. 必要なパッケージをインストールしてください：

```bash
pip install streamlit anthropic python-dotenv
```

**注意**: MCPパッケージは別途インストールが必要です。

## 使い方

1. Streamlitアプリを起動します：

```bash
streamlit run streamlit_app.py
```

2. ブラウザが自動的に開き、アプリのインターフェースが表示されます。
3. サイドバーの「サーバースクリプトパス」に、接続したいサーバースクリプト（.pyまたは.js）のパスを入力します。
4. 実行モードを選択します（Windows環境ではデフォルトで「Windows互換モード」が選択されます）。
5. 「サーバーに接続」ボタンをクリックします。
6. 接続が成功したら、画面下部のチャット入力欄からメッセージを送信できます。

## 実行モード

このアプリケーションには2つの実行モードがあります：

1. **通常モード**: 標準のMCPクライアントを使用してサーバーに接続します。Unix系OSで動作します。
2. **Windows互換モード**: Windowsでのプロセス実行の問題を回避するためのカスタム実装を使用します。実際のサーバー起動はシミュレートし、Anthropic APIを直接呼び出して応答を生成します。

Windows環境で「NotImplementedError」エラーが発生する場合は、「Windows互換モード」を使用してください。

## デバッグ機能

接続エラーが発生した場合は、デバッグ機能を使用して問題を診断できます：

1. **ログレベル設定**：サイドバーでログレベル（DEBUG, INFO, WARNING, ERROR）を選択できます。
2. **パス解決モード**：相対パスまたは絶対パスのどちらでサーバースクリプトを解決するか選択できます。
3. **パス検証**：サーバースクリプトパスの存在確認や詳細情報を取得できます。
4. **エラーログ履歴**：発生したエラーの詳細情報を確認できます。
5. **環境情報**：Python環境やシステムパスなどの情報を表示します。

## トラブルシューティング

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
