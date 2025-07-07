import json

from e3.testsuite import ParsedTest, Testsuite as Suite

from .utils import run_testsuite


def test_list_json(tmp_path):
    class TS(Suite):
        def get_test_list(self, sublist):
            return [
                ParsedTest("test1", None, {}, ".", "test1"),
                ParsedTest("test2", None, {}, ".", "test2"),
                ParsedTest("test3", None, {}, ".", None),
            ]

    json_path = tmp_path / "out.json"
    run_testsuite(TS, [f"--list-json={json_path}"])

    raw_actual = json_path.read_text()
    json_actual = json.loads(raw_actual)
    assert json_actual == [
        {
            "test_dir": ".",
            "test_matcher": "test1",
            "test_name": "test1",
        },
        {
            "test_dir": ".",
            "test_matcher": "test2",
            "test_name": "test2",
        },
        {
            "test_dir": ".",
            "test_matcher": None,
            "test_name": "test3",
        },
    ]
