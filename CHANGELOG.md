# Changelog

## 0.3.0

- 新增 `--baseline` / `--save-baseline`：只报基线之后新增的破绽，把体检变成回归检测。
- 新增 `--fix` / `--apply`：只做零判断修复（补 `.gitignore`、生成 `.env.example`），默认只预演。
- 每条问题新增“客户可见天数”。
- 新增 `--exclude`，可重复传。
- 新增 `.github/workflows/slopcheck.yml`：跑测试、写 Step Summary、critical 直接失败。
- 空目录返回满分而不是一堆“缺 LICENSE”。

## 0.2.0

- 修误报：`.env` 不再被当成已提交（改为看 `.gitignore` 是否覆盖）。
- 修误报：密钥扫描跳过 `.env`、`.md`，以及 `sk-...` / `<your-key>` 这类示例。
- 修误报：README 命令比对只在同目录存在 `package.json` 时启用。
- 修误报：工具自己的正则定义行不再被自己的规则命中。
- 支持 `.gitignore` / `LICENSE` / `Dockerfile` 等无后缀文件。

## 0.1.0

- 首个版本：18 条规则、终端/Markdown/JSON 三种输出、评分与分级。
