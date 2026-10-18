import json
import os
import shutil
import subprocess
from pathlib import Path


def libreoffice_path():
    candidate = shutil.which("soffice") or shutil.which("libreoffice")
    windows = Path("C:/Program Files/LibreOffice/program/soffice.exe")
    return candidate or (str(windows) if windows.exists() else None)


def powerpoint_available():
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CLSID"):
            return True
    except OSError:
        return False


def render_preview(pptx, output_dir=None, renderer="auto"):
    pptx = Path(pptx).resolve()
    if not pptx.is_file() or pptx.suffix.lower() != ".pptx":
        raise ValueError("需要已存在的 PPTX 文件")
    directory = (Path(output_dir) if output_dir else pptx.parent / "preview").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if renderer not in {"auto", "powerpoint", "libreoffice"}:
        raise ValueError("renderer 为 auto、powerpoint 或 libreoffice")
    office = libreoffice_path()
    if renderer == "auto":
        renderer = "powerpoint" if powerpoint_available() else "libreoffice"
    if renderer == "powerpoint":
        if not powerpoint_available():
            raise ValueError("未检测到 PowerPoint；可安装 LibreOffice 后选择 libreoffice")
        script = Path(__file__).with_name("preview_powerpoint.ps1")
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-PptxPath",
                    str(pptx),
                    "-OutputDirectory",
                    str(directory),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("PowerPoint 预览超时；请检查本机 Office 激活或对话框状态") from None
        if result.returncode:
            raise ValueError("PowerPoint 预览失败：" + result.stderr[-1200:])
    else:
        if not office:
            raise ValueError("未找到 PowerPoint 或 LibreOffice，无法生成预览")
        try:
            subprocess.run(
                [
                    office,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(directory),
                    str(pptx),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise ValueError("LibreOffice 预览失败，请检查文件占用或本机应用状态") from None
    pdf = directory / (pptx.stem + ".pdf")
    if not pdf.exists():
        raise ValueError("渲染工具未生成 PDF 文件")
    images = []
    if renderer == "powerpoint":
        manifest = json.loads((directory / "slides.json").read_text(encoding="utf-8-sig"))
        images = [directory / "slides" / name for name in manifest]
        if any(not path.is_file() for path in images):
            raise ValueError("PowerPoint 预览缺少页面图片")
    return {"pdf": str(pdf), "images": [str(p) for p in images], "renderer": renderer}
