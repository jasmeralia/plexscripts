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

_RECONCILE_SCENES = """
query ReconcileScenes($page: Int!, $per_page: Int!) {
  findScenes(filter: { page: $page, per_page: $per_page }, sort: "id", direction: ASC) {
    count
    scenes {
      id
      files { path }
      custom_fields
      performers { id name }
      tags { id name }
    }
  }
}
"""

_SCENE_BY_ID = """
query ReconcileSceneByID($id: ID!) {
  findScene(id: $id) {
    id
    files { path }
    custom_fields
    performers { id name }
    tags { id name }
  }
}
"""

_RECONCILE_SCHEMA = """
query ReconcileSchema {
  scene: __type(name: "Scene") { fields { name } }
  update: __type(name: "SceneUpdateInput") { inputFields { name type { name ofType { name ofType { name } } } } }
  merge: __type(name: "SceneMergeInput") { inputFields { name type { name ofType { name ofType { name } } } } }
  mergeValues: __type(name: "SceneMergeInputValues") { inputFields { name type { name ofType { name ofType { name } } } } }
  query: __type(name: "Query") { fields { name args { name type { name ofType { name ofType { name } } } } } }
}
"""

_INPUT_SCHEMA = """
query ReconcileInputSchema($name: String!) {
  input: __type(name: $name) { kind inputFields { name type { name ofType { name ofType { name } } } } }
}
"""

_ALL_TAGS = """
query AllTags {
  allTags { id name scene_count stash_ids { endpoint stash_id } }
}
"""

