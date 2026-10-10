"""SkillBridge: one physical skill library, native per-host directory links.

Python 3.12+, standard library only. No daemon, model API, or skill execution.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid


class BridgeError(Exception):
    pass


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def valid_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise BridgeError("名称须为 1–64 位小写英文、数字或连字符，不能包含路径。")
    if name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
        raise BridgeError("名称是 Windows 保留设备名。")
    return name


def metadata(folder: Path) -> dict:
    text = (folder / "SKILL.md").read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        raise BridgeError("SKILL.md 缺少 YAML frontmatter。")
    # Only validate the common scalar fields; preserve the original YAML verbatim.
    fields = {}
    lines = match[1].splitlines()
    for index, line in enumerate(lines):
        m = re.match(r"^(name|description):\s*(.+?)\s*$", line)
        if m:
            value = m[2].strip()
            if value in ("|", ">", "|-", ">-", "|+", ">+"):
                block = []
                for following in lines[index + 1:]:
                    if following and not following[0].isspace():
                        break
                    block.append(following.strip())
                value = (" " if value.startswith(">") else "\n").join(block).strip()
            else:
                value = value.strip("\"'")
            fields[m[1]] = value
    if not fields.get("name") or not fields.get("description"):
        raise BridgeError("SKILL.md 必须包含 name 和 description。")
    valid_name(fields["name"])
    return fields


def inventory(folder: Path) -> dict[str, tuple[int, str]]:
    """Compare ALL files and empty directories, reject embedded reparse points."""
    result = {}
    if not folder.is_dir():
        raise BridgeError(f"不是有效目录：{folder}")
    for base, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            st = path.lstat()
            if linked(path) or getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise BridgeError(f"技能内部有链接或特殊重解析点，需先手动整理：{path}")
            rel = path.relative_to(folder).as_posix()
            if path.is_dir():
                result[rel + "/"] = (0, "directory")
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(chunk)
                result[rel] = (st.st_size, digest.hexdigest())
            else:
                raise BridgeError(f"不支持的文件类型：{path}")
    return result


def size(folder: Path) -> int:
    total = 0
    for base, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = [n for n in dirs if not linked(Path(base) / n)]
        for name in files:
            p = Path(base) / name
            if not linked(p):
                total += p.stat().st_size
    return total


def human(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


def make_link(target: Path, link: Path):
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Native PowerShell cmdlet, literal paths from environment, no cmd /c.
        env = dict(os.environ, SKILLBRIDGE_TARGET=str(target), SKILLBRIDGE_LINK=str(link))
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:SKILLBRIDGE_LINK -Target $env:SKILLBRIDGE_TARGET | Out-Null"],
            env=env, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode:
            detail = completed.stderr.decode("utf-8", errors="replace")
            raise BridgeError(f"创建目录链接失败：{link}\n{detail}")
    else:
        link.symlink_to(target, target_is_directory=True)
    if not linked(link) or link.resolve() != target.resolve():
        raise BridgeError(f"链接创建校验失败：{link}")


def remove_link(path: Path):
    if not linked(path):
        raise BridgeError(f"拒绝删除实体目录：{path}")
    if path.is_junction():
        path.rmdir()  # Removes the junction itself, never recurse into the target.
    else:
        path.unlink()


class Library:
    def __init__(self, home: Path | None = None, store: Path | None = None,
                 codex: Path | None = None, workbuddy: Path | None = None):
        self.home = (home or Path.home()).absolute()
        self.store = (store or self.home / ".agents/skills").absolute()
        codex_home = Path(os.environ.get("CODEX_HOME", str(self.home / ".codex"))) if home is None else self.home / ".codex"
        self.hosts = {"codex": (codex or codex_home / "skills").absolute(),
                      "workbuddy": (workbuddy or self.home / ".workbuddy/skills").absolute()}
        roots = [self.store.resolve(), *(p.resolve() for p in self.hosts.values())]
        for i, root in enumerate(roots):
            for other in roots[i + 1:]:
                if root == other or root in other.parents or other in root.parents:
                    raise BridgeError("共享库和两个软件的目录必须彼此独立、不能嵌套。")
        self.state = self.store.parent / ".skillbridge"

    @contextmanager
    def lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        lock = self.state / "write.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise BridgeError(f"另一个操作正在写入，或上次异常退出。确认无管理器运行后删除：{lock}")
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def skill(self, name: str) -> Path:
        return self.store / valid_name(name)

    def status(self, name: str, host: str) -> str:
        path = self.hosts[host] / name
        target = self.store / name
        if not lexists(path):
            return "未共享"
        if linked(path):
            if not path.exists():
                return "断链"
            return "已共享" if path.resolve() == target.resolve() else "链接到其他位置"
        return "独立副本" if path.is_dir() else "同名文件冲突"

    def rows(self) -> list[dict]:
        names = set()
        for root in [self.store, *self.hosts.values()]:
            if root.is_dir():
                names.update(p.name for p in root.iterdir() if not p.name.startswith(".") and (p.is_dir() or linked(p)))
        rows = []
        for name in sorted(names):
            target = self.store / name
            sources = [target, *(p / name for p in self.hosts.values())]
            source = next((p for p in sources if (p / "SKILL.md").is_file()), None)
            description, error = "", ""
            if source:
                try:
                    description = metadata(source)["description"]
                except (BridgeError, OSError, UnicodeError) as e:
                    error = str(e)
            else:
                error = "缺少 SKILL.md 或链接失效"
            rows.append({"name": name, "in_store": target.is_dir(),
                         "bytes": size(source) if source else 0,
                         "description": description, "error": error,
                         **{host: self.status(name, host) for host in self.hosts}})
        return rows

    def mount(self, name: str, hosts: list[str] | None = None):
        with self.lock():
            target = self.skill(name)
            metadata(target)
            paths = [self.hosts[h] / name for h in (hosts or list(self.hosts))]
            for p in paths:
                if lexists(p) and not (linked(p) and p.exists() and p.resolve() == target.resolve()):
                    raise BridgeError(f"已有同名内容，拒绝覆盖：{p}。完全相同的实体副本可使用「合并副本」。")
            created = []
            try:
                for p in paths:
                    if not lexists(p):
                        created.append(p)
                        make_link(target, p)
            except Exception:
                for p in reversed(created):
                    if linked(p):
                        remove_link(p)
                raise

    def detach(self, name: str, host: str):
        with self.lock():
            target = self.skill(name)
            path = self.hosts[host] / name
            if not lexists(path):
                return
            if not linked(path) or path.resolve() != target.resolve():
                raise BridgeError("只允许移除此共享库的链接；已有独立副本或其他链接不会被改动。")
            remove_link(path)

    def import_skill(self, source: Path) -> str:
        source = source.resolve(strict=True)
        name = metadata(source)["name"]
        with self.lock():
            target = self.skill(name)
            original = inventory(source)
            if lexists(target):
                if inventory(target) != original:
                    raise BridgeError("共享库已有不同内容的同名技能；请自行修改名称或整理版本。")
                return name
            self.store.mkdir(parents=True, exist_ok=True)
            staging = self.store / (".import-" + uuid.uuid4().hex)
            try:
                shutil.copytree(source, staging)
                if inventory(staging) != original:
                    raise BridgeError("复制校验失败，源文件可能正在修改。")
                staging.rename(target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        return name

    def plan(self, name: str) -> dict:
        target = self.skill(name)
        metadata_sources = [target, *(p / name for p in self.hosts.values())]
        real = [p for p in metadata_sources if lexists(p) and not linked(p)]
        if not real:
            if target.is_dir():
                return {"name": name, "source": str(target), "copies": [], "backup_bytes": 0}
            raise BridgeError("没有可合并的实体技能目录。")
        source = target if target in real else real[0]
        if metadata(source)["name"] != name:
            raise BridgeError("文件夹名和 SKILL.md 的 name 不一致，请先整理名称。")
        fingerprint = inventory(source)
        for p in real:
            if inventory(p) != fingerprint:
                raise BridgeError(f"同名技能内容不同，拒绝合并：{p}")
        for p in metadata_sources:
            if linked(p) and (not p.exists() or p.resolve() != source.resolve()):
                # A healthy canonical link may already point at store.
                if not target.exists() or not p.exists() or p.resolve() != target.resolve():
                    raise BridgeError(f"存在断链或其他位置的链接，请手动处理：{p}")
        copies = [p for p in real if p != source]
        return {"name": name, "source": str(source), "copies": [str(p) for p in copies],
                "backup_bytes": sum(size(p) for p in copies)}

    def consolidate(self, name: str) -> dict:
        """Move, never overwrite. Retain duplicates in reversible backup folders."""
        with self.lock():
            plan = self.plan(name)
            source, target = Path(plan["source"]), self.skill(name)
            transaction = uuid.uuid4().hex
            backup = self.state / "backups" / transaction
            moves, links = [], []
            self.store.mkdir(parents=True, exist_ok=True)
            backup.mkdir(parents=True)
            intended_moves = ([(source, target)] if source != target else []) + [
                (Path(text), backup / f"copy-{i}") for i, text in enumerate(plan["copies"])]
            intended_links = [root / name for root in self.hosts.values()
                              if not lexists(root / name) or root / name in [old for old, _ in intended_moves]]
            journal = backup / "transaction.json"
            pending = {"name": name, "status": "pending",
                       "moves": [[str(a), str(b)] for a, b in intended_moves],
                       "links": [str(p) for p in intended_links],
                       "backup_bytes": plan["backup_bytes"], "fingerprint": inventory(source)}
            # Record recovery paths before any mutation, including for process termination.
            journal.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                if source != target:
                    source.rename(target)
                    moves.append((source, target))
                for i, text in enumerate(plan["copies"]):
                    p = Path(text)
                    dest = backup / f"copy-{i}"
                    p.rename(dest)
                    moves.append((p, dest))
                for root in self.hosts.values():
                    p = root / name
                    if not lexists(p):
                        links.append(p)
                        make_link(target, p)
                record = {"name": name, "status": "complete", "moves": [[str(a), str(b)] for a, b in moves],
                          "links": [str(p) for p in links], "backup_bytes": plan["backup_bytes"],
                          "fingerprint": inventory(target)}
                journal.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                return {"transaction": transaction, **plan,
                        "note": "副本移入备份，尚未释放磁盘；验证两端可调用后可清理备份。"}
            except Exception:
                for p in reversed(links):
                    if linked(p):
                        remove_link(p)
                for old, new in reversed(moves):
                    if new.exists() and not lexists(old):
                        new.rename(old)
                if all(old.exists() and not linked(old) for old, _ in moves):
                    journal.unlink(missing_ok=True)
                if not any(backup.iterdir()):
                    backup.rmdir()
                raise

    def transactions(self) -> list[dict]:
        root = self.state / "backups"
        result = []
        if root.exists():
            for path in sorted(root.glob("*/transaction.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                result.append({"transaction": path.parent.name, **record})
        return result

    def transaction(self, ident: str) -> tuple[Path, dict]:
        if not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise BridgeError("无效事务编号。")
        folder = self.state / "backups" / ident
        record = json.loads((folder / "transaction.json").read_text(encoding="utf-8"))
        if record.get("status", "complete") != "complete":
            raise BridgeError(f"这是中断的合并，请根据日志手动检查并恢复：{folder}")
        name = valid_name(record["name"])
        allowed = {self.skill(name), *(root / name for root in self.hosts.values())}
        for old, new in record["moves"]:
            if Path(old) not in allowed or not (Path(new) == self.skill(name) or Path(new).parent == folder):
                raise BridgeError("备份记录含库范围外的路径。")
        if any(Path(p) not in allowed for p in record["links"]):
            raise BridgeError("备份链接记录不合法。")
        if linked(folder) or folder.resolve().parent != (self.state / "backups").resolve():
            raise BridgeError("备份路径已被重定向。")
        return folder, record

    def restore(self, ident: str):
        with self.lock():
            folder, record = self.transaction(ident)
            target = self.skill(record["name"])
            expected = {k: tuple(v) for k, v in record["fingerprint"].items()}
            if inventory(target) != expected:
                raise BridgeError("共享技能自合并后已变化，拒绝自动还原，以免丢失新内容。")
            paths = [Path(p) for p in record["links"]]
            for p in paths:
                if lexists(p) and (not linked(p) or p.resolve() != target.resolve()):
                    raise BridgeError(f"链接已被修改，拒绝还原：{p}")
            for old, new in record["moves"]:
                p = Path(old)
                if lexists(p) and p not in paths:
                    raise BridgeError(f"原路径已有内容：{p}")
                if not Path(new).exists() or inventory(Path(new)) != expected:
                    raise BridgeError("备份缺失或已变化，拒绝还原。")
            removed, restored = [], []
            try:
                for p in paths:
                    if lexists(p):
                        remove_link(p)
                        removed.append(p)
                for old, new in reversed(record["moves"]):
                    Path(new).rename(Path(old))
                    restored.append((Path(old), Path(new)))
            except Exception:
                for old, new in reversed(restored):
                    old.rename(new)
                for p in removed:
                    if not lexists(p):
                        make_link(target, p)
                raise
            (folder / "transaction.json").unlink()
            folder.rmdir()

    def purge(self, ident: str) -> int:
        with self.lock():
            folder, record = self.transaction(ident)
            target = self.skill(record["name"])
            expected = {k: tuple(v) for k, v in record["fingerprint"].items()}
            if inventory(target) != expected:
                raise BridgeError("共享库内容已变化，请先检查备份；拒绝自动清理。")
            released = 0
            for old, new in record["moves"]:
                p = Path(new)
                if p.parent == folder:
                    if linked(p) or inventory(p) != expected:
                        raise BridgeError("备份已变化，拒绝清理。")
                    released += size(p)
            # The resolved absolute deletion root has been validated above.
            shutil.rmtree(folder)
            return released


def main():
    parser = argparse.ArgumentParser(description="SkillBridge 共享技能管理器")
    parser.add_argument("--home", type=Path, help="隔离测试或其他用户目录")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--codex-dir", type=Path)
    parser.add_argument("--workbuddy-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("doctor")
    p = sub.add_parser("import"); p.add_argument("source", type=Path)
    p = sub.add_parser("mount"); p.add_argument("name")
    p = sub.add_parser("detach"); p.add_argument("name"); p.add_argument("host", choices=["codex", "workbuddy"])
    p = sub.add_parser("consolidate"); p.add_argument("name"); p.add_argument("--apply", action="store_true")
    sub.add_parser("backups")
    p = sub.add_parser("restore"); p.add_argument("transaction")
    p = sub.add_parser("purge"); p.add_argument("transaction"); p.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        lib = Library(args.home, args.store, args.codex_dir, args.workbuddy_dir)
        if args.command in ("list", "doctor"):
            result = {"store": str(lib.store), "hosts": {k: str(v) for k, v in lib.hosts.items()}, "skills": lib.rows()}
        elif args.command == "import":
            result = {"imported": lib.import_skill(args.source)}
        elif args.command == "mount":
            lib.mount(args.name); result = {"shared": args.name}
        elif args.command == "detach":
            lib.detach(args.name, args.host); result = {"detached": args.name, "host": args.host}
        elif args.command == "consolidate":
            result = lib.consolidate(args.name) if args.apply else lib.plan(args.name)
        elif args.command == "backups":
            result = lib.transactions()
        elif args.command == "restore":
            lib.restore(args.transaction); result = {"restored": args.transaction}
        elif args.command == "purge":
            result = {"released_bytes": lib.purge(args.transaction)} if args.apply else {"preview": lib.transaction(args.transaction)[1]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BridgeError, OSError, ValueError, subprocess.CalledProcessError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
