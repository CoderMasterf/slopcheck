# slopcheck

> AI 写的代码，交付前先体检。单文件、零依赖、只读不写。

`slopcheck` 扫一个目录，告诉你这份代码里有多少**客户第一眼就会发现**的破绽，
每一条都带 `文件:行` 的证据。它不管审美、不管架构，只查能被机器验证的东西：
残留、缺失、矛盾。

```
得分  3 / 100   等级 D
结论  建议退回重做

[严重] 硬编码密钥/口令  (2 处)
    app.py:5      OPENAI_KEY = "sk-proj-..."
    server.js:14  const password = "admin123";
    客户可见: 交付后约 1 天

[较高] README 里的命令跑不通  (2 处)
    README.md:14  npm run dev（package.json 里没有这个 script）
    README.md:20  python train.py（文件不存在）
```

## 为什么做这个

2026 年的普遍情况：项目能跑，但一交付就露馅。原因高度集中在少数几类可被机器发现的痕迹上——
占位符没填、假数据没删、README 里的命令抄下来就报错、`catch (e) {}` 空的、密钥写死在代码里。

这些问题不需要再“思考”一遍，它们只需要被**逐条列出来**，并且每条都附上证据。

## 创新点：交付基线（baseline）

同类工具的通病是“每次都把历史债重新报一遍”，于是第二周就没人看报告了。

`slopcheck` 的做法是：把当前状态存成基线，以后**只报基线之后新增的破绽**。

```bash
# 接手 / 首次导入时，先把现有问题存成基线（允许它存在）
python slopcheck.py . --save-baseline

# 之后每次交付前，只看“这次新欠的债”
python slopcheck.py . --baseline
```

```
得分  42 / 100   等级 C
基线  新增 2 处 / 已修 7 处 / 分数 27 -> 42

[较高] 静默吞异常  (1 处)
    api/handler.js:84  } catch (e) {}
```

这让它从“一次性体检”变成了**回归检测**：可以挂进 CI，卡住“这次 PR 新增的破绽”，
而不是要求一个老项目一天之内变干净。

另外两个设计选择：

- **客户可见天数**：每条问题会标“交付后约几天会被发现”。密钥是 1 天，没测试是 30 天——
  优先级不靠感觉，靠这个刻度。
- **安全修复只做零判断的事**：`--fix` 只会补 `.gitignore`、生成 `.env.example`，
  其余一概不碰。会改变逻辑的修复，工具不代劳。

## 下载与安装

不需要 pip，也不需要虚拟环境。Python 3.8+，只用标准库。

**方式一：直接下载单文件（推荐）**

```bash
curl -L -o slopcheck.py https://raw.githubusercontent.com/CoderMasterf/slopcheck/main/slopcheck.py
python slopcheck.py --version
```

**方式二：克隆仓库（含规则文档和演示项目）**

```bash
# HTTPS
git clone https://github.com/CoderMasterf/slopcheck.git
# SSH（已配好密钥时）
git clone git@github.com:CoderMasterf/slopcheck.git

cd slopcheck
python slopcheck.py demo
```

**方式三：Windows 用户**

