import ast
import csv
import gzip
import hashlib
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import dashboard_data


TOKEN = "github_pat_SYNTHETIC_TEST_TOKEN_DO_NOT_USE"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
COMMIT_2 = "1123456789abcdef0123456789abcdef01234567"
TREE_SHA = "2123456789abcdef0123456789abcdef01234567"
TREE_SHA_2 = "3123456789abcdef0123456789abcdef01234567"
METADATA = {
    "min_date": "2020-01-01",
    "max_date": "2020-01-02",
    "score_rows": 2,
    "unique_boundary_ids": 1,
    "scope_states": sorted(dashboard_data.ALLOWED_STATES),
    "disclaimer": dashboard_data.DISCLAIMER,
    "source_score_sha256": "0" * 64,
    "source_feature_sha256": "1" * 64,
}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.body


class FakeOpener:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def fake_opener_builder(responses):
    captured = {"openers": []}
    response_queue = list(responses)

    def build(handler):
        captured["handler"] = handler
        captured["opener"] = FakeOpener(response_queue)
        captured["openers"].append(captured["opener"])
        return captured["opener"]

    return build, captured


def http_error(status, headers=None, reason="synthetic response"):
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = str(value)
    return HTTPError(
        "https://api.github.com/test-only",
        status,
        reason,
        message,
        io.BytesIO(b"synthetic body"),
    )


def github_secrets(token=TOKEN, commit=COMMIT, path_prefix=""):
    github = {} if token is None else {"token": token}
    return {
        "runtime_assets": {
            "mode": "github",
            "owner": "synthetic-owner",
            "repository": "synthetic-runtime-assets",
            "ref": commit,
            "path_prefix": path_prefix,
            "github": github,
        }
    }


