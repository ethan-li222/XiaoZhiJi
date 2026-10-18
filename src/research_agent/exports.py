import html
import json
from pathlib import Path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def export_papers(result, directory):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "papers.json", result)
    lines = ["# 论文检索结果", ""]
    for p in result.get("papers", []):
        lines.extend(
            [
                f"## {p['title']}",
                f"{p.get('year') or '年份未知'} · {', '.join(p['authors'])}",
                f"来源：{p['url']}",
                f"PDF：{p.get('pdf_url') or '暂无开放 PDF 地址'}",
                "",
                p.get("abstract", ""),
                "",
            ]
        )
    if result.get("warnings"):
        lines.extend(["## 数据提示", *result["warnings"]])
    (directory / "papers.md").write_text("\n".join(lines), encoding="utf-8")
    if "relations" in result:
        write_json(directory / "graph.json", result)
        data = (
            json.dumps(result, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        template = (Path(__file__).parent / "graph.html").read_text(encoding="utf-8")
        (directory / "graph.html").write_text(
            template.replace(
                "__GRAPH_SCRIPT__",
                (Path(__file__).parent / "static/papers.js").read_text(encoding="utf-8")
                + "\n"
                + (Path(__file__).parent / "static/literature-map.js").read_text(encoding="utf-8"),
            )
            .replace(
                "__GRAPH_CSS__",
                (Path(__file__).parent / "static/papers.css").read_text(encoding="utf-8"),
            )
            .replace("__GRAPH_DATA__", data),
            encoding="utf-8",
        )
    return {"directory": str(directory)}


def export_report(report, directory):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "report.json", report)
    write_json(directory / "sources.json", report["sources"])
    source_map = {s["id"]: s for s in report["sources"]}
    lines = ["# " + report["title"], "", "生成时间：" + report["created_at"], ""]
    for section in report["sections"]:
        lines += ["## " + section["title"], "", section["text"], ""]
        lines += [
            f"- [{html.escape(source_map[i]['title'])}]({source_map[i]['url']})"
            for i in section["source_ids"]
        ]
        lines.append("")
    if report["unknown_date_sources"]:
        lines += ["## 日期未知，未计入本期结论", ""]
        lines += [f"- [{s['title']}]({s['url']})" for s in report["unknown_date_sources"]]
    if report["warnings"]:
        lines += ["", "## 覆盖提示", "", *["- " + w for w in report["warnings"]]]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"directory": str(directory), "markdown": str(directory / "report.md")}
