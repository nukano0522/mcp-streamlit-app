import asyncio
import sys
import logging
import traceback
import os
import streamlit as st
import importlib.util
import platform
import json
import re
from dotenv import load_dotenv

load_dotenv()  # 環境変数を.envファイルから読み込む

# インポートパスの調整
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)

# ロギング設定
logging.basicConfig(
    level=logging.INFO,  # DEBUGからINFOに変更して詳細ログを削減
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mcp_client_ui")

# MCPのStdioServerParametersをカスタマイズするため、直接インポート
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    HAS_MCP = True
except ImportError:
    logger.error("MCPライブラリがインポートできません")
    HAS_MCP = False

# MCPClientモジュールのインポート
try:
    from client import MCPClient

    logger_name = "mcp_client_ui"
except ImportError:
    # パスをさらに調整して再試行
    if os.path.exists(os.path.join(current_dir, "client.py")):
        spec = importlib.util.spec_from_file_location(
            "client", os.path.join(current_dir, "client.py")
        )
        client_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client_module)
        MCPClient = client_module.MCPClient
        logger_name = "mcp_client_ui_dynamic"
    else:
        st.error(
            "client.pyが見つかりません。正しいディレクトリで実行しているか確認してください。"
        )
        st.stop()

import inspect

st.set_page_config(page_title="MCP Client", page_icon="🤖", layout="wide")

# セッション状態の初期化
if "client" not in st.session_state:
    st.session_state.client = None
if "connected" not in st.session_state:
    st.session_state.connected = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "error_logs" not in st.session_state:
    st.session_state.error_logs = []
if "execution_mode" not in st.session_state:
    st.session_state.execution_mode = (
        "Windows互換モード" if platform.system() == "Windows" else "通常モード"
    )
if "available_tools" not in st.session_state:
    st.session_state.available_tools = []


def run_async(coroutine):
    """Streamlitでasync関数を実行するためのヘルパー関数"""
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(coroutine)


