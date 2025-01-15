#!/bin/bash

echo "开始更新项目..."

# 检查是否有未提交的更改
if [ -n "$(git status --porcelain)" ]; then
    echo "检测到本地有未提交的更改..."
    git stash
    HAS_STASH=1
fi

# 拉取最新代码
echo "从远程仓库拉取最新代码..."
git pull origin main

# 如果之前有暂存的更改，恢复它们
if [ "$HAS_STASH" = "1" ]; then
    echo "恢复本地更改..."
    git stash pop
fi

# 更新依赖
echo "更新 Python 依赖..."
pip3 install -r requirements.txt

# 创建必要的目录
echo "确保必要的目录存在..."
mkdir -p static/events

echo "更新完成！"
echo "运行 'python3 app.py' 启动应用" 