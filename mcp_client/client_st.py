import asyncio
import sys
import logging
import importlib.util
import os
import json
import re
import traceback
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack

from anthropic import Anthropic
from dotenv import load_dotenv

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    HAS_MCP = True
except ImportError:
    logging.getLogger("mcp_client_st").error("MCPライブラリがインポートできません")
    HAS_MCP = False

load_dotenv()  # load environment variables from .env

# ロガーの設定
logger = logging.getLogger("mcp_client_st")


class SimpleResponse:
    """ツール呼び出し結果を格納するシンプルなレスポンスクラス"""

    def __init__(self, content):
        self.content = content


class MCPClient:
    """標準的なMCPクライアント - 実際のサーバープロセスと通信します"""

    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server

        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError(
                "サーバースクリプトは.pyまたは.jsファイルでなければなりません"
            )

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env={"PYTHONIOENCODING": "utf-8"},  # エンコーディングを明示的に指定
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        logger.info(
            f"サーバーへの接続に成功しました。利用可能なツール: {[tool.name for tool in tools]}"
        )
        return True

    async def list_tools(self):
        """利用可能なツールの一覧を返す"""
        if not self.session:
            raise ValueError("サーバーに接続されていません")
        return await self.session.list_tools()

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        messages = [{"role": "user", "content": query}]

        response = await self.session.list_tools()
        available_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

        # Initial Claude API call
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=messages,
            tools=available_tools,
        )

        # Process response and handle tool calls
        tool_results = []
        final_text = []

        for content in response.content:
            if content.type == "text":
                final_text.append(content.text)
            elif content.type == "tool_use":
                tool_name = content.name
                tool_args = content.input

                # Execute tool call
                try:
                    result = await self.session.call_tool(tool_name, tool_args)
                    tool_result_content = result.content
                except Exception as e:
                    tool_result_content = f"ツール呼び出しエラー: {str(e)}"
                    logger.error(f"ツール呼び出しエラー: {str(e)}")

                # 結果を追加
                tool_results.append({"call": tool_name, "result": tool_result_content})
                final_text.append(f"[ツール呼び出し: {tool_name}]")
                final_text.append(f"結果: {tool_result_content}")

                # Continue conversation with tool results
                if hasattr(content, "text") and content.text:
                    messages.append({"role": "assistant", "content": content.text})
                messages.append({"role": "user", "content": tool_result_content})

                # Get next response from Claude
                follow_up_response = self.anthropic.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    messages=messages,
                )

                final_text.append(follow_up_response.content[0].text)

        return "\n".join(final_text)

    async def cleanup(self):
        """Clean up resources"""
        logger.info("クライアントをクリーンアップしています...")
        await self.exit_stack.aclose()


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


class CustomMCPClient:
    """Windows互換モード用のMCPクライアント - サーバープロセス起動せずにツールを呼び出す"""

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

    async def process_query(self, query: str) -> str:
        """クエリを処理してレスポンスを生成"""
        if not self.anthropic:
            return "Anthropicライブラリが利用できないため、応答を生成できません。"

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

            anthropic_tools.append(
                {
                    "name": tool_info["name"],
                    "description": tool_info["description"],
                    "input_schema": input_schema,
                }
            )

        logger.debug(
            f"Anthropicに渡すツール情報: {json.dumps(anthropic_tools, indent=2)}"
        )

        # 初回のAnthropicAPI呼び出し（ツール情報付き）
        messages = [{"role": "user", "content": query}]
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=messages,
            tools=anthropic_tools if anthropic_tools else None,
        )

        # レスポンス処理とツール呼び出し
        final_text = []
        tool_uses = []

        for content in response.content:
            if content.type == "text":
                final_text.append(content.text)
            elif content.type == "tool_use":
                tool_name = content.name
                tool_args = content.input
                tool_id = content.id

                # ツール呼び出し実行
                tool_result = await self.call_tool(tool_name, tool_args)
                tool_result_content = (
                    tool_result.content
                    if hasattr(tool_result, "content")
                    else str(tool_result)
                )

                # 結果を追加
                final_text.append(f"[ツール呼び出し: {tool_name}]")
                final_text.append(f"結果: {tool_result_content}")
                tool_uses.append(
                    {
                        "id": tool_id,
                        "name": tool_name,
                        "result": tool_result_content,
                    }
                )

        # ツール結果がある場合、それを元に続きの会話を生成
        if tool_uses:
            # ツール結果を会話に追加
            messages = [{"role": "user", "content": query}]
            messages.append({"role": "assistant", "content": response.content})

            user_tool_results = {"role": "user", "content": []}
            for tool_use in tool_uses:
                user_tool_results["content"].append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use["id"],
                        "content": tool_use["result"],
                    }
                )

            messages.append(user_tool_results)

            # 続きのレスポンスを取得
            follow_up_response = self.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=messages,
            )

            if follow_up_response.content:
                final_text.append(follow_up_response.content[0].text)

        return "\n".join(final_text)

    async def call_tool(self, tool_name, tool_args):
        """ツール呼び出しを実行する"""
        logger.info(f"tool calling: {tool_name}")

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

            return SimpleResponse(result)
        except ImportError as e:
            return SimpleResponse(f"サーバースクリプトのインポートエラー: {str(e)}")
        except Exception as e:
            return SimpleResponse(f"ツール実行エラー: {str(e)}")

    async def cleanup(self):
        """クリーンアップ処理"""
        logger.info("カスタムモード: クリーンアップを実行")
        return True


async def process_query_async(client, query):
    """クライアントタイプに応じて適切なクエリ処理を行う非同期ラッパー関数"""
    try:
        # 型チェック - CustomMCPClientとMCPClientどちらも対応
        if hasattr(client, "process_query"):
            return await client.process_query(query)
        else:
            return "エラー: 対応していないクライアントタイプです"
    except Exception as e:
        logger.error(f"process_query_asyncでエラー発生: {str(e)}")
        return f"エラーが発生しました: {str(e)}"
