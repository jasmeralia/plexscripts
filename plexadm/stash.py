from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

PAGE_SIZE = 200

_FIND_SCENES = """
query FindScenes($page: Int!, $per_page: Int!) {
  findScenes(filter: { page: $page, per_page: $per_page }) {
    count
    scenes {
      id
      title
      rating100
      director
      files { path }
      studio { id name }
      performers { id name }
      tags { id name }
    }
  }
}
"""

_FIND_PERFORMER = """
query FindPerformer($name: String!) {
  findPerformers(
    performer_filter: { name: { value: $name, modifier: EQUALS } }
    filter: { per_page: 1 }
  ) { performers { id } }
}
"""

_CREATE_PERFORMER = """
mutation CreatePerformer($name: String!) {
  performerCreate(input: { name: $name }) { id }
}
"""

_FIND_STUDIO = """
query FindStudio($name: String!) {
  findStudios(
    studio_filter: { name: { value: $name, modifier: EQUALS } }
    filter: { per_page: 1 }
  ) { studios { id } }
}
"""

_CREATE_STUDIO = """
mutation CreateStudio($name: String!) {
  studioCreate(input: { name: $name }) { id }
}
"""

_FIND_TAG = """
query FindTag($name: String!) {
  findTags(
    tag_filter: { name: { value: $name, modifier: EQUALS } }
    filter: { per_page: 1 }
  ) { tags { id } }
}
"""

_CREATE_TAG = """
mutation CreateTag($name: String!) {
  tagCreate(input: { name: $name }) { id }
}
"""

_UPDATE_SCENE = """
mutation UpdateScene($input: SceneUpdateInput!) {
  sceneUpdate(input: $input) { id }
}
"""

_MERGE_SCENES = """
mutation MergeScenes($input: SceneMergeInput!) {
  sceneMerge(input: $input) { id }
}
"""

_RESET_PLAY_COUNT = """
mutation ResetPlayCount($id: ID!) {
  sceneResetPlayCount(id: $id)
}
"""

_ADD_PLAY = """
mutation AddPlay($id: ID!, $times: [Timestamp!]) {
  sceneAddPlay(id: $id, times: $times) { count }
}
"""

_METADATA_SCAN = """
mutation MetadataScan($input: ScanMetadataInput!) {
  metadataScan(input: $input)
}
"""

_FIND_JOB = """
query FindJob($id: ID!) {
  findJob(input: {id: $id}) { id status error }
}
"""

_FAILED_JOB_STATUSES = {"CANCELLED", "FAILED"}


