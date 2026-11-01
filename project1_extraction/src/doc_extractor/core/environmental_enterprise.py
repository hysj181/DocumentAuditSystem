from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from doc_extractor.core.environmental_models import (
    ENTERPRISE_NAME_MATCHED,
    ENTERPRISE_NAME_ONLY,
    ENTERPRISE_UNCLEAR,
    ENTERPRISE_VERIFIED,
    EnterpriseGroup,
)
from doc_extractor.core.models import DocumentResult

USCC_RE = re.compile(
    r"(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Z])",
    re.IGNORECASE,
)
LABELED_NAME_RE = re.compile(
    r"(?:企业名称|单位名称|公司名称|排污单位名称|排污单位|受检单位|被审核单位)"
    r"\s*[:：]\s*(?P<name>[^\n，,；;。]{2,80})"
)
COMPANY_NAME_RE = re.compile(
    r"(?:^|[:：\s，,；;。])"
    r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,60}?"
    r"(?:有限责任公司|股份有限公司|有限公司|集团|公司|厂|中心))"
)
NON_ENTERPRISE_FACTORY_RE = re.compile(
    r"^(?:污水|废水|垃圾|自来水|净水|污泥)处理?厂$"
)


@dataclass
class DocumentIdentity:
    document_id: str
    source_file: str
    enterprise_name: str | None
    unified_social_credit_code: str | None
    identity_status: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    return re.sub(r"\s+", "", normalized).strip("，,；;。:：")


