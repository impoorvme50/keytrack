"""Bind an installed bundle's background tools without relying on a checkout."""
import contextlib
import io
import plistlib
import shutil
import sys
from pathlib import Path

from . import agent, kev_rime_setup, prediction_setup, rime_setup


def app_bundle() -> Path | None:
    return next((p for p in Path(sys.executable).resolve().parents if p.suffix == ".app"), None)


def status() -> dict:
    packaged = bool(getattr(sys, "frozen", False))
    bundle = app_bundle() if packaged else None
    roots = (Path("/Applications"), Path.home() / "Applications")
    can_install = bundle is not None and any(bundle.parent == root for root in roots)
    configured = not packaged
    if packaged:
        try:
            current = plistlib.loads(Path(agent.PLIST_PATH).read_bytes())
            configured = current.get("ProgramArguments") == [sys.executable, "record"] and rime_setup.installation_ready()
            schema = kev_rime_setup.RIME_DIR / "rime_ice.custom.yaml"
            if schema.exists() and kev_rime_setup.BEGIN in schema.read_text():
                configured = configured and str(Path(sys.executable)) in schema.read_text()
        except (OSError, ValueError):
            configured = False
    return {"packaged": packaged, "configured": configured, "can_install": can_install}


def install(store) -> dict:
    if not status()["can_install"]:
        raise ValueError("请先将 Keytrack 拖入系统或个人的「应用程序」目录，再完成本机安装")
    backup = store.backup("切换到独立安装版")
    snapshot_dir = store.root / "backups" / (backup + "-installation")
    snapshot_dir.mkdir(mode=0o700)
    plist = Path(agent.PLIST_PATH)
    if plist.exists():
        shutil.copy2(plist, snapshot_dir / plist.name)
        (snapshot_dir / plist.name).chmod(0o600)
    rime = Path(rime_setup.RIME_DIR)
    for source in [*rime.glob("*.custom.yaml"), rime / "lua" / rime_setup.LUA_NAME]:
        if source.is_file():
            destination = snapshot_dir / source.relative_to(rime)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(source, destination)
            destination.chmod(0o600)
    # Do not change the model service or the persistent Kev on/off flag.
    with contextlib.redirect_stdout(io.StringIO()):
        if not rime_setup.setup(verbose=False):
            raise ValueError("输入法接入未完成，原配置已备份，请查看诊断后重试")
        custom = kev_rime_setup.RIME_DIR / "rime_ice.custom.yaml"
        if custom.exists() and kev_rime_setup.BEGIN in custom.read_text():
            if not kev_rime_setup.setup(verbose=False):
                raise ValueError("候选建议桥接未迁移，原配置已备份，请重试")
        if not prediction_setup.setup(verbose=False, rime_dir=rime):
            raise ValueError("本地联想实验方案未安装，原配置已备份，请查看诊断后重试")
        if not agent.install(verbose=False):
            raise ValueError("后台采集服务未启动，原配置已备份，请重试")
    return {"message": "本机安装已完成，后台功能已使用应用内运行程序", "backup": backup}
