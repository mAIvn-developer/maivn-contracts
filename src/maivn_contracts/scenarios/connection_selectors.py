"""Typed external event selectors and provider-field matching semantics."""

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

PresetIdentifier: TypeAlias = Annotated[
    StrictStr, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$')
]


class _ClosedSelector(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class FormConnectionSelector(_ClosedSelector):
    """Exact form identity inside a shared signed connection."""

    kind: Literal['form']
    form_id: PresetIdentifier


class LocalFileConnectionSelector(_ClosedSelector):
    """Exact local watcher identity, independent of the user filter."""

    kind: Literal['local_file']
    watch_id: PresetIdentifier


class GitHubConnectionSelector(_ClosedSelector):
    """Provider-specific repository and event-family predicates."""

    kind: Literal['github']
    repository: StrictStr | None = Field(
        default=None, min_length=3, max_length=200, pattern=r'^[^/\s]+/[^/\s]+$'
    )
    branch: StrictStr | None = Field(default=None, min_length=1, max_length=255)
    workflow: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    conclusion: (
        Literal[
            'success',
            'failure',
            'cancelled',
            'timed_out',
            'neutral',
            'skipped',
            'action_required',
            'stale',
            'startup_failure',
        ]
        | None
    ) = None
    merged: StrictBool | None = None


ConnectionEventSelector: TypeAlias = Annotated[
    FormConnectionSelector | LocalFileConnectionSelector | GitHubConnectionSelector,
    Field(discriminator='kind'),
]


def selector_supports_event(selector: ConnectionEventSelector, event_type: str) -> bool:
    """Reject fields whose provider event family cannot supply their meaning."""
    if isinstance(selector, FormConnectionSelector):
        return event_type == 'form.submitted'
    if isinstance(selector, LocalFileConnectionSelector):
        return event_type in ('file.created', 'file.modified')
    is_pr = event_type.startswith('pull_request.') and len(event_type) > len('pull_request.')
    is_workflow = event_type == 'workflow_run.completed'
    if not (
        is_pr
        or is_workflow
        or event_type == 'push'
        or (event_type.startswith('issues.') and len(event_type) > len('issues.'))
    ):
        return False
    if selector.branch is not None and not (is_pr or is_workflow or event_type == 'push'):
        return False
    if (selector.workflow is not None or selector.conclusion is not None) and not is_workflow:
        return False
    return selector.merged is None or is_pr


def _at(payload: object, *path: str) -> object:
    value: object = payload
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = cast('Mapping[str, object]', value).get(part)
    return value


def matches_connection_selector(
    selector: ConnectionEventSelector | None, event_type: str, payload: Mapping[str, object]
) -> bool:
    """Match exact typed fields; missing/null provider values never satisfy a predicate.

    Callers must still apply source event equality and the independent user JSONPath filter.
    A missing selector preserves the existing matching behavior.
    """
    if selector is None:
        return True
    if not selector_supports_event(selector, event_type):
        return False
    if isinstance(selector, FormConnectionSelector):
        return payload.get('form_id') == selector.form_id
    if isinstance(selector, LocalFileConnectionSelector):
        return payload.get('watch_id') == selector.watch_id
    return _matches_github(selector, event_type, payload)


def _matches_github(
    selector: GitHubConnectionSelector, event_type: str, payload: Mapping[str, object]
) -> bool:
    expected: list[tuple[object, object]] = []
    if selector.repository is not None:
        expected.append((_at(payload, 'repository', 'full_name'), selector.repository))
    if selector.branch is not None:
        if event_type == 'push':
            expected.append((payload.get('ref'), f'refs/heads/{selector.branch}'))
        elif event_type.startswith('pull_request.'):
            expected.append((_at(payload, 'pull_request', 'base', 'ref'), selector.branch))
        else:
            expected.append((_at(payload, 'workflow_run', 'head_branch'), selector.branch))
    if selector.workflow is not None:
        expected.append((_at(payload, 'workflow_run', 'name'), selector.workflow))
    if selector.conclusion is not None:
        expected.append((_at(payload, 'workflow_run', 'conclusion'), selector.conclusion))
    if selector.merged is not None:
        # Python bool/int equality must not accept malformed provider JSON 0 or 1.
        actual = _at(payload, 'pull_request', 'merged')
        if not isinstance(actual, bool) or actual is not selector.merged:
            return False
    return all(isinstance(actual, str) and actual == wanted for actual, wanted in expected)
