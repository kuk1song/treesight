<div align="center">

![treesight 的 logo：一棵小树，两个绿点表示做完，一个空心圈表示还没做完](docs/logo.svg)

# treesight

**一眼想起每个 AI 会话做了什么，还有什么没做完。**

[English](README.md) · **中文**

</div>

你是不是过了一段时间，就很难想起一个会话的整个过程和细节？可以试试 treesight :)

treesight 会读整个会话的内容，并生成一棵树：做完了什么、查清了什么、中间卡在哪，以及还没做完的事。它作为一个插件运行在你的 AI 里：没有服务器，不用注册账号，不用另配 API 密钥，页面不发任何网络请求。

https://github.com/user-attachments/assets/ce7f83e8-6201-4d57-95da-33a34c6fafb9

## 安装

在 Claude Code 2.1.275 及以上版本里运行：

```
/plugin install treesight --marketplace kuk1song/treesight
```

然后选择装在哪个范围。版本更早的话，先运行 `/plugin marketplace add kuk1song/treesight`，再运行 `/plugin install treesight@treesight`。

**想让编程代理帮你装**？请它在终端里运行下面这条（需要 Claude Code 2.1.292 及以上），装好后你自己运行 `/reload-plugins`，或者开一个新会话：

```
claude plugin install treesight --marketplace kuk1song/treesight
```

