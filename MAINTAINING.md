# 维护手册

这份文件写给未来接手的人（包括三个月后的你自己）。

## 目录结构

```
slopcheck.py              主程序，单文件，不许拆（单文件是产品卖点）
tests/test_slopcheck.py   冒烟测试
demo/                     故意写脏的演示项目（分数 3/100），用来回归
.github/workflows/        CI
```

## 加一条规则的步骤

1. 先确定它能被**客观验证**。需要“看情况”的，不要加。
2. 在 `slopcheck.py` 里写 `check_xxx(ctx, f)`，用 `ctx.hit()` 上报，必须带 `rel` 和行号。
3. 在 `run()` 的循环里注册它。
4. 在 `CLIENT_DAYS` 里给它一个“客户可见天数”；没想清楚就写 7。
5. 在 `README.md` 的规则表里补一行。
6. 在 `demo/` 里造一个会被命中的例子，并在 `tests/` 加断言。
7. 本地跑：

```bash
python -m unittest discover -s tests -v
python slopcheck.py demo --exclude nothing
```

## 误报怎么处理

误报是这类工具的死因，处理顺序不能反：

1. **先确认是不是真误报**。把 `文件:行` 拿出来看，别凭印象。
2. 如果是“规则定义行/注释里的示例”，用 `is_pattern_line()` / `is_comment_line()` 排除。
3. 如果是“上下文相关”（比如测试文件里的假数据），用 `is_test` 或路径判断排除。
4. 实在没法自动区分，就**降级**（critical → medium）而不是删规则。
5. 删规则是最后手段，且要在 CHANGELOG 里写清楚为什么。

不要用 `--exclude` 在 README 里教用户绕过误报——那等于承认工具不准。

## 发版流程

1. 改 `VERSION`，同步 `CHANGELOG.md`。
2. `python -m unittest discover -s tests -v` 全绿。
3. `python slopcheck.py . --exclude demo` 必须是 S（自己的仓库不能脏）。
4. `python slopcheck.py demo` 分数应该稳定在 3 左右；飘了说明规则行为变了，要确认是有意的。
5. 打 tag：`git tag v0.3.0 && git push origin v0.3.0`。
6. 在 Releases 里写“新增/变更/修复”三段。

版本号规则：

- 加规则、加参数 → minor（0.3.0 → 0.4.0）
- 修误报、改文案 → patch（0.3.0 → 0.3.1）
- 改 JSON 结构或计分方式 → major（0.x → 1.0）

## 基线文件

`.slopcheck-baseline.json` 默认不进版本库（已在 `.gitignore` 里）。
团队协作时建议把它提交进仓库，并在 PR 里 review 它的变化——
基线被“改小”往往意味着有人偷偷删了记录。

## 支持矩阵

| 项 | 要求 |
|---|---|
| Python | 3.8+，仅标准库 |
| 操作系统 | Windows / macOS / Linux（只用 `pathlib` 和 `os.walk`） |
| 代码规模 | 单文件上限 1.5MB、2 万行，超过就跳过 |
| 编码 | UTF-8，读不了就用替换字符继续 |

## 已知不做的事

- 不调模型、不联网、不上传代码。
- 不自动改代码（除了 `--fix` 的两种零判断操作）。
- 不做“AI 含量百分比”这种伪指标——听起来很酷，但没人能验证，会被喷。
