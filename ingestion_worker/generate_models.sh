#!/bin/sh
# Regenerate models.py from core_api.openapi.yaml, which defines the payloads of every API
# this service calls or serves. Run it after changing that file.
set -e
cd "$(dirname "$0")"
uvx --from 'datamodel-code-generator[ruff]==0.84.0' datamodel-codegen \
    --input core_api.openapi.yaml \
    --output models.py \
    --input-file-type openapi \
    --output-model-type pydantic_v2.BaseModel \
    --target-python-version 3.12 \
    --enum-field-as-literal all \
    --use-type-alias \
    --use-standard-collections \
    --use-union-operator \
    --use-schema-description \
    --use-field-description \
    --field-constraints \
    --formatters ruff-check ruff-format \
    --custom-file-header "# Generated from core_api.openapi.yaml by generate_models.sh. Don't edit it by hand."
