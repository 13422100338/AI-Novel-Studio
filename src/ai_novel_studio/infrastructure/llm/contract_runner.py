from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol, cast

from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMResponse,
    TaskPurpose,
)


class CompletionGateway(Protocol):
    def complete(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse: ...


class ContractValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JsonField:
    name: str
    expected_type: type[object] | tuple[type[object], ...]
    required: bool = True


@dataclass(frozen=True, slots=True)
class JsonObjectContract:
    fields: tuple[JsonField, ...]

    def validate(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ContractValidationError("根节点必须是 JSON 对象")
        data = cast(dict[str, object], value)
        errors: list[str] = []
        for field in self.fields:
            if field.name not in data:
                if field.required:
                    errors.append(f"缺少字段 {field.name}")
                continue
            field_value = data[field.name]
            valid = isinstance(field_value, field.expected_type)
            expected_types = (
                field.expected_type
                if isinstance(field.expected_type, tuple)
                else (field.expected_type,)
            )
            if int in expected_types and isinstance(field_value, bool):
                valid = False
            if not valid:
                expected_name = " 或 ".join(
                    expected_type.__name__ for expected_type in expected_types
                )
                errors.append(
                    f"字段 {field.name} 必须是 {expected_name}"
                )
        if errors:
            raise ContractValidationError("；".join(errors))
        return data


class LLMContractRunner:
    _FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)

    def __init__(self, gateway: CompletionGateway) -> None:
        self.gateway = gateway

    def run_json(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        contract: JsonObjectContract,
    ) -> dict[str, object]:
        response = self.gateway.complete(
            purpose,
            messages,
            output_token_limit,
            temperature=0.2,
            json_mode=True,
        )
        try:
            return self._parse_and_validate(response.text, contract)
        except ContractValidationError as first_error:
            correction = LLMMessage(
                "user",
                "上一次输出不符合合同。只返回修正后的 JSON，不要解释。具体错误："
                f"{first_error}",
            )
            corrected_messages = messages
            if response.text.strip():
                corrected_messages = (
                    *corrected_messages,
                    LLMMessage("assistant", response.text),
                )
            corrected_messages = (*corrected_messages, correction)
            corrected = self.gateway.complete(
                purpose,
                corrected_messages,
                output_token_limit,
                temperature=0.1,
                json_mode=True,
            )
            try:
                return self._parse_and_validate(corrected.text, contract)
            except ContractValidationError as second_error:
                raise ContractValidationError(
                    f"模型结构化输出连续两次不符合合同：{second_error}"
                ) from second_error

    @classmethod
    def _parse_and_validate(
        cls,
        text: str,
        contract: JsonObjectContract,
    ) -> dict[str, object]:
        candidate = text.strip()
        match = cls._FENCE.match(candidate)
        if match:
            candidate = match.group(1)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as error:
            raise ContractValidationError("输出不是有效 JSON") from error
        return contract.validate(value)
