"""Chat about the listings: OpenAI decides which MCP tools to call, we run them and return the answer.

The loop:
1. Ask the MCP server which tools it has, and hand them to OpenAI as functions.
2. Send the conversation. OpenAI either answers, or asks for tool calls.
3. Run each tool call on the MCP server and send the results back. Repeat until it answers.
"""

import json
import os

from langfuse import observe
from langfuse.openai import AsyncOpenAI  # traced drop-in for openai.AsyncOpenAI
from mcp import Client
from pydantic import BaseModel, Field

from mcp_server import mcp

CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-5.4-mini")
MAX_TOOL_ROUNDS = 5

INSTRUCTIONS = """
You help the user understand Berlin rental listings collected from their ImmoScout24 search alerts.
Prices are monthly cold rent in EUR. Sales, listings without a price, and duplicates are already removed.

- Use the tools for every number and every listing. Never guess or invent data.
- Every filter is optional. Call the tools right away, without filters for all of Berlin.
  Do not ask the user for filters they did not mention.
- Keep the order the tools return. Tables are already sorted.
- When you use filters, say which ones, for example "2 to 2.5 rooms in Neukölln".
- Name listings with their rent, size, district, and link, as a markdown link.
- Keep answers short. Use a small table or list when it helps.
- If the tools cannot answer the question, say so plainly.
- Reply in the language the user writes in.
"""


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ToolCall(BaseModel):
    name: str
    arguments: dict


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCall]


def as_openai_tool(tool) -> dict:
    """An MCP tool description, in the format OpenAI expects for a function."""
    return {"type": "function", "name": tool.name, "description": tool.description or "", "parameters": tool.input_schema}


def tool_output(result) -> str:
    """The text an MCP tool returned. Our tools return JSON as text."""
    text = "\n".join(block.text for block in result.content if block.type == "text")
    return f"Error: {text}" if result.is_error else text


@observe(name="chat")
async def chat(messages: list[ChatMessage]) -> ChatResponse:
    # Connect to our own MCP server in-process. A URL instead, for example
    # Client("https://.../mcp/"), would use the same tools over HTTP.
    async with Client(mcp) as client:
        tools = [as_openai_tool(tool) for tool in (await client.list_tools()).tools]
        conversation = [message.model_dump() for message in messages]
        used = []
        results = {}  # the same call twice in one answer runs only once

        async with AsyncOpenAI() as openai:
            for _ in range(MAX_TOOL_ROUNDS):
                response = await openai.responses.create(
                    model=CHAT_MODEL,
                    instructions=INSTRUCTIONS,
                    input=conversation,
                    tools=tools,
                    reasoning={"effort": "low"},
                )
                calls = [item for item in response.output if item.type == "function_call"]
                if not calls:
                    return ChatResponse(answer=response.output_text, tool_calls=used)

                # Keep the model's tool requests in the conversation, then add each result
                conversation += response.output
                for call in calls:
                    arguments = {k: v for k, v in json.loads(call.arguments or "{}").items() if v is not None}
                    key = (call.name, json.dumps(arguments, sort_keys=True))
                    if key not in results:
                        results[key] = tool_output(await client.call_tool(call.name, arguments))
                        used.append(ToolCall(name=call.name, arguments=arguments))
                    conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": results[key]})

    return ChatResponse(answer="Sorry, that needed too many steps. Try a narrower question.", tool_calls=used)