在 [Releases](https://github.com/CoderMasterf/slopcheck/releases) 下载 zip，解压后：

```powershell
python .\slopcheck.py .\你要扫的目录
```

## 使用

```bash
python slopcheck.py .                    # 体检当前目录
python slopcheck.py ./my-project --md    # Markdown 报告，适合贴进文档/PR
python slopcheck.py . --json             # 机器可读，适合接 CI
python slopcheck.py . --color            # 彩色终端输出
python slopcheck.py . --exclude demo     # 跳过 demo 这类目录，可重复传
```

| 参数 | 作用 |
|---|---|
| `path` | 要扫的目录，默认 `.` |
| `--md` | 输出 Markdown 报告 |
| `--json` | 输出 JSON（含 score / grade / findings / stats） |
| `--color` | 终端彩色 |
| `--exclude SUBSTR` | 跳过路径包含该字符串的文件，可重复 |
| `--save-baseline [FILE]` | 存基线，默认 `.slopcheck-baseline.json` |
| `--baseline [FILE]` | 只报基线之后新增的破绽 |
| `--fix` | 列出可安全自动修复的项（只预演） |
| `--fix --apply` | 真正写入 |

退出码：`0` 正常，`1` 路径不存在或基线损坏。CI 里建议自己解析 JSON 决定是否卡住。

## 规则列表

| 等级 | 规则 id | 检查内容 | 客户可见 |
|---|---|---|---|
| 严重 | `secret` | 硬编码密钥/口令（sk-\*/ghp_\*/AKIA\*/私钥头/`password="..."`） | 1 天 |
| 严重 | `envcommit` | 存在 `.env` 但 `.gitignore` 没覆盖它 | 1 天 |
| 严重 | `pkgjson` | `package.json` 无法解析 | 1 天 |
| 较高 | `placeholder` | `YOUR_API_KEY`、`<your-key>`、`xxx`、`请替换` 没填 | 1 天 |
| 较高 | `readmefake` | README 里的 `npm run X` / `python Y.py` 实际不存在 | 1 天 |
| 较高 | `silent` | `except: pass`、`catch (e) {}` | 7 天 |
| 较高 | `nolock` | 有 `package.json` 却没任何 lock 文件 | 7 天 |
| 较高 | `noreadme` | 无 README 或有效行数 < 12 | 7 天 |
| 较高 | `notests` | 没有任何测试文件 | 30 天 |
| 中等 | `fake` | `example.com`、`test@example.com`、`张三` 等假数据留在业务代码 | 3 天 |
| 中等 | `debug` | `print(` / `console.log` 密集残留 | 7 天 |
| 中等 | `dupfunc` | 同名函数重复定义（复制粘贴痕迹） | 7 天 |
| 中等 | `localhost` | 本地地址硬编码 4 处以上 | 14 天 |
| 中等 | `debloat` | `dependencies` 超过 30 个 | 14 天 |
| 中等 | `nolicense` | 没有 LICENSE | 30 天 |
| 中等 | `nogitignore` | 没有 `.gitignore` | 7 天 |
| 中等 | `commentheavy` | 注释占比 > 35%（解释性废话） | 30 天 |
| 提示 | `aicomment` | “This function...”、“Note that”、“Here we” 这类 AI 腔注释 | 30 天 |
| 提示 | `todo` | TODO/FIXME 5 处以上 | 30 天 |
| 提示 | `giant` | 单文件超 800 行 | 30 天 |

## 评分怎么算的

100 分起扣：严重 -12、较高 -6、中等 -3、提示 -1，**每条规则最多计 3 次**。
所以单一规则（比如满屏 `console.log`）不会把分数拉到 0，真正拉低分数的是“多种问题同时存在”。

| 分数 | 等级 | 含义 |
|---|---|---|
| 90-100 | S | 可以交付 |
| 75-89 | A | 细节卫生问题 |
| 60-74 | B | 能跑，但一交付会挨骂 |
| 40-59 | C | 这是原型，不是交付物 |
| 0-39 | D | 建议退回重做 |

## 挂进 CI

仓库自带 `.github/workflows/slopcheck.yml`：PR 里自动跑测试、把报告写进 Step Summary，
出现 `critical` 就失败。自己的项目里最小可用版本：

```yaml
- name: slopcheck
  run: |
    curl -sL -o slopcheck.py https://raw.githubusercontent.com/CoderMasterf/slopcheck/main/slopcheck.py
    python slopcheck.py . --json > report.json
    python -c "import json,sys;d=json.load(open('report.json'));sys.exit(1 if d['score']<60 else 0)"
```

老项目建议先 `--save-baseline` 把存量债圈起来，CI 里用 `--baseline` 只卡新增。

## 维护

详细流程（规则怎么加、误报怎么处理、发版 checklist）见 [MAINTAINING.md](MAINTAINING.md)。

日常只需要记住三件事：

1. 改规则必须同时改 `tests/` 里的断言，否则 CI 会红。
2. 误报优先修规则，不要靠 `--exclude` 绕过去。
3. 版本号语义化：加规则 = minor，改输出格式 = major。

跑一遍自测：

```bash
python -m unittest discover -s tests -v
python slopcheck.py . --exclude demo
```

## 局限（说在前面）

- 正则规则会误报，尤其是扫工具类项目自己的源码时。
- 只覆盖 Python / JS / TS 等常见语言的表层痕迹，不做类型检查。
- 它不是 linter，不替代 `ruff` / `eslint` / `mypy`；它查的是“交付前的态度问题”。

## 许可

MIT。随便用，但出事了别找我。
