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
    aliases: tuple[str, ...] = ()
    item_contract: JsonObjectContract | None = None


@dataclass(frozen=True, slots=True)
class JsonObjectContract:
    fields: tuple[JsonField, ...]
    minimum_present: int = 0

    def validate(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ContractValidationError("根节点必须是 JSON 对象")
        data = dict(cast(dict[str, object], value))
        errors: list[str] = []
        present = 0
        for field in self.fields:
            source_name = field.name
            if source_name not in data:
                source_name = next(
                    (alias for alias in field.aliases if alias in data),
                    "",
                )
            if not source_name:
                if field.required:
                    errors.append(f"缺少字段 {field.name}")
                continue
            present += 1
            field_value = data[source_name]
            data[field.name] = field_value
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
                continue
            if field.item_contract is not None and isinstance(field_value, list):
                normalized_items: list[dict[str, object]] = []
                for index, item in enumerate(field_value):
                    try:
                        normalized_items.append(field.item_contract.validate(item))
                    except ContractValidationError as error:
                        errors.append(f"{field.name}[{index}]：{error}")
                data[field.name] = normalized_items
        if present < self.minimum_present:
            errors.append("没有发现任何合同字段")
        if errors:
            raise ContractValidationError("；".join(errors))
        return data

    def schema_hint(self) -> str:
        descriptions: list[str] = []
        for field in self.fields:
            expected_types = (
                field.expected_type
                if isinstance(field.expected_type, tuple)
                else (field.expected_type,)
            )
            type_names = " 或 ".join(item.__name__ for item in expected_types)
            requirement = "必填" if field.required else "可省略"
            description = f"{field.name}（{type_names}，{requirement}）"
            if field.item_contract is not None:
                description += f"，列表项：{field.item_contract.schema_hint()}"
            descriptions.append(description)
        return "；".join(descriptions)


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
                f"{first_error}\n合同字段：{contract.schema_hint()}",
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