它在你自己电脑上的 Claude Code 里使用：终端里实测过；桌面端的 Code 页签和 IDE 扩展应该也能用，但没测过。云端会话、Cowork、claude.ai 聊天和其他编程代理里不能用（[详细说明](docs/design.md#5-delivery)，英文）。

treesight 还需要 3.9 及以上的 `python3`（Apple 命令行工具里的就行），系统是 macOS 或 Linux；Windows 没测过。在 Claude Code 2.1.299 上测过。这类插件市场默认不自动更新：可以在 `/plugin` 里打开自动更新，或者运行 `claude plugin update treesight@treesight`，再运行 `/reload-plugins` 或开一个新会话。

## 用法

打开想看的会话（比如用 `claude --resume`），运行：

```
/treesight:treesight
```

几秒内 treesight 会请浏览器打开页面；后台跑完后，会话的树就出现在页面上，多数会话要几分钟。这期间你可以接着干活。同一个对话里之后的运行和修改，会更新这个已打开的页面，不再开新标签页。

- **画同一项目的别的会话**：在命令后加它的 id 或标题里的词（顺序不限），如 `/treesight:treesight 0a182a7b` 或 `/treesight:treesight release`。项目页列出项目里的会话：点一个还没生成树的会话，能看到它的摘要，以及两个链接，会打开 Claude Code 并填好生成树或接着这个会话的命令。
- **再运行一次**只读新增的内容。上一次还没跑完时再运行，这一次会在前台跑，你的对话要等它做完。如果你中途停掉了一次运行，加上 `--restart` 就能重新开始画这个会话。
- **手动改页面**：`/treesight:treesight close <条目名称里的词>`，或 `reopen`、`hide`、`set <条目> when=旅行回来后`（可改的字段：label、line、kind、due、when、who、rank、score、blocked_by）。你改的永远优先。

## 怎么工作

1. **读取**：脚本读 `~/.claude/projects` 里的会话记录，不用模型；剔除常见的密钥格式，给 IPv4 地址和邮箱打码。
2. **提炼**：一个后台子 agent 用你自己的模型和账号挑出节点和没做完的事，不动你当前的对话。每一条都要带一段从会话里原样抄来的话。它还会给项目里需要摘要的其他会话各写一句摘要，依据是每个会话的一小段内容。
3. **核对并保存**：脚本逐字核对每段原话确实出现在它引用的那条消息里，再追加到本地的账本里。下次只读新增的内容；模型拿不准一件事是否已经办完时，会留给你确认。
4. **画页面**：脚本给每个项目生成一个静态页面，这一步不用模型。

skill 只预先放行两件事：运行它自己的脚本，以及把结果写进 `~/.cache/treesight`。它要做别的事，照你平时的权限设置处理。哪些内容会缩短、核对哪些东西、每个文件放在哪里，见 [docs/design.md](docs/design.md)（英文）。

## 隐私

- 页面不发任何网络请求。它的内容安全策略只运行页面自己的脚本（按哈希放行）和这段脚本加载的文件，而它只加载页面旁边一个一行的版本文件，已打开的页面靠它知道有了新结果。会话里的文字放在不执行的块里，不会被当成代码运行。
- 摘录，以及为写摘要截取的项目里其他会话的一小段内容，交给模型的方式和你平时的对话一样：同一个账号、同一个服务商，交出去之前已剔除常见密钥格式，IPv4 地址和邮箱已打码。
- treesight 不往别处发送任何东西。它的账本（默认在 `~/.local/share/treesight/`）在卸载插件后仍然保留；删掉这个文件夹和 `~/.cache/treesight`，就删掉了 treesight 留下的内容。

## 用时和花费

提炼算在你的 Claude Code 用量里。treesight 优先把没做完的事找全，其次才是快，所以用 xhigh 思考强度，模型跟你的会话一样。2026-10-16 用 Opus 5.5 实测，按 API 价折算：15 次提问的会话用了 3.1 分钟（0.64 美元）；73 次提问、7 次压缩的会话用了 21 分钟（8.50 美元），会话自己最后一份待办清单里的 17 件事全部找到。同一个会话以后再跑只读新增的部分；没有新内容时，也要几次很短的模型请求（实测约 20 秒）。项目里第一次运行还会给其他会话写摘要：2026-10-23 有 14 个其他会话时，一个 9 次提问的会话用了 7.0 分钟（2.07 美元）；同一个会话 2026-10-21 用了 5.6 分钟（1.25 美元），那时还没有摘要。各测一次。全部测量见 [docs/design.md](docs/design.md#6-known-limits-and-what-remains-to-verify)。

## 局限

- 提炼结果不确定，所以账本保留第一次的结果，不会每次重画。
- 页面要等模型的第一次回复才打开；实测有一次等了 3.4 分钟。
- 每次运行的报告会回到你的对话里，那边的 Claude 可能会评论几句，或者自己去核对。
- 还没生成树的会话，摘要是根据一小段内容写的，可能不准，所以标了 AI。
- 打开 Claude Code 的链接要靠它的 `claude-cli://` 处理程序，Claude Code 在你第一次交互提问时注册它；没有打开时，页面会提供命令让你复制。用 `claude -p` 或 Agent SDK 跑的会话，生成树之后才列出。
- 会话记录的格式是 Claude Code 内部的，任何版本都可能变。
- 页面只有深色主题。
- 已打开的页面自动更新，只在 Chrome 里测过；Safari 和 Firefox 没测过。

其余局限和具体数字见 [docs/design.md](docs/design.md#6-known-limits-and-what-remains-to-verify)。

<details>
<summary><b>和同类工具比</b>（2026-10-15 核对）</summary>

| 工具 | 做了什么 | treesight 多做的 |
|---|---|---|
| Claude Code 的 agent view、桌面版侧栏、Projects | 显示每个会话此刻的状态：进行中、要你处理、已完成。Projects 的「Waiting on you」只管云端线程。 | 从会话记录里提炼每个会话做完了什么，以及跨会话还没做完的事。 |
| [loose-ends](https://github.com/MiguelProz/claude-loose-ends) | Claude Code 的 mod：从当前对话里提出没收尾的事，要求原样引用；只有你确认、并附上证明它已办完的那句话时才关掉。 | 同样的原话规则，覆盖一个项目的所有会话；外加在等谁、等了多久、被什么挡住，以及会话树。 |
| [openloops](https://github.com/thorwhalen/openloops) | 从 GitHub issue 列出欠着和被挡住的事并带天数；会话摘要不用模型。 | 待完成取自会话里说过的话。 |
| [alluvia](https://github.com/dylanp12/alluvia) | Claude Code 插件：提炼带原话的决定，原话按字符串核对；列出没解决的问题；用你配置的模型服务和 API 密钥。 | 每个会话一棵树和整个项目的待完成清单，直接用 Claude Code 本身。 |
| [context-visualizer](https://github.com/Abudulaz/context-visualizer) | 从会话记录画出带类型的里程碑，能连回原文；要 OpenRouter 密钥。 | 待完成清单，也不用另配密钥。 |

</details>

## 求助

问题、建议和 bug：[开一个 issue](https://github.com/kuk1song/treesight/issues/new/choose)；bug 表单会提醒你不要贴会话里的任何内容。安全问题见 [SECURITY.md](SECURITY.md)。

## 参与贡献

测试、检查、PR 和发版流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，设计和理由见 [docs/design.md](docs/design.md)（两份都是英文），数据格式见 [schema/](schema/)。

## 许可证

[MIT](LICENSE)。treesight 是独立项目，与 Anthropic 没有关联，也未获其认可。
