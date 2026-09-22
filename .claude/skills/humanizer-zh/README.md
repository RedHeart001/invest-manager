# Humanizer-zh: AI 写作去痕工具（中文版）

> **来源**：[github.com/op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh)（MIT，Copyright © 2026 歸藏）
> 本目录的 SKILL.md / LICENSE 为该仓库原文件；此 README 为本地安装说明。
>
> **声明（承自上游）**：
> - 核心文件翻译自 [blader/humanizer](https://github.com/blader/humanizer/tree/main)
> - 实用工具部分（核心规则、快速检查清单、质量评分）参考 [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop)
> - 原项目基于维基百科 [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) 指南

## 用途

去除文本中的 AI 生成痕迹，让文字读起来更像人写的。检测并修复 24 类模式：夸大的象征意义、宣传性语言、-ing 式肤浅分析、模糊归因、破折号滥用、三段式法则、AI 高频词、否定式排比等。

**适用**：编辑/审阅 AI 生成的内容、提升文章人性化程度。触发词见 SKILL.md frontmatter。

## 安装位置

本项目级：`.claude/skills/humanizer-zh/`（第三方技能约定，见同目录上一级 `README.md`）。

## 同步上游

```bash
# 重新拉取（上游更新后比对哈希再用）
curl -sS https://raw.githubusercontent.com/op7418/Humanizer-zh/main/SKILL.md -o .claude/skills/humanizer-zh/SKILL.md
```