class StashClient:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/") + "/graphql"
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        self._performer_cache: dict[str, str] = {}
        self._studio_cache: dict[str, str] = {}
        self._tag_cache: dict[str, str] = {}

    def _gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self._session.post(self.endpoint, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if "errors" in result:
            raise RuntimeError(f"GraphQL errors: {result['errors']}")
        return result["data"]  # type: ignore[return-value]

    def all_scenes(self) -> dict[str, dict[str, Any]]:
        """Return a path -> scene dict for every scene in Stash."""
        index: dict[str, dict[str, Any]] = {}
        seen_ids: set[str] = set()
        page = 1
        while True:
            data = self._gql(_FIND_SCENES, {"page": page, "per_page": PAGE_SIZE})
            result = data["findScenes"]
            total = result["count"]
            scenes = result["scenes"]
            if not scenes:
                break
            for scene in scenes:
                seen_ids.add(scene["id"])
                for f in scene.get("files") or []:
                    index[f["path"]] = scene
            log.info("Loaded Stash page %d (%d/%d scenes indexed)", page, len(seen_ids), total)
            if len(seen_ids) >= total:
                break
            page += 1
        return index

    def find_or_create_performer(self, name: str) -> str:
        if name in self._performer_cache:
            return self._performer_cache[name]
        data = self._gql(_FIND_PERFORMER, {"name": name})
        performers = data["findPerformers"]["performers"]
        if performers:
            pid = performers[0]["id"]
        else:
            pid = self._gql(_CREATE_PERFORMER, {"name": name})["performerCreate"]["id"]
            log.info("Created performer: %s (id=%s)", name, pid)
        self._performer_cache[name] = pid
        return pid

    def find_or_create_studio(self, name: str) -> str:
        if name in self._studio_cache:
            return self._studio_cache[name]
        data = self._gql(_FIND_STUDIO, {"name": name})
        studios = data["findStudios"]["studios"]
        if studios:
            sid = studios[0]["id"]
        else:
            sid = self._gql(_CREATE_STUDIO, {"name": name})["studioCreate"]["id"]
            log.info("Created studio: %s (id=%s)", name, sid)
        self._studio_cache[name] = sid
        return sid

    def find_or_create_tag(self, name: str) -> str:
        if name in self._tag_cache:
            return self._tag_cache[name]
        data = self._gql(_FIND_TAG, {"name": name})
        tags = data["findTags"]["tags"]
        if tags:
            tid = tags[0]["id"]
        else:
            tid = self._gql(_CREATE_TAG, {"name": name})["tagCreate"]["id"]
            log.info("Created tag: %s (id=%s)", name, tid)
        self._tag_cache[name] = tid
        return tid

    def update_scene(self, scene_id: str, fields: dict[str, Any]) -> None:
        update = dict(fields)
        update["id"] = scene_id
        self._gql(_UPDATE_SCENE, {"input": update})

    def sync_play_history(self, scene_id: str, timestamps: list[str]) -> None:
        """Replace Stash play history with the given ISO8601 timestamps from Plex."""
        self._gql(_RESET_PLAY_COUNT, {"id": scene_id})
        if timestamps:
            self._gql(_ADD_PLAY, {"id": scene_id, "times": timestamps})

    def scan(
        self,
        *,
        generate_phashes: bool = True,
        paths: list[str] | None = None,
        timeout: float = 3600.0,
        poll_interval: float = 3.0,
    ) -> None:
        """Trigger a Stash library scan and block until the job reaches a terminal state.

        Defaults to generating phashes, since a scan triggered here is meant to make
        newly-added content fully usable in Stash (matching, dedup, Identify), not just
        visible - a bare scan alone would leave new scenes without them.

        `rescan` is deliberately never set on the mutation input (left at Stash's
        default/false), NOT an oversight: verified against a real instance that with
        `rescan` unset, `scanGeneratePhashes: true` only computes fingerprints (oshash +
        phash together) for files that are new or changed since the last scan - existing
        files' `updated_at` and fingerprint values are untouched, confirmed by diffing the
        same scenes before/after a repeat scan. Passing `rescan: true` here would force
        every file in the library to be reprocessed on every reconcile run, which is
        exactly what this method must not do.
        """
        scan_input: dict[str, Any] = {"paths": paths or [], "scanGeneratePhashes": generate_phashes}
        job_id = self._gql(_METADATA_SCAN, {"input": scan_input})["metadataScan"]
        self._wait_for_job(job_id, timeout=timeout, poll_interval=poll_interval)

    def _wait_for_job(self, job_id: str, *, timeout: float, poll_interval: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            job = self._gql(_FIND_JOB, {"id": job_id})["findJob"]
            status = job["status"]
            if status == "FINISHED":
                return
            if status in _FAILED_JOB_STATUSES:
                raise RuntimeError(f"Stash job {job_id} ended with status {status}: {job.get('error')}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"Stash job {job_id} did not finish within {timeout}s (last status: {status})")
            time.sleep(poll_interval)

    def merge_scenes(self, source_ids: list[str], destination_id: str, fields: dict[str, Any]) -> None:
        """Merge source scenes into destination, applying fields to the result. Sources are deleted."""
        values = dict(fields)
        values["id"] = destination_id
        self._gql(
            _MERGE_SCENES,
            {
                "input": {
                    "source": source_ids,
                    "destination": destination_id,
                    "play_history": True,
                    "values": values,
                }
            },
        )
