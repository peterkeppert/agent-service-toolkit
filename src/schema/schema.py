from typing import Any, Literal
from uuid import uuid4

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolCall,
    ToolMessage,
    message_to_dict,
    messages_from_dict,
)
from langchain_core.messages import (
    ChatMessage as LangchainChatMessage,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field


def convert_message_content_to_string(content: str | list[str | dict]) -> str:
    if isinstance(content, str):
        return content
    text: list[str] = []
    for content_item in content:
        if isinstance(content_item, str):
            text.append(content_item)
            continue
        if content_item["type"] == "text":
            text.append(content_item["text"])
    return "".join(text)


class UserInput(BaseModel):
    """Basic user input for the agent."""

    message: str = Field(
        description="User input to the agent.",
        examples=["What is the weather in Tokyo?"],
    )
    model: str = Field(
        description="LLM Model to use for the agent.",
        default="gpt-4o-mini",
        examples=["gpt-4o-mini", "llama-3.1-70b"],
    )
    thread_id: str | None = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )


class StreamInput(UserInput):
    """User input for streaming the agent's response."""

    stream_tokens: bool = Field(
        description="Whether to stream LLM tokens to the client.",
        default=True,
    )


class AgentResponse(BaseModel):
    """Response from the agent when called via /invoke."""

    message: dict[str, Any] = Field(
        description="Final response from the agent, as a serialized LangChain message.",
        examples=[
            {
                "message": {
                    "type": "ai",
                    "data": {"content": "The weather in Tokyo is 70 degrees.", "type": "ai"},
                }
            }
        ],
    )


class ChatMessage(BaseModel):
    """Message in a chat."""

    type: Literal["human", "ai", "tool", "custom"] = Field(
        description="Role of the message.",
        examples=["human", "ai", "tool", "custom"],
    )
    content: str = Field(
        description="Content of the message.",
        default="",
        examples=["Hello, world!"],
    )
    tool_calls: list[ToolCall] = Field(
        description="Tool calls in the message.",
        default=[],
    )
    tool_call_id: str | None = Field(
        description="Tool call that this message is responding to.",
        default=None,
        examples=["call_Jja7J89XsjrOLA5r!MEOW!SL"],
    )
    run_id: str | None = Field(
        description="Run ID of the message.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    original: dict[str, Any] = Field(
        description="Original LangChain message in serialized form.",
        default={},
    )
    custom_data: dict[str, Any] = Field(
        description="Custom message data.",
        default={},
    )

    @classmethod
    def from_langchain(cls, message: BaseMessage) -> "ChatMessage":
        """Create a ChatMessage from a LangChain message."""
        original = message_to_dict(message)
        match message:
            case HumanMessage():
                human_message = cls(
                    type="human",
                    content=convert_message_content_to_string(message.content),
                    original=original,
                )
                return human_message
            case AIMessage():
                ai_message = cls(
                    type="ai",
                    content=convert_message_content_to_string(message.content),
                    original=original,
                )
                if message.tool_calls:
                    ai_message.tool_calls = message.tool_calls
                return ai_message
            case ToolMessage():
                tool_message = cls(
                    type="tool",
                    content=convert_message_content_to_string(message.content),
                    tool_call_id=message.tool_call_id,
                    original=original,
                )
                return tool_message
            case LangchainChatMessage():
                if message.role == "custom":
                    custom_message = cls(
                        type="custom",
                        custom_data=message.content[0],
                    )
                    return custom_message
                else:
                    raise ValueError(f"Unsupported chat message role: {message.role}")
            case _:
                raise ValueError(f"Unsupported message type: {message.__class__.__name__}")

    def to_langchain(self) -> BaseMessage:
        """Convert the ChatMessage to a LangChain message."""
        if self.original:
            raw_original = messages_from_dict([self.original])[0]
            raw_original.content = self.content
            return raw_original
        match self.type:
            case "human":
                return HumanMessage(content=self.content)
            case _:
                raise NotImplementedError(f"Unsupported message type: {self.type}")

    def pretty_print(self) -> None:
        """Pretty print the ChatMessage."""
        lc_msg = self.to_langchain()
        lc_msg.pretty_print()


class Feedback(BaseModel):
    """Feedback for a run, to record to LangSmith."""

    run_id: str = Field(
        description="Run ID to record feedback for.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    key: str = Field(
        description="Feedback key.",
        examples=["human-feedback-stars"],
    )
    score: float = Field(
        description="Feedback score.",
        examples=[0.8],
    )
    kwargs: dict[str, Any] = Field(
        description="Additional feedback kwargs, passed to LangSmith.",
        default={},
        examples=[{"comment": "In-line human feedback"}],
    )


class Task:
    def __init__(self, task_name: str) -> None:
        self.name = task_name
        self.id = str(uuid4())
        self.state: Literal["new", "running", "complete"] = "new"
        self.result = None

    async def start(self, config: RunnableConfig, data: dict = {}) -> LangchainChatMessage:
        self.state = "running"
        task_message = LangchainChatMessage(
            content=[
                TaskMessageData(
                    name=self.name, run_id=self.id, state=self.state, data=data
                ).model_dump()
            ],
            role="custom",
        )
        await adispatch_custom_event(
            name=self.name,
            data=task_message,
            config=config,
        )
        return task_message

    async def write_data(self, config: RunnableConfig, data: dict) -> LangchainChatMessage:
        if self.state != "running":
            raise ValueError("Only running tasks can output data.")
        task_message = LangchainChatMessage(
            content=[
                TaskMessageData(
                    name=self.name, run_id=self.id, state=self.state, data=data
                ).model_dump()
            ],
            role="custom",
        )
        await adispatch_custom_event(
            name=self.name,
            data=task_message,
            config=config,
        )
        return task_message

    async def finish(
        self, result: Literal["success", "error"], config: RunnableConfig, data: dict = {}
    ) -> LangchainChatMessage:
        self.state = "complete"
        self.result = result
        task_message = LangchainChatMessage(
            content=[
                TaskMessageData(
                    name=self.name, run_id=self.id, state=self.state, result=self.result, data=data
                ).model_dump()
            ],
            role="custom",
        )
        await adispatch_custom_event(
            name=self.name,
            data=task_message,
            config=config,
        )
        return task_message


class TaskMessageData(BaseModel):
    name: str | None = Field(
        description="Name of the task.", default=None, examples=["Check input safety"]
    )
    run_id: str = Field(
        description="ID of the task run to pair state updates to.",
        default="",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    state: Literal["new", "running", "complete"] | None = Field(
        description="Current state of given task instance.",
        default=None,
        examples=["running"],
    )
    result: Literal["success", "error"] | None = Field(
        description="Result of given task instance.",
        default=None,
        examples=["running"],
    )
    data: dict[str, Any] = Field(
        description="Additional data generated by the task.",
        default={},
    )


class FeedbackResponse(BaseModel):
    status: Literal["success"] = "success"


class ChatHistoryInput(BaseModel):
    """Input for retrieving chat history."""

    thread_id: str = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )


class ChatHistory(BaseModel):
    messages: list[ChatMessage]
