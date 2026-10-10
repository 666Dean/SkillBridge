# SkillBridge：Codex × WorkBuddy 共享技能库

Windows 本地桌面软件，中文图形界面，也提供命令行。Python 3.12 或更高版本，使用标准库，无第三方依赖、无后台服务、无网络请求。


> 项目状态：可运行的 Python 源码便携版。已完成 14 项 Windows 文件系统集成测试和 Tk 界面启动、搜索、详情自检。尚未在 Codex / WorkBuddy 客户端完成实际技能任务的端到端测试。

**目标：减少重复的技能文件和维护成本。共享目录不合并两个软件的运行内存。**

| 功能 | 行为 |
| --- | --- |
| 导入技能 | 复制到共享库，保留来源，不运行安装脚本 |
| 共享到两端 | 建立目录链接，不复制第二份技能文件 |
| 合并副本 | 逐文件 SHA-256 校验，仅合并完全相同的副本 |
| 备份与还原 | 保留旧副本，变化时拒绝覆盖 |
| 清理备份 | 用户确认后永久删除旧副本，释放磁盘空间 |
| 搜索与检查 | 查看元数据、共享状态、冲突和断链 |

## 启动

安装带 Tkinter 的 Python 3.12 或更高版本。下载此仓库 ZIP 并解压，双击 **Launch.cmd**，或在此文件夹运行：

```powershell
python app.py
```

这是可运行的源码便携版，不是独立 EXE。在另一台机器使用时，需要安装带 Tkinter 的 Python 3.12+，解压整个文件夹后启动。管理器关闭后，两个软件仍然直接访问共享 skill，无需一直运行 SkillBridge。

## 工作方式

```text
%USERPROFILE%\.agents\skills\my-skill\       唯一的共享实体文件
    ├── SKILL.md
    ├── scripts\
    └── references\

%USERPROFILE%\.codex\skills\my-skill         目录链接 → 共享实体
%USERPROFILE%\.workbuddy\skills\my-skill     目录链接 → 共享实体
```

Windows 使用 NTFS Junction，通常无需管理员权限；不支持的文件系统或系统策略会明确报错，不会退回成复制。通过任何一端链接编辑文件，另一端看到同一份内容。不要在宿主软件中选择“卸载并删除文件”来停用共享技能：外部软件可能对链接目标递归删除。请用 SkillBridge 的“取消共享”，或用软件自身的启用开关。

默认使用 `.codex/skills` 兼容目录，并尊重 `CODEX_HOME` 环境变量。如果已有 skillctl，SkillBridge 复用 `.agents/skills` 实体库，使用独立 `.agents/.skillbridge` 备份和锁，不修改 skillctl 的安装记录。不要同时运行两个管理器的写操作。

当前 Codex 官方文档的用户目录为 `~/.agents/skills`，并支持链接技能目录。兼容目录 `.codex/skills` 的实际发现行为应以安装版本为准；请检查你的 Codex 版本是否扫描该兼容目录。如果新版已直接扫描共享实体库且出现重复技能卡片，可以在确认后取消 Codex 兼容链接，保留 `.agents/skills` 实体。目录设置也可改成实际被宿主扫描的其他独立目录。

## 日常使用

1. **检查现有技能**：启动自动扫描共享库和两端目录；支持搜索、查看状态与描述。
2. **导入新技能**：选择直接包含 `SKILL.md` 的文件夹。复制到共享库，保留原来源文件。选中后点击“共享到两端”。
3. **减少现有重复文件**：选中技能，点击“合并副本”。先显示计划，再核对每一个文件的 SHA-256 和目录结构；内容不同则拒绝合并。
4. **验证实际调用**：在两端技能列表找到技能；必要时重新打开软件。在 Codex 使用技能选择器或 `$技能名`，在 WorkBuddy 使用技能选择器或自然语言指定技能，执行一次实际任务。
5. **释放空间**：合并时原副本移到备份区，磁盘空间暂未释放。两端验证成功后，到“合并备份”页清理旧副本。共享实体保留，旧副本永久删除。
6. **还原**：尚未清理备份时可以还原。共享文件或原目录已变化会拒绝自动还原，以免覆盖新内容。
7. **取消共享**：只删除所选软件的目录链接；实体文件仍保留。

导入是非破坏性复制，不会自动删除来源文件。如需把现有宿主目录里的技能迁入共享库，请使用“合并副本”；从下载目录导入后，来源包可由你另行清理。

## 能节省什么

- 减少重复的技能文件、脚本、模板和依赖目录占用的**磁盘空间**；新安装到共享库的技能只需一份。
- 不会合并 Codex 和 WorkBuddy 的进程内存，不保证降低 RAM 或模型上下文消耗。
- 管理器本身不常驻，不执行技能脚本、不安装依赖、不联网、不读取聊天数据库或 API Key。

## 兼容性与边界

两个软件均使用 `SKILL.md`，但共享文件不等于所有工作流都能跨宿主运行。使用 Codex 专属工具、WorkBuddy 专属连接器、绝对路径、登录凭据或特定 Python/Node 环境的技能，需要分别配置或适配。此工具保留原技能全文，不擅自改写指令或自动执行安装脚本。

WorkBuddy 官方公开资料确认 `SKILL.md` 包结构，但未明确承诺所有版本都自动发现 Junction。工具创建 WorkBuddy 用户技能目录下的 Junction；仍需在当前 WorkBuddy 版本实际验证技能列表和调用。工具不改 WorkBuddy 数据库、启用状态或缓存。

系统自带技能、插件缓存、市场元数据和其他隐藏目录不做迁移。顶层名称要求为小写英文、数字及连字符，内部链接/重解析点拒绝导入或合并。不同盘符之间的原子移动可能失败；会报告错误并回退已完成的步骤，请把共享库放在同一盘符。大小显示是文件逻辑字节数，不等于实际磁盘分配字节。

正常异常会执行回退；进程被强制终止或断电时不保证自动恢复。合并与还原时请关闭相关任务，避免宿主并发更新。异常退出后，先检查原目录、共享库与 `.agents/.skillbridge/backups`，确认没有写操作运行后再移除 `.agents/.skillbridge/write.lock`。备份清理是不可撤销的。

## 命令行

```powershell
python bridge.py list
python bridge.py doctor
python bridge.py import "D:\Downloads\my-skill"
python bridge.py mount my-skill
python bridge.py consolidate my-skill          # 仅预览
python bridge.py consolidate my-skill --apply  # 执行合并
python bridge.py backups
python bridge.py restore 事务编号
python bridge.py purge 事务编号                # 仅预览
python bridge.py purge 事务编号 --apply        # 永久清理备份
python bridge.py detach my-skill workbuddy
```

命令行不会读取图形界面的 `settings.json`。自定义目录需用 `--store`、`--codex-dir` 和 `--workbuddy-dir`，放在子命令之前。`doctor` 与 `list` 均为只读，输出路径、状态及元数据错误，不代表已完成宿主调用测试。

## 验证

```powershell
python -m unittest -v test_bridge
```

集成测试使用临时隔离用户目录，覆盖真实 Windows Junction、两端读取同一文件、同名冲突、合并、还原、清理、故障回退、并发锁、路径边界与备份篡改。不会改现有软件目录。

## 参考资料

- [Codex 官方：Build skills](https://learn.chatgpt.com/docs/build-skills)
- [WorkBuddy 官方：Skill 包结构](https://open.workbuddy.cn/en/docs/skill)

MIT License，见 LICENSE。
