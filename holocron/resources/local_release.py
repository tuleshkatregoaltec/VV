"""Local staging resource for Holocron source releases."""

from __future__ import annotations

import shutil
from pathlib import Path

from dagster import ConfigurableResource, get_dagster_logger


class LocalReleaseStorageResource(ConfigurableResource):
    root_dir: str

    def root_path(self) -> Path:
        path = Path(self.root_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def release_dir(self, dataset: str, release_id: str) -> Path:
        return self.root_path() / dataset / release_id

    def reset_release_dir(self, dataset: str, release_id: str) -> Path:
        path = self.release_dir(dataset, release_id)
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete_release_dir(self, dataset: str, release_id: str) -> bool:
        path = self.release_dir(dataset, release_id)
        if not path.exists():
            get_dagster_logger().info(f"Local release directory already absent: {path}")
            return False
        shutil.rmtree(path)
        get_dagster_logger().info(f"Deleted local release directory {path}")
        return True
