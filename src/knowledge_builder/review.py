"""内存审核核心：明确人工操作、保留原始候选、不自动确认关系端点。"""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from .extraction import fingerprint, validate_result
from .models import (
    Entity,
    EntityCandidate,
    Evidence,
    ExtractionResult,
    PaperInput,
    Relation,
    RelationCandidate,
    ReviewEvent,
    ReviewItem,
    ReviewSelection,
    ReviewStatus,
)

REVIEW_VERSION = "b-review/0.1-draft"


class ReviewSession:
    """一篇论文的一轮内存审核。不是 HTTP 会话，也不自带身份认证或文件保存。"""

    review_version = REVIEW_VERSION

    def __init__(self, paper: PaperInput, result: ExtractionResult):
        validate_result(paper, result)
        self._paper = deepcopy(paper)
        self._original = deepcopy(result)
        self._items: dict[str, ReviewItem] = {}
        self._history: list[ReviewEvent] = []
        for candidate in result.entities:
            self._items[candidate.candidate_id] = ReviewItem(
                candidate.candidate_id,
                candidate.entity,
                tuple(candidate.evidence),
                "pending",
            )
        for candidate in result.relations:
            self._items[candidate.candidate_id] = ReviewItem(
                candidate.candidate_id,
                Relation(candidate.source, candidate.kind, candidate.target),
                tuple(candidate.evidence),
                "pending",
            )

    @property
    def original(self) -> ExtractionResult:
        """给调用方副本，避免其修改抽取原始记录。"""
        return deepcopy(self._original)

    @property
    def history(self) -> tuple[ReviewEvent, ...]:
        return tuple(self._history)

    @property
    def items(self) -> tuple[ReviewItem, ...]:
        return tuple(self._items.values())

    @classmethod
    def replay(
        cls,
        paper: PaperInput,
        result: ExtractionResult,
        events: tuple[ReviewEvent, ...],
    ) -> "ReviewSession":
        """用同一套业务方法重放历史，验证前后快照及撤回联动，保留原时间。"""
        session = cls(paper, result)
        index = 0
        while index < len(events):
            event = events[index]
            if not isinstance(event, ReviewEvent):
                raise ValueError("Invalid review event")
            try:
                timestamp = datetime.fromisoformat(event.occurred_at)
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid event time") from exc
            if timestamp.utcoffset() != timedelta(0):
                raise ValueError("Event time must include UTC timezone")
            kwargs = {"reviewer": event.reviewer, "reason": event.reason}
            identifier = event.before.candidate_id
            if event.action in {"confirm", "reject", "reopen"}:
                getattr(session, event.action)(identifier, **kwargs)
            elif event.action == "correct":
                content = event.after.content
                session.correct(
                    identifier,
                    name=content.name if isinstance(content, Entity) else None,
                    evidence=event.after.evidence,
                    **kwargs,
                )
            else:
                raise ValueError("Unexpected event action or orphan dependency event")
            generated = session.history[index:]
            expected = events[index : index + len(generated)]
            if len(expected) != len(generated):
                raise ValueError("Missing dependent review events")
            for actual, saved in zip(generated, expected):
                if (
                    saved.occurred_at != event.occurred_at
                    or replace(actual, occurred_at=event.occurred_at) != saved
                ):
                    raise ValueError("Review event sequence or snapshots do not match")
            session._history[index:] = expected
            index += len(generated)
        return session

    def get(self, candidate_id: str) -> ReviewItem:
        try:
            return self._items[candidate_id]
        except KeyError as exc:
            raise ValueError("Unknown candidate ID") from exc

    def select(self, status: ReviewStatus) -> ReviewSelection:
        if status not in {"pending", "confirmed", "rejected"}:
            raise ValueError("Unknown review status")
        selected = [item for item in self._items.values() if item.status == status]
        return ReviewSelection(
            tuple(item for item in selected if isinstance(item.content, Entity)),
            tuple(item for item in selected if isinstance(item.content, Relation)),
        )

    def check_input(self, paper: PaperInput):
        """外部输入更新后必须另开审核，不能凭相同候选 ID 继承决定。"""
        if fingerprint(asdict(paper)) != self._original.input_fingerprint:
            raise ValueError("Input changed; create a new review session")

    def _validate(self, items: dict[str, ReviewItem]):
        # 复用候选校验，审核状态单独保存；不放宽抽取器只产出 pending 的约束。
        result = deepcopy(self._original)
        result.entities = [
            EntityCandidate(item.candidate_id, item.content, list(item.evidence))
            for item in items.values()
            if isinstance(item.content, Entity)
        ]
        result.relations = [
            RelationCandidate(
                item.candidate_id,
                item.content.source,
                item.content.kind,
                item.content.target,
                list(item.evidence),
            )
            for item in items.values()
            if isinstance(item.content, Relation)
        ]
        validate_result(self._paper, result)
        entity_status = {
            item.content.key: item.status
            for item in items.values()
            if isinstance(item.content, Entity)
        }
        for item in items.values():
            if isinstance(item.content, Relation) and item.status == "confirmed":
                if any(
                    entity_status[key] != "confirmed"
                    for key in (item.content.source, item.content.target)
                ):
                    raise ValueError(
                        "Confirm both endpoint entities before the relation"
                    )

    def _apply(self, updates, action, reviewer, reason):
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Reviewer name is required")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A review reason is required")
        proposed = dict(self._items)
        for item, _ in updates:
            proposed[item.candidate_id] = item
        self._validate(proposed)
        timestamp = datetime.now(timezone.utc).isoformat()
        events = [
            ReviewEvent(
                len(self._history) + index + 1,
                event_action or action,
                reviewer.strip(),
                reason.strip(),
                timestamp,
                self.get(item.candidate_id),
                item,
            )
            for index, (item, event_action) in enumerate(updates)
        ]
        # 上面任何检查失败都不会修改当前状态或操作记录。
        self._items = proposed
        self._history.extend(events)

    def _pending(self, candidate_id):
        item = self.get(candidate_id)
        if item.status != "pending":
            raise ValueError("Reopen a decided candidate before changing it")
        return item

    def confirm(self, candidate_id: str, *, reviewer: str, reason: str) -> ReviewItem:
        item = replace(self._pending(candidate_id), status="confirmed")
        self._apply([(item, None)], "confirm", reviewer, reason)
        return item

    def reject(self, candidate_id: str, *, reviewer: str, reason: str) -> ReviewItem:
        item = replace(self._pending(candidate_id), status="rejected")
        self._apply([(item, None)], "reject", reviewer, reason)
        return item

    def correct(
        self,
        candidate_id: str,
        *,
        reviewer: str,
        reason: str,
        name: str | None = None,
        evidence: tuple[Evidence, ...] | None = None,
    ) -> ReviewItem:
        """纠正名称或证据后仍待审核；不改变身份、类型或关系两端。"""
        before = self._pending(candidate_id)
        content = before.content
        if name is not None:
            if (
                not isinstance(content, Entity)
                or not isinstance(name, str)
                or not name.strip()
            ):
                raise ValueError("Only an entity may receive a nonempty display name")
            content = replace(content, name=name.strip())
        proofs = before.evidence if evidence is None else tuple(evidence)
        if not proofs or any(not isinstance(proof, Evidence) for proof in proofs):
            raise ValueError("Correction requires valid evidence objects")
        item = replace(before, content=content, evidence=proofs)
        if item == before:
            raise ValueError("Correction must change the candidate")
        self._apply([(item, None)], "correct", reviewer, reason)
        return item

    def reopen(self, candidate_id: str, *, reviewer: str, reason: str) -> ReviewItem:
        """撤回决定。实体重审时，其已确认关系同步退回待审并留下独立记录。"""
        before = self.get(candidate_id)
        if before.status == "pending":
            raise ValueError("Candidate is already pending")
        item = replace(before, status="pending")
        updates = [(item, None)]
        if isinstance(item.content, Entity):
            for dependent in self._items.values():
                if (
                    isinstance(dependent.content, Relation)
                    and dependent.status == "confirmed"
                    and item.content.key
                    in (dependent.content.source, dependent.content.target)
                ):
                    updates.append(
                        (replace(dependent, status="pending"), "reopen_dependency")
                    )
        self._apply(updates, "reopen", reviewer, reason)
        return item
