# GitHub Actions 自動化部署指南

本專案使用 GitHub Actions 來自動化測試和發布流程。

## 設定步驟

### 1. 設定 API Tokens

#### PyPI API Token
1. 前往 [PyPI Account Settings](https://pypi.org/manage/account/)
2. 點選 "Add API token"
3. 設定 Token 名稱（例如：`redshift-comment-mcp-github`）
4. 選擇 Scope：選擇特定專案或 "Entire account"
5. 複製生成的 Token（格式：`pypi-...`）

#### TestPyPI API Token
1. 前往 [TestPyPI Account Settings](https://test.pypi.org/manage/account/)
2. 點選 "Add API token"
3. 設定 Token 名稱（例如：`redshift-comment-mcp-test`）
4. 選擇 Scope："Entire account"（TestPyPI 通常選這個）
5. 複製生成的 Token（格式：`pypi-...`）

### 2. 在 GitHub 中設定 Secrets

1. 前往你的 GitHub Repository
2. 點選 **Settings** → **Secrets and variables** → **Actions**
3. 分別添加兩個 Secrets：

**PyPI Token:**
- Name: `PYPI_API_TOKEN`
- Value: 貼上 PyPI API Token

**TestPyPI Token:**
- Name: `TEST_PYPI_API_TOKEN`
- Value: 貼上 TestPyPI API Token

## 工作流程說明

### 自動測試 (.github/workflows/test.yml)

**觸發條件：**
- Push 到 `main` 或 `develop` 分支
- Pull Request 到 `main` 或 `develop` 分支

**執行內容：**
- 在 Python 3.10、3.11、3.12 環境下執行測試
- 安裝依賴並運行 `pytest tests/`

### TestPyPI 測試發布 (.github/workflows/test-publish.yml)

**觸發條件：**
- GitHub Pre-release 發布時自動觸發
- 可手動觸發 (workflow_dispatch)

**執行流程：**
1. 執行完整測試確保品質
2. 建置套件 (`python -m build`)
3. 發布到 **TestPyPI**
4. 驗證發布成功
5. 測試安裝功能
6. 自動在 Release 中添加測試報告留言

### PyPI 正式發布 (.github/workflows/publish.yml)

**觸發條件：**
- GitHub Release 正式發布時自動觸發
- 可手動觸發 (workflow_dispatch)

**執行流程：**
1. 執行完整測試確保品質
2. 建置套件 (`python -m build`)
3. 發布到 **PyPI**
4. 驗證發布成功
5. 自動在 Release 中添加發布報告留言

## 發布新版本流程

### 方法 1: 通過 GitHub Release（推薦）

#### 步驟 1: 測試發佈（TestPyPI）

1. **提交代碼變更**
   ```bash
   git add .
   git commit -m "feat: add new feature" # 或 "fix: resolve bug" 或 "BREAKING CHANGE: ..."
   git push origin main
   ```

2. **建立 Git Tag**
   ```bash
   # 建立版本標籤（例如：v0.2.0）
   git tag v0.2.0
   git push origin v0.2.0
   ```

3. **建立 Pre-release**
   - 前往 GitHub Repository → **Releases** → **Create a new release**
   - Tag version: 選擇剛才建立的 tag（例如：`v0.2.0`）
   - Release title: `Version 0.2.0 Release Candidate`
   - 描述更新內容
   - ✅ **勾選 "Set as a pre-release"**
   - 點選 **Publish release**

4. **自動測試發布**
   - GitHub Actions 會自動觸發
   - 執行測試 → 建置 → 發布到 **TestPyPI** → 驗證發布 → 測試安裝
   - 可在 https://test.pypi.org/project/redshift-comment-mcp/ 查看

#### 📊 如何確認 TestPyPI 發布成功

**方法 1: Release 留言（最直觀）**
1. 前往你的 Pre-release 頁面
2. 查看自動生成的留言，包含：
   - ✅ 發布狀態
   - 🔗 TestPyPI 連結
   - 📥 測試安裝指令

**方法 2: GitHub Actions Summary**
1. 前往 **Actions** 頁面
2. 點選最新的 "Test Publish to TestPyPI" workflow run
3. 查看 **Summary** 區域的 "TestPyPI 發布報告"
4. 確認狀態顯示 ✅ 成功

**方法 3: Actions 日誌詳細檢查**
1. 在 workflow run 中點選 **test-publish** job
2. 檢查各個步驟的狀態：
   - ✅ "Publish to TestPyPI" - 上傳成功
   - ✅ "Verify TestPyPI publication" - 確認可下載
   - ✅ "Test installation from TestPyPI" - 安裝測試通過
   - ✅ "Create Test Report" - 生成報告

**方法 4: 手動確認**
```bash
# 直接查看 TestPyPI 網頁
https://test.pypi.org/project/redshift-comment-mcp/

# 或使用 API 檢查
curl -s "https://test.pypi.org/pypi/redshift-comment-mcp/json" | jq '.releases | keys'
```

5. **驗證 TestPyPI 套件**
   ```bash
   # 從 TestPyPI 安裝測試
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ redshift-comment-mcp==0.1.1
   
   # 測試功能是否正常
   redshift-comment-mcp --help
   ```

#### 步驟 2: 正式發佈（PyPI）

6. **建立正式 Release**
   - 前往之前建立的 Pre-release
   - 點選 **Edit release**
   - ❌ **取消勾選 "Set as a pre-release"**
   - Tag version 保持不變: `v0.2.0`（不需要修改）
   - 點選 **Update release**

7. **自動正式發布**
   - GitHub Actions 會自動觸發
   - 執行測試 → 建置 → 發布到 **PyPI**
   - 可在 https://pypi.org/project/redshift-comment-mcp/ 查看

### 方法 2: 手動觸發

1. 前往 **Actions** → **Publish to PyPI**
2. 點選 **Run workflow**
3. 選擇分支並執行

## 監控發布狀態

1. 前往 **Actions** 頁面查看工作流程狀態
2. 點選具體的 workflow run 查看詳細日誌
3. 發布成功後，可在 [PyPI](https://pypi.org/project/redshift-comment-mcp/) 確認新版本

## 故障排除

### 常見問題

1. **PyPI API Token 錯誤**
   - 確認 Secret 名稱是 `PYPI_API_TOKEN`
   - 確認 Token 有效且有權限

2. **測試失敗**
   - 檢查測試程式碼是否有問題
   - 確保所有依賴都正確安裝

3. **建置失敗**
   - 檢查 `pyproject.toml` 設定是否正確
   - 確認檔案結構完整

### 查看日誌

點選失敗的 Action 查看詳細錯誤訊息，通常會指出具體問題所在。

## 版本號自動管理

本專案使用 **setuptools-scm** 進行自動版本管理，版本號基於 Git 標籤自動生成。

### 版本號規則

- **正式版本**：基於 Git tag（例如：`v0.2.0` → 版本 `0.2.0`）
- **開發版本**：自動生成（例如：`0.2.1.dev3+g1234567`）
- **格式**：遵循 [語意化版本](https://semver.org/lang/zh-TW/) `MAJOR.MINOR.PATCH`

### 版本類型建議

```bash
# Bug 修復（PATCH：0.1.0 → 0.1.1）
git tag v0.1.1

# 新功能（MINOR：0.1.1 → 0.2.0）
git tag v0.2.0

# 重大變更（MAJOR：0.2.0 → 1.0.0）
git tag v1.0.0

# 預發布版本
git tag v0.2.0-rc1
git tag v0.2.0-beta1
```

### 檢查當前版本

```bash
# 安裝 setuptools-scm
pip install setuptools-scm

# 查看當前版本
python -c "from setuptools_scm import get_version; print(get_version())"
```

### 優點

- ✅ **自動化**：無需手動更新 `pyproject.toml` 中的版本號
- ✅ **同步**：版本號與 Git 歷史完全同步
- ✅ **開發版本**：自動生成開發版本號，便於測試
- ✅ **防錯**：避免忘記更新版本號的問題