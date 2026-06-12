"""Drop-in OpenAI client wrapper with IRIS governance on every API call."""

from __future__ import annotations

from typing import Any, List, Optional

from iris_core.dlp import DLPScanner
from iris_core.dlp.enforcement import (
    enforce_prompt_dlp,
    extract_openai_response_text,
    handle_response_dlp,
)
from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport

from iris_openai._governance import (
    current_environment,
    enforce_result,
    evaluate_openai_call,
    load_passport_policy,
)
from iris_openai.tool_guard import guard_openai_tools


def _lazy_openai():
    import openai

    return openai


def _extract_tool_names_from_messages(messages: List[Any]) -> List[str]:
    names: List[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") or {}
            name = fn.get("name")
            if name:
                names.append(name)
    return names


def _extract_prompt_text(kwargs: dict) -> str:
    parts: List[str] = []
    for msg in kwargs.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if text:
                        parts.append(str(text))
    return "\n".join(parts)


def _extract_tool_names_from_kwargs(kwargs: dict) -> List[str]:
    names: List[str] = []
    tools = kwargs.get("tools") or kwargs.get("functions") or []
    for tool in tools:
        if isinstance(tool, dict):
            if tool.get("type") == "function":
                fn = tool.get("function") or {}
                if fn.get("name"):
                    names.append(fn["name"])
            elif tool.get("name"):
                names.append(tool["name"])
        elif hasattr(tool, "name"):
            names.append(getattr(tool, "name"))
    names.extend(_extract_tool_names_from_messages(kwargs.get("messages") or []))
    return list(dict.fromkeys(names))


class _IrisOpenAIClientBase:
    _passport: AgentPassport
    _engine: CedarEngine
    _vault: EvidenceVault
    _dlp: DLPScanner
    _azure_endpoint: Optional[str] = None


class _GovernedCompletionsBase:
    def __init__(self, parent: _IrisOpenAIClientBase, completions_resource: Any):
        self._parent = parent
        self._completions = completions_resource

    @property
    def _passport(self) -> AgentPassport:
        return self._parent._passport

    @property
    def _engine(self) -> CedarEngine:
        return self._parent._engine

    @property
    def _vault(self) -> EvidenceVault:
        return self._parent._vault

    def _govern_kwargs(self, kwargs: dict) -> None:
        env = current_environment()
        prompt = _extract_prompt_text(kwargs)
        dlp_result = enforce_prompt_dlp(
            self._parent._dlp,
            self._vault,
            self._passport,
            env,
            prompt,
            resource="openai-api",
        )
        if kwargs.get("tools"):
            kwargs["tools"] = guard_openai_tools(kwargs["tools"], self._passport, env)
        tool_names = _extract_tool_names_from_kwargs(kwargs)
        result = evaluate_openai_call(
            self._engine,
            self._vault,
            self._passport,
            env,
            operation="chat.completions",
            model=kwargs.get("model"),
            tool_names=tool_names,
            azure_endpoint=getattr(self._parent, "_azure_endpoint", None),
            dlp_prompt_findings=dlp_result.findings,
        )
        enforce_result(result, env)

    def _scan_response(self, response: Any) -> Any:
        env = current_environment()
        response_text = extract_openai_response_text(response)
        blocked, _ = handle_response_dlp(
            self._parent._dlp,
            self._vault,
            self._passport,
            env,
            response_text,
            response,
            resource="openai-api",
        )
        return blocked

    def create(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        response = self._completions.create(**kwargs)
        return self._scan_response(response)

    def stream(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        return self._completions.stream(**kwargs)


class _GovernedCompletionsAsyncBase(_GovernedCompletionsBase):
    async def create(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        response = await self._completions.create(**kwargs)
        return self._scan_response(response)

    async def stream(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        return await self._completions.stream(**kwargs)


class IrisChatCompletionsResource(_GovernedCompletionsBase):
    pass


class IrisChatCompletionsResourceAsync(_GovernedCompletionsAsyncBase):
    pass


class IrisChatResource:
    def __init__(self, parent: _IrisOpenAIClientBase, chat_resource: Any):
        self._parent = parent
        self._chat = chat_resource
        self._completions_resource = IrisChatCompletionsResource(
            parent, self._chat.completions
        )

    @property
    def completions(self) -> IrisChatCompletionsResource:
        return self._completions_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class IrisChatResourceAsync:
    def __init__(self, parent: _IrisOpenAIClientBase, chat_resource: Any):
        self._parent = parent
        self._chat = chat_resource
        self._completions_resource = IrisChatCompletionsResourceAsync(
            parent, self._chat.completions
        )

    @property
    def completions(self) -> IrisChatCompletionsResourceAsync:
        return self._completions_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class _GovernedEmbeddingsBase:
    def __init__(self, parent: _IrisOpenAIClientBase, embeddings_resource: Any):
        self._parent = parent
        self._embeddings = embeddings_resource

    def _govern_kwargs(self, kwargs: dict) -> None:
        env = current_environment()
        result = evaluate_openai_call(
            self._parent._engine,
            self._parent._vault,
            self._parent._passport,
            env,
            operation="embeddings",
            model=kwargs.get("model"),
            data_classification=self._parent._passport.data_classification.value,
            azure_endpoint=getattr(self._parent, "_azure_endpoint", None),
        )
        enforce_result(result, env)

    def create(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        return self._embeddings.create(**kwargs)


class _GovernedEmbeddingsAsyncBase(_GovernedEmbeddingsBase):
    async def create(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        return await self._embeddings.create(**kwargs)


class IrisEmbeddingsResource(_GovernedEmbeddingsBase):
    pass


class IrisEmbeddingsResourceAsync(_GovernedEmbeddingsAsyncBase):
    pass


class IrisOpenAI(_IrisOpenAIClientBase):
    """
    Drop-in replacement for openai.OpenAI() with IRIS governance.

    Pass an AgentPassport and the same kwargs you would give OpenAI().
    All attributes not defined here are proxied to the underlying client.
    """

    def __init__(self, passport: AgentPassport, **openai_kwargs: Any):
        from iris_core.dev_trust import print_dev_trust_message

        print_dev_trust_message()
        openai = _lazy_openai()
        self._passport = passport
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        load_passport_policy(self._engine, passport)
        self._client = openai.OpenAI(**openai_kwargs)
        self._chat_resource = IrisChatResource(self, self._client.chat)
        self._embeddings_resource = IrisEmbeddingsResource(self, self._client.embeddings)

    @property
    def chat(self) -> IrisChatResource:
        return self._chat_resource

    @property
    def embeddings(self) -> IrisEmbeddingsResource:
        return self._embeddings_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class IrisOpenAIAsync(_IrisOpenAIClientBase):
    """Async drop-in replacement for openai.AsyncOpenAI()."""

    def __init__(self, passport: AgentPassport, **openai_kwargs: Any):
        openai = _lazy_openai()
        self._passport = passport
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        load_passport_policy(self._engine, passport)
        self._client = openai.AsyncOpenAI(**openai_kwargs)
        self._chat_resource = IrisChatResourceAsync(self, self._client.chat)
        self._embeddings_resource = IrisEmbeddingsResourceAsync(
            self, self._client.embeddings
        )

    @property
    def chat(self) -> IrisChatResourceAsync:
        return self._chat_resource

    @property
    def embeddings(self) -> IrisEmbeddingsResourceAsync:
        return self._embeddings_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class IrisAzureOpenAI(IrisOpenAI):
    """Drop-in replacement for openai.AzureOpenAI() with Azure region checks."""

    def __init__(self, passport: AgentPassport, **openai_kwargs: Any):
        self._azure_endpoint = openai_kwargs.get("azure_endpoint")
        super().__init__(passport, **openai_kwargs)


class IrisAzureOpenAIAsync(IrisOpenAIAsync):
    """Async Azure OpenAI client with IRIS governance."""

    def __init__(self, passport: AgentPassport, **openai_kwargs: Any):
        self._azure_endpoint = openai_kwargs.get("azure_endpoint")
        super().__init__(passport, **openai_kwargs)