async def process_query_async(client, query):
    """非同期クエリ処理のラッパー - ツール呼び出しロジックを含む"""
    try:
        # 通常モード（元のMCPClient）の場合はそのまま処理
        if not hasattr(client, "available_tools") or not client.available_tools:
            return await client.process_query(query)

        # Windows互換モード（CustomMCPClient）で、ツール情報がある場合の処理
        try:
            from anthropic import Anthropic

            # Anthropicクライアントが使えるか確認
            if not hasattr(client, "anthropic") or not client.anthropic:
                return "エラー: Anthropicクライアントが初期化されていません"

            # ツール情報をAnthropicに渡す形式に変換
            anthropic_tools = []
            for tool_info in client.available_tools:
                # 入力スキーマの生成
                input_schema = {"type": "object", "properties": {}, "required": []}

                for param_name, param_info in tool_info.get("params", {}).items():
                    param_type = param_info.get("type", "string")
                    if "float" in param_type:
                        schema_type = "number"
                    elif "int" in param_type:
                        schema_type = "integer"
                    elif "bool" in param_type:
                        schema_type = "boolean"
                    else:
                        schema_type = "string"

                    input_schema["properties"][param_name] = {"type": schema_type}
                    input_schema["required"].append(param_name)

                anthropic_tool = {
                    "name": tool_info["name"],
                    "description": tool_info["description"],
                    "input_schema": input_schema,
                }
                anthropic_tools.append(anthropic_tool)

            # 会話履歴を初期化
            messages = [{"role": "user", "content": query}]

            # 初回のAnthropic API呼び出し
            response = client.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=messages,
                tools=anthropic_tools,
            )

            # レスポンス処理と結果の構築
            final_text = []
            tool_uses = []  # 実際のツール使用を記録

            # 最初のレスポンスを処理
            assistant_message = {"role": "assistant", "content": []}

            for content in response.content:
                if content.type == "text":
                    final_text.append(content.text)
                    assistant_message["content"].append(
                        {"type": "text", "text": content.text}
                    )

                elif content.type == "tool_use":
                    tool_name = content.name
                    tool_args = content.input
                    tool_id = content.id

                    # ツール呼び出し情報を保存
                    tool_uses.append(
                        {"id": tool_id, "name": tool_name, "args": tool_args}
                    )

                    # アシスタントメッセージにツール呼び出しを追加
                    assistant_message["content"].append(
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tool_name,
                            "input": tool_args,
                        }
                    )

                    logger.info(f"ツール呼び出し: {tool_name}")

                    # 引数の型変換前処理
                    processed_args = tool_args

                    # ツール呼び出し実行
                    try:
                        tool_result = await client.call_tool(tool_name, processed_args)
                        tool_result_content = (
                            tool_result.content
                            if hasattr(tool_result, "content")
                            else str(tool_result)
                        )
                    except Exception as e:
                        tool_result_content = f"ツール呼び出しエラー: {str(e)}"

                    # 会話履歴に追加
                    final_text.append(f"[ツール呼び出し: {tool_name}]")
                    final_text.append(f"結果: {tool_result_content}")

                    # このツール呼び出しの結果を保存
                    tool_uses[-1]["result"] = tool_result_content

            # アシスタントメッセージを会話に追加
            messages.append(assistant_message)

            # ツール結果がある場合、それを追加
            if tool_uses:
                user_tool_results = {"role": "user", "content": []}

                for tool_use in tool_uses:
                    user_tool_results["content"].append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use["id"],
                            "content": tool_use["result"],
                        }
                    )

                # ツール結果を会話に追加
                messages.append(user_tool_results)

                # 続きのレスポンスを取得
                try:
                    follow_up_response = client.anthropic.messages.create(
                        model="claude-3-5-sonnet-20241022",
                        max_tokens=1000,
                        messages=messages,
                    )

                    # 続きのレスポンスを処理
                    if follow_up_response.content:
                        follow_up_text = follow_up_response.content[0].text
                        final_text.append(follow_up_text)
                except Exception as e:
                    error_detail = str(e)
                    final_text.append(
                        f"エラー: フォローアップ応答の取得に失敗しました: {error_detail}"
                    )

            return "\n".join(final_text)
        except Exception as e:
            logger.error(f"カスタム処理でエラー: {str(e)}")
            # エラー時はバックアップとして元のメソッドを呼び出し
            return await client.process_query(query)
    except Exception as e:
        logger.error(f"process_query_asyncでエラー発生: {str(e)}")
        return f"エラーが発生しました: {str(e)}"


# サーバースクリプトからツール情報を抽出する関数
def extract_tools_from_script(script_path):
    """サーバースクリプトからデコレータを使って定義されたツール情報を抽出する"""
    tools = []
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()

        # @mcp.tool() デコレータのパターンを検索
        function_pattern = r"@mcp\.tool\(\)\s*async\s*def\s+(\w+)\(([^)]*)\)\s*->\s*(\w+):\s*\"\"\"([^\"]*)\"\"\""
        matches = re.findall(function_pattern, script_content, re.DOTALL)

        for match in matches:
            func_name, params_str, return_type, description = match
            params = {}

            # パラメータの解析
            if params_str.strip():
                param_lines = params_str.strip().split(",")
                for param_line in param_lines:
                    if ":" in param_line:
                        param_parts = param_line.strip().split(":")
                        param_name = param_parts[0].strip()
                        param_type = param_parts[1].strip()
                        params[param_name] = {"type": param_type}

            # ツール情報の構築
            tool_info = {
                "name": func_name,
                "description": description.strip(),
                "params": params,
                "return_type": return_type,
            }
            tools.append(tool_info)
    except Exception as e:
        logger.error(f"ツール情報の抽出エラー: {str(e)}")

    return tools