def git_blob_sha(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def annual_bytes(status="PASS_AT_LEAST_80_PERCENT", category="", available="0"):
    fields = sorted(dashboard_data.ANNUAL_REQUIRED_COLUMNS)
    rows = []
    for day in ("2020-01-01", "2020-01-02"):
        rows.append({
            "State": "Andhra Pradesh",
            "District": "Synthetic District",
            "Rainfall_Boundary_Record_Index": "1",
            "GeoJSON_id": "1",
            "Target_Date": day,
            "Risk_Score": "",
            "Risk_Category": category,
            "Risk_Score_Available": available,
            "Data_Quality_Status": "UNAVAILABLE",
            "Score_Unavailable_Reason": "synthetic test fixture",
            "Coverage_Gate_Status": status,
        })
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def history_bytes():
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb") as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
            fields = sorted(dashboard_data.HISTORY_REQUIRED_COLUMNS)
            writer = csv.DictWriter(text, fieldnames=fields)
            writer.writeheader()
            writer.writerows([
                {
                    "state": "Andhra Pradesh",
                    "district": "Synthetic District",
                    "Rainfall_Boundary_Record_Index": "1",
                    "date": "2020-01-01",
                    "Rainfall_Prev_1d_mm": "0.0",
                },
                {
                    "state": "Andhra Pradesh",
                    "district": "Synthetic District",
                    "Rainfall_Boundary_Record_Index": "1",
                    "date": "2020-01-02",
                    "Rainfall_Prev_1d_mm": "",
                },
            ])
    return output.getvalue()


def runtime_asset_bytes():
    return {
        dashboard_data.BOUNDARY_PATH: json.dumps(
            {"type": "FeatureCollection", "features": []}
        ).encode("utf-8"),
        dashboard_data.METADATA_PATH: json.dumps(METADATA).encode("utf-8"),
        "data/annual_scores/2020.csv": annual_bytes(),
        "data/district_history/1.csv.gz": history_bytes(),
    }


def commit_response(commit_sha=COMMIT, tree_sha=TREE_SHA):
    return json.dumps({"sha": commit_sha, "tree": {"sha": tree_sha}}).encode("utf-8")


def tree_response(assets, prefix="", tree_sha=TREE_SHA, truncated=False):
    entries = []
    for path, data in assets.items():
        full_path = f"{prefix}/{path}" if prefix else path
        entries.append({"path": full_path, "type": "blob", "sha": git_blob_sha(data)})
    return json.dumps({"sha": tree_sha, "truncated": truncated, "tree": entries}).encode("utf-8")


def api_responses(assets=None, prefix="", commit_sha=COMMIT, tree_sha=TREE_SHA):
    assets = assets or runtime_asset_bytes()
    responses = [
        FakeResponse(commit_response(commit_sha, tree_sha)),
        FakeResponse(tree_response(assets, prefix, tree_sha)),
    ]
    responses.extend(FakeResponse(data) for data in assets.values())
    return responses


class GithubAssetLoaderTests(unittest.TestCase):
    def setUp(self):
        for loader in (
            dashboard_data._metadata_for_version,
            dashboard_data._date_list_for_version,
            dashboard_data._map_snapshot_for_version,
            dashboard_data._district_history_for_version,
            dashboard_data._boundary_geojson_for_version,
            dashboard_data._cached_map_view,
            dashboard_data._tree_for_commit,
        ):
            loader.clear()

    def load_local_annual(self, statuses, categories, availability):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "data" / "annual_scores").mkdir(parents=True)
        (root / "data").joinpath("dashboard_cache_metadata.json").write_text(
            json.dumps(METADATA), encoding="utf-8"
        )
        fields = sorted(dashboard_data.ANNUAL_REQUIRED_COLUMNS)
        rows = []
        for index, day in enumerate(("2020-01-01", "2020-01-02")):
            rows.append({
                "State": "Andhra Pradesh", "District": "Synthetic District",
                "Rainfall_Boundary_Record_Index": "1", "GeoJSON_id": "1",
                "Target_Date": day,
                "Risk_Score": "12.5" if availability[index] == "1" else "",
                "Risk_Category": categories[index],
                "Risk_Score_Available": availability[index],
                "Data_Quality_Status": "AVAILABLE" if availability[index] == "1" else "UNAVAILABLE",
                "Score_Unavailable_Reason": "" if availability[index] == "1" else "synthetic test fixture",
                "Coverage_Gate_Status": statuses[index],
            })
        with (root / "data" / "annual_scores" / "2020.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        secrets = {"runtime_assets": {"mode": "local", "local_data_root": str(root)}}
        return temp, secrets

    def test_annual_coverage_statuses_and_category_gate(self):
        cases = (
            ("PASS_AT_LEAST_80_PERCENT", "LOW", "1", "LOW"),
            ("FAIL_BELOW_80_PERCENT", "", "0", "Category withheld: low coverage"),
            ("UNAVAILABLE_COVERAGE", "", "0", "Coverage unavailable"),
        )
        for status, category, available, expected_display in cases:
            with self.subTest(status=status):
                temp, secrets = self.load_local_annual(
                    [status, status], [category, category], [available, available]
                )
                try:
                    with patch.object(dashboard_data.st, "secrets", secrets):
                        frame = dashboard_data.map_snapshot("2020")
                    self.assertEqual(set(frame["Coverage_Gate_Status"]), {status})
                    self.assertEqual(set(frame["Risk_Category"]), {category})
                    self.assertEqual(dashboard_data.map_status(frame.iloc[0]), expected_display)
                finally:
                    temp.cleanup()

    def test_categories_on_either_non_pass_status_are_rejected(self):
        for status in ("FAIL_BELOW_80_PERCENT", "UNAVAILABLE_COVERAGE"):
            with self.subTest(status=status):
                temp, secrets = self.load_local_annual(
                    [status, status], ["LOW", "LOW"], ["1", "1"]
                )
                try:
                    with patch.object(dashboard_data.st, "secrets", secrets):
                        with self.assertRaisesRegex(
                            dashboard_data.DataValidationError,
                            "assigns a category without passing the coverage gate",
                        ):
                            dashboard_data.map_snapshot("2020")
                finally:
                    temp.cleanup()

    def test_unknown_coverage_status_is_rejected(self):
        temp, secrets = self.load_local_annual(
            ["UNKNOWN_STATUS", "UNKNOWN_STATUS"], ["", ""], ["0", "0"]
        )
        try:
            with patch.object(dashboard_data.st, "secrets", secrets):
                with self.assertRaisesRegex(
                    dashboard_data.DataValidationError, "invalid coverage status"
                ):
                    dashboard_data.map_snapshot("2020")
        finally:
            temp.cleanup()

    def test_app_coverage_labels_distinguish_all_states_and_default_unavailable(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app_tree = ast.parse(app_path.read_text(encoding="utf-8"))
        wanted_functions = {"coverage_status_label", "status_distribution_counts"}
        wanted_constants = {"MAP_LEGEND_LABELS", "STATUS_DISTRIBUTION_LABELS"}
        isolated_nodes = [
            node for node in app_tree.body
            if (
                isinstance(node, ast.FunctionDef) and node.name in wanted_functions
            ) or (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id in wanted_constants
                        for target in node.targets)
            )
        ]
        isolated_module = ast.Module(body=isolated_nodes, type_ignores=[])
        namespace = {}
        exec(compile(isolated_module, str(app_path), "exec"), namespace)
        label = namespace["coverage_status_label"]
        self.assertEqual(label("PASS_AT_LEAST_80_PERCENT"), "At least 80% (gate passed)")
        self.assertEqual(label("FAIL_BELOW_80_PERCENT"), "Below 80% (category withheld)")
        self.assertEqual(label("UNAVAILABLE_COVERAGE"), "Coverage unavailable")
        self.assertEqual(label("UNKNOWN"), "Coverage unavailable")
        self.assertEqual(label(None), "Coverage unavailable")

        def record(coverage, available, category):
            return {
                "Coverage_Gate_Status": coverage,
                "Risk_Score_Available": available,
                "Risk_Category": category,
            }

        statuses = [
            dashboard_data.map_status(record("PASS_AT_LEAST_80_PERCENT", "1", "LOW")),
            dashboard_data.map_status(record("FAIL_BELOW_80_PERCENT", "0", "")),
            dashboard_data.map_status(record("UNAVAILABLE_COVERAGE", "0", "")),
            dashboard_data.map_status(record("UNKNOWN", "0", "")),
            dashboard_data.map_status(record(None, "0", "")),
        ]
        counts = namespace["status_distribution_counts"](statuses)
        self.assertEqual(counts["LOW"], 1)
        self.assertEqual(counts["Category withheld: low coverage"], 1)
        self.assertEqual(counts["Coverage unavailable"], 1)
        self.assertEqual(counts["Score unavailable"], 2)
        self.assertNotIn("PASS_AT_LEAST_80_PERCENT", counts)

        legend_labels = namespace["MAP_LEGEND_LABELS"]
        self.assertIn("Coverage unavailable", legend_labels)
        for legend_label in legend_labels:
            self.assertIn(legend_label, dashboard_data.MAP_STATUS_COLORS)

    def test_commit_to_tree_resolution_and_correct_path_to_blob_sha(self):
        assets = runtime_asset_bytes()
        prefix = "private/runtime-v1"
        build, captured = fake_opener_builder([
            FakeResponse(commit_response()),
            FakeResponse(tree_response(assets, prefix)),
        ])
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            tree = dashboard_data._tree_for_commit(
                "synthetic-owner", "synthetic-runtime-assets", COMMIT, TOKEN
            )
        self.assertEqual(tree[f"{prefix}/{dashboard_data.METADATA_PATH}"], git_blob_sha(assets[dashboard_data.METADATA_PATH]))
        requests = [request for opener in captured["openers"] for request in opener.requests]
        self.assertEqual(len(requests), 2)
        self.assertTrue(requests[0].full_url.endswith(f"/git/commits/{COMMIT}"))
        self.assertTrue(requests[1].full_url.endswith(f"/git/trees/{TREE_SHA}?recursive=1"))
        self.assertTrue(all(urlsplit(request.full_url).netloc == "api.github.com" for request in requests))

    def test_successful_blob_uses_raw_media_type_and_stays_on_api_host(self):
        payload = b"synthetic blob content"
        sha = git_blob_sha(payload)
        build, captured = fake_opener_builder([FakeResponse(payload)])
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            actual = dashboard_data._blob_bytes(
                "synthetic-owner", "synthetic-runtime-assets", sha, TOKEN
            )
        request = captured["opener"].requests[0]
        self.assertEqual(actual, payload)
        self.assertTrue(request.full_url.endswith(f"/git/blobs/{sha}"))
        self.assertEqual(request.get_header("Accept"), "application/vnd.github.raw+json")
        self.assertEqual(urlsplit(request.full_url).scheme, "https")
        self.assertEqual(urlsplit(request.full_url).netloc, "api.github.com")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, request.full_url)

    def test_all_four_asset_types_load_through_tree_and_blob_api_with_prefix(self):
        assets = runtime_asset_bytes()
        prefix = "runtime-assets/v1"
        secrets = github_secrets(path_prefix=prefix)
        build, captured = fake_opener_builder(api_responses(assets, prefix))
        with patch.object(dashboard_data.st, "secrets", secrets), patch.object(
            dashboard_data, "build_opener", side_effect=build
        ):
            self.assertEqual(dashboard_data.boundary_geojson()["features"], [])
            self.assertEqual(dashboard_data.metadata(), METADATA)
            annual = dashboard_data.map_snapshot("2020")
            history = dashboard_data.district_history("1")
        self.assertEqual(len(annual), 2)
        self.assertEqual(history["Rainfall_Prev_1d_mm"].tolist(), ["0.0", ""])
        requests = [request for opener in captured["openers"] for request in opener.requests]
        self.assertEqual(len(requests), 6)  # Commit + tree once, then four lazy blob reads.
        self.assertTrue(all(urlsplit(request.full_url).netloc == "api.github.com" for request in requests))
        blob_urls = [request.full_url for request in requests if "/git/blobs/" in request.full_url]
        self.assertEqual(len(blob_urls), 4)

    def test_missing_approved_asset_path_fails_without_blob_request(self):
        assets = runtime_asset_bytes()
        assets.pop(dashboard_data.METADATA_PATH)
        build, captured = fake_opener_builder([
            FakeResponse(commit_response()), FakeResponse(tree_response(assets))
        ])
        source = ("github", "synthetic-owner", "synthetic-runtime-assets", COMMIT,
                  dashboard_data.METADATA_PATH, "")
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            with self.assertRaisesRegex(dashboard_data.RuntimeAssetError, "not found"):
                dashboard_data._read_asset(source, TOKEN)
        self.assertEqual(sum(len(opener.requests) for opener in captured["openers"]), 2)

    def test_invalid_commit_and_invalid_tree_responses_fail_safely(self):
        cases = [
            ([FakeResponse(b"not json")], "invalid pinned commit response"),
            ([FakeResponse(commit_response(COMMIT_2))], "does not match the pinned SHA"),
            ([FakeResponse(json.dumps({"sha": COMMIT, "tree": {"sha": "bad"}}).encode())], "invalid tree identifier"),
            ([FakeResponse(commit_response()), FakeResponse(json.dumps({"sha": TREE_SHA, "truncated": "false", "tree": []}).encode())], "invalid recursive tree response"),
            ([FakeResponse(commit_response()), FakeResponse(json.dumps({"sha": TREE_SHA, "truncated": False, "tree": [{"path": "x", "type": "blob", "sha": "bad"}]}).encode())], "invalid blob identifier"),
        ]
        for responses, expected in cases:
            with self.subTest(expected=expected):
                dashboard_data._tree_for_commit.clear()
                build, _ = fake_opener_builder(responses)
                with patch.object(dashboard_data, "build_opener", side_effect=build):
                    with self.assertRaisesRegex(dashboard_data.RuntimeAssetError, expected):
                        dashboard_data._tree_for_commit(
                            "synthetic-owner", "synthetic-runtime-assets", COMMIT, TOKEN
                        )

    def test_truncated_tree_is_reported_and_never_treated_as_missing_asset(self):
        assets = runtime_asset_bytes()
        truncated = tree_response(assets, truncated=True)
        build, _ = fake_opener_builder([FakeResponse(commit_response()), FakeResponse(truncated)])
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            with self.assertRaisesRegex(dashboard_data.RuntimeAssetError, "truncated"):
                dashboard_data._tree_for_commit(
                    "synthetic-owner", "synthetic-runtime-assets", COMMIT, TOKEN
                )

    def test_authentication_and_permission_errors_are_sanitized(self):
        for status, expected in ((401, "authentication failed"), (403, "denied access")):
            with self.subTest(status=status):
                build, _ = fake_opener_builder([http_error(status, reason=TOKEN)])
                with patch.object(dashboard_data, "build_opener", side_effect=build):
                    with self.assertNoLogs():
                        with self.assertRaises(dashboard_data.RuntimeAssetError) as caught:
                            dashboard_data._tree_for_commit(
                                "synthetic-owner", "synthetic-runtime-assets", COMMIT, TOKEN
                            )
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_rate_limit_retries_are_bounded_and_network_failure_is_sanitized(self):
        build, captured = fake_opener_builder([
            http_error(429, {"Retry-After": "0"}), FakeResponse(b"ok")
        ])
        with patch.object(dashboard_data, "build_opener", side_effect=build), patch.object(
            dashboard_data.time, "sleep"
        ) as sleep:
            self.assertEqual(dashboard_data._github_api_get(
                "synthetic-owner", "synthetic-runtime-assets", "/git/commits/" + COMMIT,
                TOKEN, "application/vnd.github+json", resource="pinned commit",
            ), b"ok")
        self.assertEqual(sum(len(opener.requests) for opener in captured["openers"]), 2)
        sleep.assert_called_once_with(0.0)

        build, _ = fake_opener_builder([URLError(TOKEN)])
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            with self.assertNoLogs():
                with self.assertRaises(dashboard_data.RuntimeAssetError) as caught:
                    dashboard_data._github_api_get(
                        "synthetic-owner", "synthetic-runtime-assets", "/git/commits/" + COMMIT,
                        TOKEN, "application/vnd.github+json", resource="pinned commit",
                    )
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_pinned_commit_cache_isolation(self):
        build, captured = fake_opener_builder([
            FakeResponse(commit_response(COMMIT, TREE_SHA)),
            FakeResponse(tree_response(runtime_asset_bytes(), tree_sha=TREE_SHA)),
            FakeResponse(commit_response(COMMIT_2, TREE_SHA_2)),
            FakeResponse(tree_response(runtime_asset_bytes(), tree_sha=TREE_SHA_2)),
        ])
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            first = dashboard_data._tree_for_commit(
                "synthetic-owner", "synthetic-runtime-assets", COMMIT, TOKEN
            )
            cached = dashboard_data._tree_for_commit(
                "synthetic-owner", "synthetic-runtime-assets", COMMIT, "github_pat_ROTATED_TEST_TOKEN"
            )
            second = dashboard_data._tree_for_commit(
                "synthetic-owner", "synthetic-runtime-assets", COMMIT_2, TOKEN
            )
        self.assertEqual(first, cached)
        self.assertEqual(first, second)
        requests = [request for opener in captured["openers"] for request in opener.requests]
        self.assertEqual(len(requests), 4)
        self.assertIn(COMMIT, requests[0].full_url)
        self.assertIn(COMMIT_2, requests[2].full_url)

    def test_token_is_never_in_api_urls_or_sanitized_errors(self):
        build, captured = fake_opener_builder([http_error(404, reason=TOKEN)])
        with patch.object(dashboard_data, "build_opener", side_effect=build):
            with self.assertNoLogs():
                with self.assertRaises(dashboard_data.RuntimeAssetError) as caught:
                    dashboard_data._github_api_get(
                        "synthetic-owner", "synthetic-runtime-assets", "/git/blobs/" + TREE_SHA,
                        TOKEN, "application/vnd.github.raw+json", resource="runtime blob",
                    )
        request = captured["opener"].requests[0]
        self.assertNotIn(TOKEN, request.full_url)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_blob_sha_is_verified(self):
        payload = b"integrity fixture"
        expected = git_blob_sha(payload)
        self.assertEqual(dashboard_data._verify_blob_sha(payload, expected), payload)
        with self.assertRaisesRegex(dashboard_data.RuntimeAssetError, "SHA-1 integrity"):
            dashboard_data._verify_blob_sha(payload, "0" * 40)

    def test_prefix_validation_and_asset_allowlist(self):
        self.assertEqual(dashboard_data._validate_path_prefix(""), "")
        self.assertEqual(dashboard_data._validate_path_prefix("runtime/assets-v1"), "runtime/assets-v1")
        for prefix in ("/runtime", "runtime/", "runtime//assets", "runtime/../assets", "runtime\\assets"):
            with self.subTest(prefix=prefix), self.assertRaises(dashboard_data.RuntimeAssetError):
                dashboard_data._validate_path_prefix(prefix)
        for path in ("../secret.csv", "/data/annual_scores/2020.csv", "data\\annual_scores\\2020.csv",
                     "data/other/file.csv", "data/annual_scores/not-a-year.csv"):
            with self.subTest(path=path), self.assertRaises(dashboard_data.RuntimeAssetError):
                dashboard_data._validate_asset_path(path)

    def test_redirects_are_rejected_instead_of_forwarding_credentials(self):
        handler = dashboard_data._RejectGitHubRedirectHandler()
        request = Request("https://api.github.com/repos/synthetic-owner/repo/git/blobs/" + TREE_SHA,
                          headers={"Authorization": f"Bearer {TOKEN}"})
        with self.assertRaises(dashboard_data.RuntimeAssetError) as caught:
            handler.redirect_request(request, None, 302, "Found", Message(),
                                     "https://raw.githubusercontent.com/synthetic-owner/repo/blob")
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_local_mode_needs_no_github_credentials_and_preserves_zero_vs_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data" / "annual_scores").mkdir(parents=True)
            (root / "data" / "district_history").mkdir(parents=True)
            (root / "assets").mkdir()
            (root / "data" / "dashboard_cache_metadata.json").write_text(
                json.dumps(METADATA), encoding="utf-8"
            )
            annual_fields = sorted(dashboard_data.ANNUAL_REQUIRED_COLUMNS)
            with (root / "data" / "annual_scores" / "2020.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=annual_fields)
                writer.writeheader()
                for day in ("2020-01-01", "2020-01-02"):
                    writer.writerow({
                        "State": "Andhra Pradesh", "District": "Synthetic District",
                        "Rainfall_Boundary_Record_Index": "1", "GeoJSON_id": "1",
                        "Target_Date": day, "Risk_Score": "", "Risk_Category": "",
                        "Risk_Score_Available": "0", "Data_Quality_Status": "UNAVAILABLE",
                        "Score_Unavailable_Reason": "synthetic", "Coverage_Gate_Status": "PASS_AT_LEAST_80_PERCENT",
                    })
            (root / "data" / "district_history" / "1.csv.gz").write_bytes(history_bytes())
            secrets = {"runtime_assets": {"mode": "local", "local_data_root": str(root)}}
            with patch.object(dashboard_data.st, "secrets", secrets):
                self.assertEqual(dashboard_data.metadata(), METADATA)
                self.assertEqual(len(dashboard_data.map_snapshot("2020")), 2)
                history = dashboard_data.district_history("1")
            self.assertEqual(history["Rainfall_Prev_1d_mm"].tolist(), ["0.0", ""])


if __name__ == "__main__":
    unittest.main()
