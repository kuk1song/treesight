# treesight

[English](README.md) | **中文**

把 Claude Code 的会话画成树来看:每个会话做完了什么、查清了什么,整个项目还有什么没完。

会话一多,三周前那个会话定下了什么、还欠着什么,就很难想起来。treesight 读你本机的会话记录,让 Claude 挑出每个会话的地标(做完的事、查清的事、中间卡在哪)和没完的事(你来办的,或在等别人的),画在一个本地页面上。整个项目所有会话的待完成汇成一张清单:在等谁、等了几天、哪些过期了、哪件挡住了哪件。

> [!NOTE]
> 非官方,与 Anthropic 无关。早期版本:只在 Claude Code 里用,只有深色。

<p align="center">
  <img src="docs/demo-tree.png" alt="一个会话画成的树:树干上四个节点;其中一个展开,显示中间卡了约 1.5 小时,并列出带时刻的三行(卡在、应对、结果);较早的一个发现被后来的节点推翻,划掉了" width="760">
</p>
<p align="center">
  <img src="docs/demo-open.png" alt="项目视图与待完成抽屉:按已失效、待你确认、after the trip、没定时间分段;一件等待的事写着先放着、已 35 天" width="760">
</p>
<p align="center"><sub>本仓库里编造的示例项目(<code>docs/demo.html</code>,由 <code>dev/make_sample.py</code> 生成),2026-10-20 截图,天数按那天算。截图是英文界面;浏览器首选中文时页面自动用中文。</sub></p>

## 快速开始

1. 在 Claude Code 里装插件:

   ```
   /plugin marketplace add kuk1song/treesight
   /plugin install treesight@treesight
   ```

   Claude Code 2.1.275 及以上可以一步装好:`/plugin install treesight --marketplace kuk1song/treesight`。

2. 在想看的会话里运行:

   ```
   /treesight:treesight
   ```

   几秒后(实测 7 到 12 秒)页面打开,先显示已有的内容,并写明这个会话正在生成。提炼在后台跑,你可以接着干活;页面会自己刷新,生成完就显示新的树。如果上一次还没跑完你又运行 `/treesight:treesight`,Claude Code 会让第二次在前台跑,你的对话要等它做完。

3. 画同一项目的别的会话,在后面加它的 id 或标题里的词:`/treesight:treesight 0a182a7b` 或 `/treesight:treesight release`。还没生成树的会话在项目页上会写明要运行的命令。

4. 手动改页面:`/treesight:treesight close <条目里的词>`,或 `reopen`、`hide`、`set <条目> when=旅行回来后`(可改的字段:label、line、kind、due、when、who、rank、score、blocked_by)。你改的永远优先于提炼的结果。

需要 Claude Code(在 2.1.299 上测过)、3.9 及以上的 `python3`(macOS 自带的就行)、macOS 或 Linux。Windows 没测过。

## 怎么工作

1. **读取。** 脚本读 `~/.claude/projects` 里这个会话的记录,不用模型;剔除常见的密钥格式,给 IPv4 地址和邮箱打码,写成一份摘录:提问、回复、自动回顾和压缩摘要。原文不截断,只有粘贴进来的内容(留前 400 字)、压缩摘要(留要紧的小节,最多 8000 字)和单条就比一整份摘录还长的内容会缩短,摘录里写明。treesight 自己的命令,以及你的对话处理它的报告的那一轮,不算进去。
2. **提炼。** skill 在单独的子 agent 里跑,不动你当前的对话,用的模型和账号就是你的 Claude Code。skill 只预先放行两件事:运行 treesight 自己的脚本(摘录也由它输出给子 agent 读),以及把结果写进 `~/.cache/treesight`。它要做别的事,照你平时的权限设置处理。它新增的每个节点和每件待完成都要带一段从会话里原样抄来的话;它也可以建议关掉某件待完成,同样要带原话。
3. **核对并保存。** 保存前,脚本先按 JSON Schema 检查输出,再逐字核对每段原话确实出现在它引用的那条消息里。结果写进一个只追加的账本:存进去的就不再变,下次只读新增的消息。没把握的关闭和看起来已经办不了的事,留给你确认。条目提出之前说的话不能用来关掉它。如果先画了较新的会话、后补画较早的会话,较早会话新增的条目会和较新会话记下的结果对一遍,因为那几次运行没见过这些条目。
4. **画页面。** 脚本从账本给每个项目生成一个静态 HTML 页面,这一步不用模型。

文件在哪:账本在 `~/.local/share/treesight/`(或 `$XDG_DATA_HOME/treesight`,或 `$TREESIGHT_HOME`),卸载插件也不会删。账本还记着每个会话的标题和时间,所以 Claude Code 删掉旧记录后(默认 30 天),这个会话照样留在页面上。页面在插件的数据目录,卸载时 Claude Code 会删掉,可以重新生成。生成进行中,摘录和提炼结果在 `~/.cache/treesight/work/`(或 `$TREESIGHT_WORK`,但那样 Claude Code 写入前会问你),写进账本后就删掉。这些文件都只有你能读。

