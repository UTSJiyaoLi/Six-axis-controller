# 🚀 Git 常用命令速查表

这是一个覆盖 90% 日常开发场景的 Git 指令清单，适用于：

- 上传代码到 GitHub
- 管理更新和版本
- 解决 push/pull 问题
- 切换分支
- 回退版本

---

## 1. 初始化 Git 仓库

```bash
git init
git remote add origin https://github.com/xxx/xxx.git
git branch -M main
git push -u origin main
```

---

## 2. 提交代码（本地）

```bash
git status            # 查看工作区状态
git add .             # 添加所有改动到暂存区
git commit -m "msg"   # 提交
```

---

## 3. 推送到 GitHub（远程）

```bash
git push              # 推送到当前分支
git push origin main  # 推送到指定分支
```

---

## 4. 从 GitHub 拉取最新代码

```bash
git pull origin main
```

如果本地也有提交，推荐用 rebase：

```bash
git pull --rebase origin main
```

---

## 5. 克隆远程仓库

```bash
git clone https://github.com/xxx/xxx.git
```

---

## 6. 分支管理

## 查看分支

```bash
git branch
git branch -a    # 包含远程分支
```

## 创建分支

```bash
git branch feature/a
```

## 切换分支

```bash
git checkout feature/a
```

## 新建并切换

```bash
git checkout -b feature/a
```

## 合并分支

```bash
git checkout main
git merge feature/a
```

## 删除本地分支

```bash
git branch -d feature/a
```

## 删除远程分支

```bash
git push origin --delete feature/a
```

---

## 7. 回滚与撤销

## 撤销工作区修改（未 add）

```bash
git checkout -- filename
```

## 撤销暂存区修改（add 但未 commit）

```bash
git reset HEAD filename
```

## 回退到某次提交（谨慎）

```bash
git reset --hard <commit_id>
```

查看提交历史：

```bash
git log --oneline --graph
```

---

## 8. 处理冲突（pull 时）

```bash
git pull origin main
# 如果冲突，手动解决后：

git add .
git commit -m "fix conflict"
git push
```

---

## 9. 强制推送（慎用）

如果远程与本地提交不一致，需要覆盖远程记录：

```bash
git push --force
```

---

## 10. 常用配置（建议永久设置）

```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"

# 增大 Git 缓冲区，上传大文件时不超时
git config --global http.postBuffer 524288000
git config --global core.compression 0
```

---

## 11. .gitignore（建议每个项目都写）

示例：

``` python
*.exe
*.dll
*.zip
*.rar
__pycache__/
*.pyc
dist/
build/
```

---

## 🎉 完成

这份文档适合长期放在你自己的 GitHub 仓库、团队文档或本地笔记中。
