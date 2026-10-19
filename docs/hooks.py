"""Publish each service's OpenAPI files with the site, so the Swagger pages can load them.

The specs stay where their services keep them; this copies them in at build time.
"""

from pathlib import Path

from mkdocs.structure.files import File

REPO = Path(__file__).resolve().parent.parent

# Published path (under openapi/) -> file in the repo. Specs that $ref each other keep
# their file names and share a folder, so the relative refs still resolve.
SPECS = {
    "web_app/webapp_api.yaml": "web_app/contracts/webapp_api.yaml",
    "tester/tester.yaml": "tester/openapi/tester.yaml",
    "ingestion_worker/openapi.yaml": "ingestion_worker/openapi.yaml",
    "ingestion_worker/core_api.openapi.yaml": "ingestion_worker/core_api.openapi.yaml",
    "notification_service/openapi.yaml": "notification_service/openapi.yaml",
    "notification_service/core_api.openapi.yaml": "notification_service/core_api.openapi.yaml",
}


def on_files(files, config):
    for published, source in SPECS.items():
        files.append(
            File.generated(config, f"openapi/{published}", abs_src_path=str(REPO / source))
        )
    return files