# Windowsでのプロセス実行の問題を回避するためのカスタムスタブ
class CustomMCPClient:
    def __init__(self):
        # 初期化
        self.anthropic = None
        self.available_tools = []
        self.server_script_path = None

        from anthropic import Anthropic

        self.anthropic = Anthropic()

    async def connect_to_server(self, server_script_path):
        """サーバーへの接続をシミュレート"""
        logger.info(f"カスタムモードでサーバー {server_script_path} に接続します")
        self.server_script_path = server_script_path

        # サポートされているファイル拡張子の確認
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError(
                "サーバースクリプトは.pyまたは.jsファイルでなければなりません"
            )

        # スクリプトからツール情報を抽出
        self.available_tools = extract_tools_from_script(server_script_path)
        logger.info(
            f"利用可能なツール: {[tool['name'] for tool in self.available_tools]}"
        )

        # ツール情報の詳細をログに出力
        for tool in self.available_tools:
            logger.debug(f"ツール情報: {json.dumps(tool, indent=2)}")

        # 実際のサーバー起動はシミュレートする
        logger.info("カスタムモード: サーバー接続をシミュレートします")
        return True

    async def list_tools(self):
        """利用可能なツールの一覧を返す"""
        logger.info("カスタムモード: ツール一覧を取得")

        class ToolResponse:
            def __init__(self, tools):
                self.tools = tools

        class Tool:
            def __init__(self, name, description, input_schema):
                self.name = name
                self.description = description
                self.inputSchema = input_schema

        tools = []
        for tool_info in self.available_tools:
            # 入力スキーマの生成（簡略化）
            input_schema = {"type": "object", "properties": {}}

            for param_name, param_info in tool_info.get("params", {}).items():
                param_type = param_info.get("type", "string")
                if "float" in param_type:
                    schema_type = "number"
                elif "int" in param_type:
                    schema_type = "integer"
                elif "bool" in param_type:
                    schema_type = "boolean"
                else:
                    schema_type = "string"

                input_schema["properties"][param_name] = {"type": schema_type}

            tool = Tool(
                name=tool_info["name"],
                description=tool_info["description"],
                input_schema=input_schema,
            )
            tools.append(tool)

        return ToolResponse(tools)

    async def process_query(self, query):
        """クエリ処理をシミュレート"""
        if not self.anthropic:
            return "Anthropicライブラリが利用できないため、応答を生成できません。"

        try:
            # ツール情報をAnthropicに渡す形式に変換
            anthropic_tools = []
            for tool_info in self.available_tools:
                # 入力スキーマの生成
                input_schema = {"type": "object", "properties": {}, "required": []}

                for param_name, param_info in tool_info.get("params", {}).items():
                    param_type = param_info.get("type", "string")
                    if "float" in param_type:
                        schema_type = "number"
                    elif "int" in param_type:
                        schema_type = "integer"
                    elif "bool" in param_type:
                        schema_type = "boolean"
                    else:
                        schema_type = "string"

                    input_schema["properties"][param_name] = {"type": schema_type}
                    input_schema["required"].append(param_name)

                anthropic_tool = {
                    "name": tool_info["name"],
                    "description": tool_info["description"],
                    "input_schema": input_schema,
                }
                anthropic_tools.append(anthropic_tool)

            logger.debug(
                f"Anthropicに渡すツール情報: {json.dumps(anthropic_tools, indent=2)}"
            )

            # Anthropic APIを直接呼び出す（ツール情報を含む）
            response = self.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": query}],
                tools=anthropic_tools if anthropic_tools else None,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic API呼び出しエラー: {str(e)}")
            return f"エラーが発生しました: {str(e)}"

    async def call_tool(self, tool_name, tool_args):
        """ツール呼び出しを実行する"""
        logger.info(f"ツール呼び出し: {tool_name}")

        # 対応するツールが存在するか確認
        tool_info = None
        for tool in self.available_tools:
            if tool["name"] == tool_name:
                tool_info = tool
                break

        if not tool_info:
            return SimpleResponse(f"ツール '{tool_name}' は存在しません")

        # 引数の前処理
        processed_args = {}
        try:
            # 文字列形式の引数を辞書に変換
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    return SimpleResponse(f"引数の解析に失敗しました: {tool_args}")

            # 各パラメータを処理
            for param_name, param_info in tool_info.get("params", {}).items():
                param_type = param_info.get("type", "string")

                # 引数が存在するか確認
                if param_name not in tool_args:
                    continue

                param_value = tool_args[param_name]

                # 型変換
                try:
                    if "float" in param_type:
                        if not isinstance(param_value, (int, float)):
                            processed_args[param_name] = float(param_value)
                        else:
                            processed_args[param_name] = param_value
                    elif "int" in param_type:
                        if not isinstance(param_value, int):
                            processed_args[param_name] = int(float(param_value))
                        else:
                            processed_args[param_name] = param_value
                    elif "bool" in param_type:
                        if not isinstance(param_value, bool):
                            if isinstance(param_value, str):
                                processed_args[param_name] = param_value.lower() in (
                                    "true",
                                    "yes",
                                    "1",
                                    "y",
                                )
                            else:
                                processed_args[param_name] = bool(param_value)
                        else:
                            processed_args[param_name] = param_value
                    else:  # string
                        processed_args[param_name] = str(param_value)
                except (ValueError, TypeError) as e:
                    return SimpleResponse(
                        f"パラメータ {param_name} の型変換に失敗しました: {str(e)}"
                    )
        except Exception as e:
            return SimpleResponse(f"引数処理中にエラーが発生しました: {str(e)}")

        # 必須パラメータの確認
        missing_args = []
        for param_name in tool_info.get("params", {}):
            if param_name not in processed_args:
                missing_args.append(param_name)

        if missing_args:
            return SimpleResponse(
                f"必須パラメータが不足しています: {', '.join(missing_args)}"
            )

        # サーバースクリプトのツール関数を動的にインポートして実行
        try:
            # サーバースクリプトのパスからモジュールをインポート
            script_path = self.server_script_path
            if not script_path.endswith(".py"):
                return SimpleResponse(
                    "現在はPythonスクリプト(.py)のみサポートしています"
                )

            module_name = os.path.basename(script_path)[:-3]  # .pyを削除
            spec = importlib.util.spec_from_file_location(module_name, script_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # ツール関数を取得
            if not hasattr(module, tool_name):
                return SimpleResponse(
                    f"関数 '{tool_name}' がサーバースクリプトに見つかりません"
                )

            tool_function = getattr(module, tool_name)

            # 関数を実行
            if asyncio.iscoroutinefunction(tool_function):
                # 非同期関数の場合
                result = await tool_function(**processed_args)
            else:
                # 同期関数の場合
                result = tool_function(**processed_args)

            class SimpleResponse:
                def __init__(self, content):
                    self.content = content

            return SimpleResponse(result)
        except ImportError as e:
            return SimpleResponse(f"サーバースクリプトのインポートエラー: {str(e)}")
        except Exception as e:
            return SimpleResponse(f"ツール実行エラー: {str(e)}")

    async def cleanup(self):
        """クリーンアップ処理"""
        logger.info("カスタムモード: クリーンアップを実行")
        return True


# MCPClientのメソッドをデバッグ用にラップする関数
def debug_mcp_method(client, method_name):
    original_method = getattr(client, method_name)

    async def wrapped_method(*args, **kwargs):
        logger.debug(f"呼び出し: {method_name} 引数: {args}, キーワード引数: {kwargs}")
        try:
            result = await original_method(*args, **kwargs)
            logger.debug(f"{method_name} 成功")
            return result
        except Exception as e:
            logger.error(f"{method_name} 失敗: {str(e)}")
            raise

    setattr(client, method_name, wrapped_method)


st.title("MCP Client")

# サイドバーでサーバースクリプトパスの入力
with st.sidebar:
    st.header("設定")
    server_script_path = st.text_input("サーバースクリプトパス", "")

    # パス解決モードを選択
    path_mode = st.radio("パス解決モード", options=["相対パス", "絶対パス"], index=0)

    # 実行モードの選択
    execution_mode = st.radio(
        "実行モード",
        options=["通常モード", "Windows互換モード"],
        index=1 if platform.system() == "Windows" else 0,
    )

    connect_button = st.button("サーバーに接続")

    # 接続済みの場合切断ボタンを表示
    if st.session_state.connected:
        if st.button("切断", key="disconnect_sidebar"):
            if st.session_state.client:
                run_async(st.session_state.client.cleanup())
            st.session_state.client = None
            st.session_state.connected = False
            st.session_state.chat_history = []
            st.session_state.available_tools = []
            st.experimental_rerun()


# パス解決関数
def resolve_path(input_path, mode="相対パス"):
    """パスを解決する関数"""
    if not input_path:
        return None

    if mode == "絶対パス" and not os.path.isabs(input_path):
        return os.path.abspath(input_path)
    elif mode == "相対パス" and os.path.isabs(input_path):
        try:
            return os.path.relpath(input_path, os.getcwd())
        except ValueError:
            return input_path
    return input_path


# サーバーへの接続処理
if connect_button and server_script_path:
    # 実行モードをセッションに保存
    st.session_state.execution_mode = execution_mode

    # パスを解決
    # resolved_path = resolve_path(server_script_path, path_mode)
    logger.info(f"サーバー接続: {server_script_path}")

    with st.spinner("サーバーに接続中..."):
        try:
            # パスの検証
            if not os.path.exists(server_script_path):
                raise FileNotFoundError(f"ファイルが存在しません: {server_script_path}")

            # 実行モードに応じてクライアントを選択
            if execution_mode == "Windows互換モード":
                client = CustomMCPClient()
            else:
                client = MCPClient()

            # 実際の接続処理
            connect_result = run_async(client.connect_to_server(server_script_path))

            # ツール情報の取得
            if hasattr(client, "list_tools"):
                try:
                    tools_result = run_async(client.list_tools())
                    if hasattr(tools_result, "tools"):
                        st.session_state.available_tools = [
                            {"name": tool.name, "description": tool.description}
                            for tool in tools_result.tools
                        ]
                except Exception as e:
                    logger.error(f"ツール情報の取得エラー: {str(e)}")

            st.session_state.client = client
            st.session_state.connected = True
            st.sidebar.success(
                f"サーバー {server_script_path} に接続しました！ ({execution_mode})"
            )
        except Exception as e:
            error_detail = traceback.format_exc()
            logger.error(f"接続エラー: {str(e)}")
            st.session_state.error_logs.append((str(e), error_detail))
            st.sidebar.error(f"接続エラー: {str(e)}")
            # エラー詳細を表示するエリア
            with st.expander("エラー詳細情報", expanded=True):
                st.code(error_detail)

# ツール情報表示エリア
if st.session_state.connected and st.session_state.available_tools:
    with st.expander("利用可能なツール", expanded=False):
        st.write(f"合計: {len(st.session_state.available_tools)}個のツールが利用可能")
        for i, tool in enumerate(st.session_state.available_tools):
            st.write(f"**{i+1}. {tool['name']}**")
            st.write(f"説明: {tool['description']}")
            st.write("---")

# チャットインターフェース
if st.session_state.connected:
    # チャット履歴の表示
    for i, (query, response) in enumerate(st.session_state.chat_history):
        with st.chat_message("user"):
            st.write(query)
        with st.chat_message("assistant"):
            # ツール使用の情報を抽出して表示
            tool_usage_info = []
            tool_call_patterns = re.findall(r"\[ツール呼び出し: ([^\]]+)\]", response)

            if tool_call_patterns:
                # ツール使用があった場合
                for tool_name in tool_call_patterns:
                    tool_usage_info.append(tool_name)

                # ツール使用情報を表示
                st.info(f"使用ツール: {', '.join(tool_usage_info)}")

                # 表示用にレスポンスからツール呼び出し情報を整形
                formatted_response = response
                formatted_response = re.sub(
                    r"\[ツール呼び出し: ([^\]]+)\]",
                    r"**ツール呼び出し: \1**",
                    formatted_response,
                )
                formatted_response = re.sub(
                    r"結果: ", r"**結果**: ", formatted_response
                )

                st.markdown(formatted_response)
            else:
                # ツール使用がなかった場合
                st.write(response)
                st.info("ツールは使用されていません")

    # 新しいメッセージ入力
    query = st.chat_input("メッセージを入力...")
    if query:
        with st.chat_message("user"):
            st.write(query)

        with st.chat_message("assistant"):
            with st.spinner("回答を生成中..."):
                try:
                    # UTF-8エンコーディングを明示的に適用
                    query_encoded = query.encode("utf-8").decode("utf-8")

                    # クエリを処理
                    response = run_async(
                        process_query_async(st.session_state.client, query_encoded)
                    )

                    # ツール使用の情報を抽出
                    tool_usage_info = []
                    tool_call_patterns = re.findall(
                        r"\[ツール呼び出し: ([^\]]+)\]", response
                    )

                    if tool_call_patterns:
                        # ツール使用があった場合
                        for tool_name in tool_call_patterns:
                            tool_usage_info.append(tool_name)

                        # ツール使用情報を表示
                        st.info(f"使用ツール: {', '.join(tool_usage_info)}")

                        # 表示用にレスポンスからツール呼び出し情報を整形
                        formatted_response = response
                        formatted_response = re.sub(
                            r"\[ツール呼び出し: ([^\]]+)\]",
                            r"**ツール呼び出し: \1**",
                            formatted_response,
                        )
                        formatted_response = re.sub(
                            r"結果: ", r"**結果**: ", formatted_response
                        )

                        st.markdown(formatted_response)
                    else:
                        # ツール使用がなかった場合
                        st.write(response)
                        st.info("ツールは使用されていません")

                    # チャット履歴に追加
                    st.session_state.chat_history.append((query, response))

                except Exception as e:
                    error_detail = traceback.format_exc()
                    logger.error(f"処理エラー: {str(e)}")
                    st.error(f"エラー: {str(e)}")
                    with st.expander("エラー詳細情報", expanded=True):
                        st.code(error_detail)

else:
    st.info("サーバーに接続してください。")

# エラーログ表示エリア
if st.session_state.error_logs:
    with st.sidebar.expander("エラーログ履歴", expanded=False):
        for i, (error_msg, error_detail) in enumerate(st.session_state.error_logs):
            st.write(f"エラー {i+1}: {error_msg}")
            if st.button(f"詳細を表示 #{i+1}"):
                with st.expander(f"エラー {i+1} 詳細", expanded=True):
                    st.code(error_detail)


# アプリ終了時のクリーンアップ
def cleanup():
    if st.session_state.client:
        logger.info("クライアントをクリーンアップしています...")
        run_async(st.session_state.client.cleanup())


# Streamlitの終了処理はありませんが、ブラウザタブを閉じたときにクリーンアップされるように
# この関数をセッション終了時に呼び出すロジックは実装できません
# そのため、明示的な切断ボタンを提供
if st.session_state.connected:
    with st.sidebar:
        if st.button("切断", key="disconnect_footer"):
            cleanup()
            st.session_state.client = None
            st.session_state.connected = False
            st.session_state.chat_history = []
            st.session_state.available_tools = []
            logger.info("サーバーから切断しました")
            st.experimental_rerun()