_CONFIGURED_STASH_BOXES = """
query ConfiguredStashBoxes {
  configuration { general { stashBoxes { name endpoint } } }
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

_UPDATE_TAG = """
mutation UpdateTag($input: TagUpdateInput!) {
  tagUpdate(input: $input) { id name }
}
"""

_MERGE_SCENES = """
mutation MergeScenes($input: SceneMergeInput!) {
  sceneMerge(input: $input) { id }
}
"""

_MERGE_PERFORMERS = """
mutation MergePerformers($input: PerformerMergeInput!) {
  performerMerge(input: $input) { id }
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

_METADATA_CLEAN = """
mutation MetadataClean($input: CleanMetadataInput!) {
  metadataClean(input: $input)
}
"""

_FIND_JOB = """
query FindJob($id: ID!) {
  findJob(input: {id: $id}) { id status error }
}
"""

_FAILED_JOB_STATUSES = {"CANCELLED", "FAILED"}


def _named_type(type_ref: dict[str, Any] | None) -> str | None:
    while type_ref:
        if type_ref.get("name"):
            return str(type_ref["name"])
        type_ref = type_ref.get("ofType")
    return None


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

    def check_reconcile_capabilities(self) -> None:
        """Fail before reconcile mutations unless Stash supports scene custom fields and merges."""
        schema = self._gql(_RECONCILE_SCHEMA)
        scene_fields = {field["name"] for field in (schema.get("scene") or {}).get("fields") or []}
        update_fields = {field["name"] for field in (schema.get("update") or {}).get("inputFields") or []}
        custom_fields_type = next(
            (
                _named_type(field.get("type"))
                for field in (schema.get("update") or {}).get("inputFields") or []
                if field["name"] == "custom_fields"
            ),
            None,
        )
        merge_fields = {field["name"] for field in (schema.get("merge") or {}).get("inputFields") or []}
        values_type = next(
            (
                _named_type(field.get("type"))
                for field in (schema.get("merge") or {}).get("inputFields") or []
                if field["name"] == "values"
            ),
            None,
        )
        value_fields = {field["name"] for field in (schema.get("mergeValues") or {}).get("inputFields") or []}
        missing = []
        if "custom_fields" not in scene_fields:
            missing.append("Scene.custom_fields")
        if "custom_fields" not in update_fields:
            missing.append("SceneUpdateInput.custom_fields")
        elif custom_fields_type:
            custom_fields_schema = self._gql(_INPUT_SCHEMA, {"name": custom_fields_type}).get("input") or {}
            custom_fields_input_fields = {field["name"] for field in custom_fields_schema.get("inputFields") or []}
            if custom_fields_schema.get("kind") != "INPUT_OBJECT" or "partial" not in custom_fields_input_fields:
                missing.append(f"{custom_fields_type}.partial")
        if not {"source", "destination", "values"}.issubset(merge_fields):
            missing.append("SceneMergeInput source/destination/values")
        if values_type and values_type != "SceneUpdateInput" and "custom_fields" not in value_fields:
            missing.append(f"{values_type}.custom_fields")
        query_fields = (schema.get("query") or {}).get("fields") or []
        find_scenes: dict[str, Any] = next((field for field in query_fields if field["name"] == "findScenes"), {})
        scene_filter_type = next(
            (_named_type(arg.get("type")) for arg in find_scenes.get("args") or [] if arg["name"] == "scene_filter"),
            None,
        )
        scene_filter_schema = (
            self._gql(_INPUT_SCHEMA, {"name": scene_filter_type}).get("input") or {} if scene_filter_type else {}
        )
        scene_filter_fields = scene_filter_schema.get("inputFields") or []
        custom_filter_type = next(
            (_named_type(field.get("type")) for field in scene_filter_fields if field["name"] == "custom_fields"),
            None,
        )
        custom_filter_schema = (
            self._gql(_INPUT_SCHEMA, {"name": custom_filter_type}).get("input") or {} if custom_filter_type else {}
        )
        custom_filter_fields = {field["name"] for field in custom_filter_schema.get("inputFields") or []}
        if not {"field", "value", "modifier"}.issubset(custom_filter_fields):
            missing.append("findScenes scene_filter.custom_fields EQUALS")
        if missing:
            raise RuntimeError("Stash does not support safe Plex rating key reconciliation: " + ", ".join(missing))

    def reconcile_scenes(self) -> list[dict[str, Any]]:
        """Read a stable, ID-ordered scene inventory for reconcile, retaining path collisions."""
        scenes_by_id: dict[str, dict[str, Any]] = {}
        expected_count: int | None = None
        previous_id: int | None = None
        page = 1
        while True:
            result = self._gql(_RECONCILE_SCENES, {"page": page, "per_page": PAGE_SIZE})["findScenes"]
            count = int(result["count"])
            scenes = result["scenes"]
            if expected_count is None:
                expected_count = count
            elif count != expected_count:
                raise RuntimeError(f"Stash scene count changed during reconcile inventory ({expected_count} → {count})")
            expected_page_size = min(PAGE_SIZE, max(count - len(scenes_by_id), 0))
            if len(scenes) != expected_page_size:
                raise RuntimeError(f"Stash scene inventory ended early on page {page}")
            for scene in scenes:
                scene_id = str(scene["id"])
                try:
                    numeric_id = int(scene_id)
                except ValueError as exc:
                    raise RuntimeError(f"Stash returned a non-numeric scene ID: {scene_id}") from exc
                if scene_id in scenes_by_id or (previous_id is not None and numeric_id <= previous_id):
                    raise RuntimeError(f"Stash scene pagination was not strictly ID-ordered at scene {scene_id}")
                previous_id = numeric_id
                scenes_by_id[scene_id] = scene
            if len(scenes_by_id) == count:
                break
            if not scenes:
                raise RuntimeError(f"Stash scene inventory ended at {len(scenes_by_id)} of {count} scenes")
            page += 1
        if len(scenes_by_id) != (expected_count or 0):
            raise RuntimeError(
                f"Stash scene inventory count mismatch: collected {len(scenes_by_id)} of {expected_count}"
            )
        return list(scenes_by_id.values())

    def reconcile_scene_by_id(self, scene_id: str) -> dict[str, Any] | None:
        """Read the current merge participant immediately before a scene merge."""
        return self._gql(_SCENE_BY_ID, {"id": scene_id}).get("findScene")

    def all_tags(self) -> list[dict[str, Any]]:
        """Return every Stash tag with its id, name, scene_count, and stash_ids (external stash-box links)."""
        return self._gql(_ALL_TAGS)["allTags"]  # type: ignore[no-any-return]

    def configured_stash_boxes(self) -> list[dict[str, Any]]:
        """Return this instance's configured stash-box connections (name + endpoint)."""
        return self._gql(_CONFIGURED_STASH_BOXES)["configuration"]["general"]["stashBoxes"]  # type: ignore[no-any-return]

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

    def rename_tag(self, tag_id: str, new_name: str) -> None:
        self._gql(_UPDATE_TAG, {"input": {"id": tag_id, "name": new_name}})

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

    def clean(self, *, timeout: float = 3600.0, poll_interval: float = 3.0) -> None:
        """Remove Stash scene records whose files are no longer present in configured paths.

        Run after scanning so files moved within the library can be found and their existing
        scene records updated before the clean task removes records for paths that are gone.
        """
        job_id = self._gql(_METADATA_CLEAN, {"input": {"dryRun": False}})["metadataClean"]
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

    def merge_performers(self, source_ids: list[str], destination_id: str) -> None:
        """Merge source performers into destination - every scene referencing a source
        performer is reassigned to destination, and the source performer records are
        deleted."""
        self._gql(_MERGE_PERFORMERS, {"input": {"source": source_ids, "destination": destination_id}})
