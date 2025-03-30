import asyncio
import sys
import logging
import traceback
import os
import streamlit as st
import platform
import re
from dotenv import load_dotenv

load_dotenv()  # 環境変数を.envファイルから読み込む

# インポートパスの調整
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# カスタムクライアントモジュールのインポート
from mcp_client.client_st import (
    MCPClient,
    CustomMCPClient,
    process_query_async,
    SimpleResponse,
    HAS_MCP,
)

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mcp_client_ui")

st.set_page_config(page_title="MCP Client", page_icon="🤖", layout="wide")

# セッション状態の初期化
if "client" not in st.session_state:
    st.session_state.client = None
if "connected" not in st.session_state:
    st.session_state.connected = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
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


st.title("MCP Client")

# サイドバーでサーバースクリプトパスの入力
with st.sidebar:
    st.header("設定")
    # セレクトボックスでサーバースクリプトパスを選択
    server_script_path = st.selectbox(
        "サーバースクリプトパス",
        options=[
            f"{os.getenv('BASE_MCP_SERVER_PATH')}/weather/weather.py",
            f"{os.getenv('BASE_MCP_SERVER_PATH')}/deep_research/deep_research.py",
        ],
    )

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
