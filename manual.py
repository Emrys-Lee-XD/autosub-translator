"""Open the current README in a browser without duplicating stale instructions."""
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile
import webbrowser


def main():
    readme = Path(__file__).with_name("README.md").read_text(encoding="utf-8")
    page = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<title>Autosub 使用说明</title>"
            "<style>body{font:16px/1.7 'Microsoft YaHei',sans-serif;max-width:900px;"
            "margin:3rem auto;padding:0 1rem;color:#20304a;background:#f8fafc}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><pre>"
            + escape(readme) + "</pre></html>")
    with NamedTemporaryFile("w", suffix=".html", prefix="autosub-manual-",
                            encoding="utf-8", delete=False) as file:
        file.write(page)
        path = Path(file.name)
    webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