def _normalize_code(code: str) -> str:
    return re.sub(r"\s+", "", code).upper()


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _is_plausible_company(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if NON_ENTERPRISE_FACTORY_RE.fullmatch(name):
        return False
    return bool(
        re.search(
            r"(?:有限责任公司|股份有限公司|有限公司|集团|公司|厂|中心)$",
            name,
        )
    )


def _document_text(document: DocumentResult) -> str:
    parts: list[str] = []
    for record in document.records:
        if record.text.strip():
            parts.append(record.text.strip())
    if not parts:
        return document.raw_text()
    return "\n".join(parts)


class EnterpriseResolver:
    def resolve(
        self,
        documents: list[DocumentResult],
    ) -> tuple[list[EnterpriseGroup], dict[str, EnterpriseGroup]]:
        identities: list[DocumentIdentity] = []
        documents_by_id = {document.document_id: document for document in documents}

        for document in documents:
            if document.error:
                continue
            identities.append(self._extract_identity(document))

        code_groups: dict[str, EnterpriseGroup] = {}
        name_only_documents: list[DocumentIdentity] = []
        unclear_documents: list[DocumentIdentity] = []
        group_for_document: dict[str, EnterpriseGroup] = {}

        for identity in identities:
            if identity.identity_status == ENTERPRISE_UNCLEAR:
                unclear_documents.append(identity)
                continue
            if identity.unified_social_credit_code:
                code = identity.unified_social_credit_code
                group = code_groups.get(code)
                if group is None:
                    group = EnterpriseGroup(
                        enterprise_id=_stable_id("ent_code", code),
                        enterprise_name=identity.enterprise_name,
                        unified_social_credit_code=code,
                        identity_status=ENTERPRISE_VERIFIED,
                    )
                    code_groups[code] = group
                elif identity.enterprise_name and group.enterprise_name is None:
                    group.enterprise_name = identity.enterprise_name
                elif (
                    identity.enterprise_name
                    and group.enterprise_name
                    and identity.enterprise_name != group.enterprise_name
                ):
                    group.warnings.append(
                        "同一统一社会信用代码下出现不同企业名称，请人工核实。"
                    )
                self._add_document(group, documents_by_id[identity.document_id], identity)
                group_for_document[identity.document_id] = group
                continue
            name_only_documents.append(identity)

        name_groups: dict[str, EnterpriseGroup] = {}
        for identity in name_only_documents:
            if not identity.enterprise_name:
                unclear_documents.append(identity)
                continue
            normalized_name = _normalize_name(identity.enterprise_name)
            matching_code_groups = [
                group
                for group in code_groups.values()
                if group.enterprise_name
                and _normalize_name(group.enterprise_name) == normalized_name
            ]

            if len(matching_code_groups) == 1:
                group = matching_code_groups[0]
                group.identity_status = ENTERPRISE_NAME_MATCHED
                group.warnings.append(
                    "部分文件缺少统一社会信用代码，已按企业名称归并，建议人工核实。"
                )
            elif len(matching_code_groups) > 1:
                group = name_groups.get(normalized_name)
                if group is None:
                    group = EnterpriseGroup(
                        enterprise_id=_stable_id("ent_name", normalized_name),
                        enterprise_name=identity.enterprise_name,
                        unified_social_credit_code=None,
                        identity_status=ENTERPRISE_NAME_ONLY,
                    )
                    name_groups[normalized_name] = group
                group.warnings.append(
                    "存在多个同名但统一社会信用代码不同的企业，未自动合并。"
                )
            else:
                group = name_groups.get(normalized_name)
                if group is None:
                    group = EnterpriseGroup(
                        enterprise_id=_stable_id("ent_name", normalized_name),
                        enterprise_name=identity.enterprise_name,
                        unified_social_credit_code=None,
                        identity_status=ENTERPRISE_NAME_ONLY,
                    )
                    name_groups[normalized_name] = group
                    group.warnings.append(
                        "未找到统一社会信用代码，仅按企业名称归并，建议人工核实。"
                    )
            self._add_document(group, documents_by_id[identity.document_id], identity)
            group_for_document[identity.document_id] = group

        for identity in unclear_documents:
            group = EnterpriseGroup(
                enterprise_id=f"ent_unknown_{identity.document_id[:10]}",
                enterprise_name=None,
                unified_social_credit_code=None,
                identity_status=ENTERPRISE_UNCLEAR,
                warnings=["企业身份不明确，已按独立企业处理，未自动合并。"],
            )
            self._add_document(group, documents_by_id[identity.document_id], identity)
            group_for_document[identity.document_id] = group
            identity.warnings.append("企业身份不明确，已按独立企业处理，未自动合并。")

        groups = list(code_groups.values()) + list(name_groups.values())
        for group in groups:
            group.warnings = list(dict.fromkeys(group.warnings))

        unresolved = [
            group
            for group in group_for_document.values()
            if group.identity_status == ENTERPRISE_UNCLEAR
        ]
        groups.extend(unresolved)

        groups.sort(key=lambda group: (group.enterprise_name is None, group.display_name))
        return groups, group_for_document

    def _extract_identity(self, document: DocumentResult) -> DocumentIdentity:
        text = _document_text(document)
        uscc_candidates = list(
            dict.fromkeys(_normalize_code(match.group(0)) for match in USCC_RE.finditer(text))
        )
        labeled_names = list(
            dict.fromkeys(
                _normalize_name(match.group("name"))
                for match in LABELED_NAME_RE.finditer(text)
                if _normalize_name(match.group("name"))
            )
        )
        company_names = list(
            dict.fromkeys(
                _normalize_name(match.group("name"))
                for match in COMPANY_NAME_RE.finditer(text)
                if _is_plausible_company(_normalize_name(match.group("name")))
            )
        )
        names = labeled_names or company_names
        warnings: list[str] = []

        if len(uscc_candidates) > 1:
            warnings.append("检测到多个统一社会信用代码，企业身份不明确。")
            return DocumentIdentity(
                document_id=document.document_id,
                source_file=document.source_file,
                enterprise_name=None,
                unified_social_credit_code=None,
                identity_status=ENTERPRISE_UNCLEAR,
                warnings=warnings,
                metadata={
                    "uscc_candidates": uscc_candidates,
                    "name_candidates": names,
                },
            )

        if len(names) > 1:
            warnings.append("检测到多个企业名称，企业身份不明确，未自动合并。")
            return DocumentIdentity(
                document_id=document.document_id,
                source_file=document.source_file,
                enterprise_name=None,
                unified_social_credit_code=uscc_candidates[0] if uscc_candidates else None,
                identity_status=ENTERPRISE_UNCLEAR,
                warnings=warnings,
                metadata={
                    "uscc_candidates": uscc_candidates,
                    "name_candidates": names,
                },
            )

        enterprise_name = names[0] if names else None
        if uscc_candidates:
            identity_status = ENTERPRISE_VERIFIED
        elif enterprise_name:
            identity_status = ENTERPRISE_NAME_ONLY
        else:
            identity_status = ENTERPRISE_UNCLEAR
            warnings.append("未识别到企业名称或统一社会信用代码。")

        return DocumentIdentity(
            document_id=document.document_id,
            source_file=document.source_file,
            enterprise_name=enterprise_name,
            unified_social_credit_code=uscc_candidates[0] if uscc_candidates else None,
            identity_status=identity_status,
            warnings=warnings,
            metadata={
                "uscc_candidates": uscc_candidates,
                "labeled_names": labeled_names,
                "company_names": company_names,
                "text_excerpt": text[:500],
            },
        )

    @staticmethod
    def _add_document(
        group: EnterpriseGroup,
        document: DocumentResult,
        identity: DocumentIdentity,
    ) -> None:
        if document.document_id not in group.document_ids:
            group.document_ids.append(document.document_id)
        if document.source_file not in group.source_files:
            group.source_files.append(document.source_file)
        group.warnings.extend(identity.warnings)
        if group.enterprise_name is None and identity.enterprise_name:
            group.enterprise_name = identity.enterprise_name


def resolve_enterprises(
    documents: list[DocumentResult],
) -> tuple[list[EnterpriseGroup], dict[str, EnterpriseGroup]]:
    return EnterpriseResolver().resolve(documents)