## 花费

提炼和别的请求一样,算在你的 Claude Code 用量里。treesight 优先把没完的事找全,其次才是快和省,所以不管你的会话用什么思考强度,这个 skill 都用 xhigh(只有环境变量 `CLAUDE_CODE_EFFORT_LEVEL` 能改它);模型跟你的会话一样。用时几乎全花在模型的思考和写出提炼结果上,每秒约输出 110 个 token。2026-10-16 用 Opus 5.5、xhigh 思考强度完整跑,在手动权限模式下没有一次权限被拒,按 API 价折算:

| 会话 | 用时 | 花费 |
|---|---|---|
| 编造的示例,15 次提问 | 3.1 分钟 | 0.64 美元 |
| 一个真实会话,4 次提问 | 4.0 分钟 | 0.97 美元 |
| 一个真实会话,73 次提问、7 次压缩,分两段读 | 21 分钟 | 8.50 美元 |

在那个 73 次提问的会话上,会话自己最后一份待办清单里的 17 件事全部找到(16 件由脚本对上,第 17 件措辞不同,人工核对;这份清单本身还没有人工复核),还找回了那份清单漏掉的更早的事。之前的版本把每条提问和每轮最后的回复截到 1500 字、其余回复截到 500 字,在一个 8 次提问的真实会话上漏了 8 件待完成,现在的版本都找到了。用之前的版本时,降低思考强度或换小模型,17 件只找到 3 到 10 件。同一个会话以后再跑,只读新增的部分。重画页面不用模型。

## 隐私

- 页面不发任何网络请求。它的内容安全策略不放行任何网络访问,脚本只放行页面自己的那一段;数据放在不执行的块里,会话里的文字不会被当成代码运行。
- 摘录交给模型的方式和你平时的 Claude Code 对话一样:同一个账号、同一个服务商。交出去之前已剔除常见密钥格式,IPv4 地址和邮箱已打码。
- treesight 不往别处发送任何东西。

## 和同类比

2026-10-15 按各项目自己的 README 或文档核对。

| 工具 | 做了什么 | treesight 多做的 |
|---|---|---|
| Claude Code 的 agent view、桌面版侧栏、Projects | 显示每个会话此刻的状态:进行中、要你处理、已完成。Projects 的「Waiting on you」只管云端线程。 | 从会话记录里提炼每个会话做完了什么,以及跨会话还没完的事。 |
| [loose-ends](https://github.com/MiguelProz/claude-loose-ends) | Claude Code 的 mod:从当前对话里提出没收尾的事,要求原样引用;只有你确认、并附上证明它已办完的那句话时才关掉。 | 同样的原话规则,覆盖一个项目的所有会话;外加在等谁、等了多久、被什么挡住,以及会话树。 |
| [openloops](https://github.com/thorwhalen/openloops) | 从 GitHub issue 列出欠着和被挡住的事并带天数;会话摘要不用模型。 | 待完成取自会话里说过的话。 |
| [alluvia](https://github.com/dylanp12/alluvia) | Claude Code 插件:提炼带原话的决定,原话按字符串核对;列出没解决的问题;用你配置的模型服务和 API key。 | 每个会话一棵树和整个项目的待完成清单,直接用 Claude Code 本身。 |
| [context-visualizer](https://github.com/Abudulaz/context-visualizer) | 从会话记录画出带类型的里程碑,能连回原文;要 OpenRouter 密钥。 | 待完成清单,也不用另配密钥。 |

## 局限

- 提炼结果不确定。用之前的版本在同一个大会话上跑两次,约 70% 的节点相同,待完成一次列了 27 件、一次 38 件。账本保留第一次的结果,不会每次重画。
- 一份摘录最多 15 万字;新内容更多时分段读,一次运行最多读两段,下一次运行接着读。
- 每次运行的报告会回到你的对话里。treesight 请那边的 Claude 不要据此行动,但它仍可能评论几句。
- 页面由后台运行的第二步打开,所以要等模型的第一次回复。实测有一次那次回复中途断开,Claude Code 重新请求,页面 3.4 分钟后才打开。
- 先画较新的会话、后补画较早的会话时,只能对照较新会话记成节点或关闭的内容。它们办完了却没记下的小事,会一直留在清单上,要你自己关掉。
- 会话记录的格式是 Claude Code 内部的,任何版本都可能变;所有读取都集中在 `scripts/transcript.py`。
- 页面自己不能提炼:要在 Claude Code 里运行命令,再刷新页面。
- 只有深色。Windows 没测过。

## 开发

测试、检查、PR 和发版流程见 [CONTRIBUTING.md](CONTRIBUTING.md)(英文)。设计和理由见 [docs/design.md](docs/design.md),数据格式见 [schema/](schema/)。

## 许可证

[MIT](LICENSE)
