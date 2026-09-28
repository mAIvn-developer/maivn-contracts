"""Generate attachment action schemas with the same action constraints as Python."""

from __future__ import annotations

from typing import Any

from maivn_contracts.artifacts.attachment_resolution import PrivateArtifactResolveRequest


def private_artifact_resolve_request_schema() -> dict[str, Any]:
    """Materialize the public request and its operation-specific field requirements."""
    schema = PrivateArtifactResolveRequest.model_json_schema()
    schema['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
    schema['$id'] = (
        'https://schemas.maivn.dev/artifacts/private_artifact_resolve_request.schema.json'
    )
    # Reuse the canonical wire reference, whose schema includes kind/label,
    # revision and deletion invariants not expressed by Pydantic field types.
    schema['properties']['artifact_ref'] = {
        '$ref': 'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json#/$defs/privateArtifactRef'
    }
    schema['$defs'] = {'VaultDeletionScope': schema['$defs']['VaultDeletionScope']}
    action_fields = {
        'retrieve_session': 'client_proof_digest',
        'redacted_export': 'export_filename',
        'delete': 'deletion_scope',
    }
    required_types = {
        'client_proof_digest': {'type': 'string'},
        'export_filename': {'type': 'string'},
        'deletion_scope': {'$ref': '#/$defs/VaultDeletionScope'},
    }
    schema['oneOf'] = [
        {
            'required': [field] + ([] if operation == 'retrieve_session' else ['operation']),
            'properties': {
                'operation': {'const': operation},
                **(
                    {}
                    if operation == 'retrieve_session'
                    else {
                        'retrieval_part': {'const': 'private_original'},
                    }
                ),
                **{
                    candidate: required_types[candidate] if candidate == field else {'type': 'null'}
                    for candidate in action_fields.values()
                },
            },
        }
        for operation, field in action_fields.items()
    ]
    return schema
