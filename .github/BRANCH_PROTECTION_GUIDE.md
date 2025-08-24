# Main 分支保護設定指南

## 設定位置
前往 Repository → Settings → Branches → Add rule

## 建議的保護規則

### Branch name pattern
```
main
```

### 保護設定

#### ✅ 必須啟用的保護項目：
- **Require a pull request before merging**
  - Required number of approvals before merging: `1`
  - Dismiss stale PR approvals when new commits are pushed
  - Require review from code owners (如果有 CODEOWNERS)

- **Require status checks to pass before merging**  
  - Require branches to be up to date before merging
  - Status checks required:
    - `test` (來自 test.yml workflow)

- **Restrict pushes that create files larger than 100MB**

- **Do not allow force pushes**

- **Do not allow deletions** 

#### ⚠️ 重要設定：
- **Include administrators** ✅ 
  - 這確保即使是 repository 擁有者也必須遵循保護規則
  - 避免意外的直接推送到 main

## 工作流程影響

### 正常開發流程：
1. 從 main 建立 feature 分支
2. 開發完成後建立 Pull Request
3. 等待 CI 測試通過
4. 自行 approve 並合併 PR
5. 刪除 feature 分支

### GitHub Actions 相容性：
- ✅ CI/CD workflows 可以正常運作
- ✅ 自動發布流程不受影響
- ✅ 測試必須通過才能合併

## 例外情況

如果緊急需要直接推送到 main：
1. 暫時停用保護規則
2. 進行緊急修復  
3. 立即重新啟用保護規則

## 額外建議

### 建立 CODEOWNERS 檔案 (可選)
在 repository 根目錄建立 `.github/CODEOWNERS`：

```
# 全域代碼擁有者
* @kouko

# 特定檔案的擁有者
.github/workflows/* @kouko
pyproject.toml @kouko
```

這樣可以確保重要檔案的變更需要你的 review。