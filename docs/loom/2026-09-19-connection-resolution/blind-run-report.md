# 伺服器照它自己說的方式連線 — 我實際試了什麼、結果如何

**結論：七條驗收條件全部通過（PASS）。** 但有三件驗收條件沒點到、我認為你應該
知道的事，寫在後面「驗收條件沒點到、但我注意到的事」一節——其中一件是**這次改動
讓「代理人看得到的 `--password` 字樣」從 1 處變成 2 處**，方向和這次的目的相反。

試用日期：2026-09-21。用 `git worktree` 從這個分支目前的版本 `8e4d0b7` 另外開一份
**全新、沒有人動過的副本**，重新裝一次相依套件再開始，不是在既有工作目錄上跑。
反向驗證（第 7 條）另外從分支起點 `3821be8` 開第二份獨立副本。兩份副本**在跑任何
數字之前都先印出程式實際載入自哪個路徑**，確認彼此沒有污染。

全程設定檔位置指向用完即丟的暫存資料夾，鑰匙圈**全程換成只存在記憶體裡的假貨**。
你電腦上真正的設定檔和系統鑰匙圈從頭到尾沒有被寫入過——驗證前後我都比對過，
結果放在文末。

---

## 一句話：這個修改對你來說是什麼意思

你在 Claude Code 裝這個外掛時會看到一個表單，問你 host / port / user / dbname /
password。**改之前**，只要你填了前面幾欄、密碼欄留空，伺服器就直接報錯不讓你連——
就算你電腦裡已經存了一組**針對同一台機器、同一個帳號**、密碼也好好放在鑰匙圈裡的
設定，它也不看一眼。這就是 2026-09-17 發生在你自己機器上的那件事，當時只能手動去
改外掛存的選項。而且外掛表單上的說明文字和 README 講的是**相反**的規則。

**改之後**：密碼欄留空時，伺服器會去找一組 host、port、user、dbname **四個欄位
全部都對得上**你填的值的設定，借它鑰匙圈裡的密碼來用——**連線目標永遠是你填的那個**，
設定檔只借密碼，絕不會偷偷把你導去它自己的機器。四個欄位沒有全對上就直接拒絕，
而且會把「你填的目標」和「每一組既有設定的目標」都列出來給你看。另外三件事也
一起修好了：狀態查詢工具不再對非 `default` 名稱的設定謊報「沒設定」；未被替換的
設定佔位符不再被當成真密碼拿去登入；兩處叫你用 `--password` 指令參數傳密碼的
建議文字被拿掉了。

---

## 你要求的七件事，一條一條試

### 1. 填了連線欄位、沒有密碼 → 借用 host / port / user / dbname 四者全對的設定的密碼，並連到你填的目標

- **先說清楚我能證明到哪裡**：你的 Redshift 叢集目前**連不上**。我不透過這個專案的
  任何程式碼、直接對
  `ichef-data-warehouse.cjvlrn1rocv5.ap-northeast-1.redshift.amazonaws.com:5439`
  做最原始的連線測試，8 秒逾時。所以「真的登入成功」這件事我**沒辦法證明**，
  也不會假裝證明了。我改成從三個一層比一層深的關卡去確認，每一關都說明它證明了
  什麼、沒證明什麼。

- **我怎麼試的（第一關：解析結果）**：在暫存設定檔裡放**兩組**設定——一組名叫
  `some-unrelated-name`（刻意不叫 `default`、也不叫目標的名字，用來證明名稱完全
  不參與比對），四個欄位正好等於我要連的目標；另一組 `decoy` 只有 host 不一樣，
  用來確認它不會被誤選。然後用「填好四個欄位、完全沒有密碼」的方式啟動。

- **結果**：

  ```
  profiles in store        : ['decoy', 'some-unrelated-name']
  launch args              : --host warehouse.example.com --port 5439 --user analyst --dbname prod   (no --password, no REDSHIFT_PASSWORD)
  mechanism                : 'borrowed'
  profile lending password : 'some-unrelated-name'
  resolved host            : 'warehouse.example.com'
  resolved port            : 5439
  resolved user            : 'analyst'
  resolved dbname          : 'prod'
  resolved password is the stored one : True
  resolved password is the decoy's    : False
  ```

- **我怎麼試的（第二關：真正交給連線程式庫的參數）**：把底層的 Redshift 連線
  函式換成一個「只記錄收到什麼、然後立刻停住」的替身，看伺服器實際遞給它的是
  哪些值。這是進到網路之前的最後一道關卡。

- **結果**：

  ```
  connect(host=)              : 'warehouse.example.com'
  connect(port=)              : 5439
  connect(user=)              : 'analyst'
  connect(database=)          : 'prod'
  connect(password=)          : <redacted> is the stored profile password: True
  ```

  四個欄位**全部是我填的值**，密碼**確實是設定檔裡存的那一個**，不是 `decoy` 的。

- **我怎麼試的（第三關：真的開一條網路連線）**：我在本機開一個**假的監聽程式**
  （它不是 Redshift，只會接住連線、把收到的第一段位元組印出來），把設定與啟動
  參數都指向它，然後讓伺服器真的連過去。

- **結果**：

  ```
  stand-in listener at     : 127.0.0.1:59578
  resolved target          : 127.0.0.1:59578/prod as analyst
  password borrowed from local-standin: True
  connector failed after connecting, as expected against a non-Redshift listener: InterfaceError
  listener accepted a TCP connection : True
  listener local address             : ('127.0.0.1', 59578)
  first bytes seen on the wire       : b'\x00\x00\x00\x08\x04\xd2\x16/'
  ```

  假監聽程式**確實收到了一條真實的網路連線**，而且收到的位址就是我填的那個。
  **這一關證明「連線真的往你填的目標送出去」，不證明「登入成功」**——那個假監聽
  程式不是 Redshift，所以連線在握手階段就被它擋下來了（`InterfaceError`）。

- **證據**：上述三段逐字輸出；探針程式 `a1_borrow.py`；另外專案自己的測試
  `test_four_field_match_borrows_and_uses_inline_values` 在這個版本通過。

- **判定：PASS（通過）。** 「借對密碼、連到你填的目標」這件事在解析層、連線程式庫
  參數層、真實網路連線層三關都成立；**「真的登入進 Redshift」因為叢集連不上而
  無法驗證**，這不是這次改動的問題，但也請你知道它沒被驗證到。

---

### 2. 填了欄位、沒有密碼、又沒有四欄全對的設定 → 拒絕，訊息要同時列出你填的目標和每一組既有設定的目標

- **我怎麼試的**：六種情境，每種都是「填好四個欄位、沒有密碼」。A 只有 host 不對、
  B 只有 port 不對（這正是 2026-09-21 修訂加進來的那一欄）、C 只有 user 不對、
  D 只有 dbname 不對、E 兩組設定**只差 dbname**（看訊息會不會把它們印成一模一樣、
  分不出來）、F 完全沒有任何設定。另外加一個對照組 G：四欄全對，確認它沒有變成
  「什麼都拒絕」。

- **結果**：A 到 F **六種全部拒絕**，G 正常借用。以 B（只有 port 不對）為例，
  訊息逐字如下：

  ```
  Inline mode requires a password for host='warehouse.example.com' port=5439 user='analyst' dbname='prod', and no stored profile's host/port/user/dbname all match it to borrow one from.
  Existing profiles: p-port (host='warehouse.example.com' port=9999 user='analyst' dbname='prod').
  Provide the REDSHIFT_PASSWORD env var, or configure a profile matching this exact host/port/user/dbname via /redshift-comment-mcp:redshift-setup.
  ```

  第一行是**你填的目標**，第二行是**既有設定各自的目標**，兩邊用同樣的
  `host=/port=/user=/dbname=` 格式寫，可以一欄一欄對照著看差在哪。

  E（兩組只差 dbname）這個最容易出包的情境，兩組**確實印得出差別**：

  ```
  Existing profiles: twin-a (host='warehouse.example.com' port=5439 user='analyst' dbname='alpha'), twin-b (host='warehouse.example.com' port=5439 user='analyst' dbname='beta').
  ```

  F（完全沒有設定）印的是 `Existing profiles: none configured.`。

- **證據**：六段逐字訊息；探針程式 `a2_refuse.py`；專案測試
  `test_port_mismatch_refuses_and_names_both_ports`、
  `test_mismatched_profile_raises_naming_both_hosts`、
  `test_no_profiles_at_all_raises`、
  `test_refusal_two_profiles_differing_only_in_dbname_render_distinctly`。

- **判定：PASS（通過）**

---

### 3. `get_setup_status` 回報的機制與目標，要和伺服器真正會用的一致，包含名字不是 `default` 的設定

- **我怎麼試的**：這條的重點是「**工具說的**和**伺服器真的會做的**是不是同一件事」，
  所以我每次都在同一個程序裡**兩邊各問一次**再比對，而且是走真正的 MCP 工具呼叫
  路徑（跟你的代理人呼叫它的路徑同一條），不是直接叫內部函式。三個情境：
  唯一一組設定名叫 `ichef-dw`（不是 `default`）、借用模式、以及完全沒有密碼的情境。

- **結果**：

  情境一，唯一一組設定叫 `ichef-dw`：

  ```
  get_setup_status -> {'profile': 'ichef-dw', 'source': 'profile', 'configured': True, 'has_fields': True, 'has_password': True, 'host': 'dw.example.com', 'port': 5439, 'user': 'analyst', 'dbname': 'prod'}
  server would connect to : dw.example.com:5439/prod as analyst
  same mechanism          : True
  same target as connector: True
  status leaks a password : False
  ```

  **改之前這裡會回報 `configured: False`**（我在分支起點實測過，見第 7 條），
  現在回報 `True`，而且把真正解析到的名字 `ichef-dw` 講出來了。

  情境二，借用模式：

  ```
  get_setup_status -> {'profile': 'default', 'source': 'borrowed', 'configured': True, ..., 'host': 'dw.example.com', 'port': 5439, 'user': 'analyst', 'dbname': 'prod', 'borrowed_from_profile': 'lender'}
  same mechanism          : 'borrowed' == connector's 'borrowed'
  same target as connector: True
  names the lending profile: 'lender'
  status leaks a password : False
  ```

  機制（`borrowed`）和四個目標欄位都和連線程式**完全一致**，而且另外講明密碼是跟
  哪一組借的。三個情境的回報內容裡**都沒有洩漏密碼**（我拿密碼原文去搜每一個欄位，
  結果都是找不到）。

  情境三，沒有密碼時，工具說 `configured: False`，連線程式也確實拒絕——兩邊一致。

- **證據**：三段逐字輸出；探針程式 `a34_status_placeholder.py`；專案測試
  `test_get_setup_status_profile_mode_named_other_than_default_reports_configured`、
  `test_get_setup_status_borrowed_mode_reports_inline_host_and_borrowed_source`。

- **判定：PASS（通過）。** 驗收條件問的「機制」和「目標」兩者都對得上。但這個工具
  回傳的 `profile` 欄位在借用模式下有個會誤導人的地方，寫在後面「驗收條件沒點到」
  第 1 點。

---

### 4. 密碼以「未被替換的設定佔位符」形式送進來時，要當成「沒有密碼」，不是「有一個叫這個名字的密碼」

- **我怎麼試的**：三種送法——用 `--password ${user_config.password}` 送、用環境變數
  `REDSHIFT_PASSWORD=${user_config.password}` 送、以及密碼欄整個留空。每次都在
  設定檔裡放一組四欄全對、密碼是 `BORROWED-PASSWORD-333` 的設定，這樣可以看出
  程式到底是「拿佔位符文字去登入」還是「當成沒密碼、改去借」。再加一個對照組：
  真正的密碼還是要優先於借來的。

- **結果**：

  ```
    launch: --password ${user_config.password}
      mechanism                       : 'borrowed'
      treated as a real password?     : False
      password actually used is the placeholder text : False
      password actually used is the stored one       : True

    launch: REDSHIFT_PASSWORD=${user_config.password}
      mechanism                       : 'borrowed'
      treated as a real password?     : False
      password actually used is the placeholder text : False
      password actually used is the stored one       : True

    launch: --password '' (blank field)
      mechanism                       : 'borrowed'
      ...同上

    CONTROL: a real password must still win over the stored one
      mechanism                       : 'inline'
      uses the inline password        : True
  ```

  三種送法**都沒有拿佔位符文字去登入**，全部正確地改走借用。真密碼的對照組也正常，
  沒有被這個正規化誤傷。另外我把能借的設定拿掉再問一次狀態工具，它也老實回報
  `configured: False`，沒有因為看到佔位符就自稱設定完成。

- **證據**：上述逐字輸出；探針程式 `a34_status_placeholder.py`；專案測試
  `test_resolve_inline_params_password_placeholder_is_no_password`、
  `test_resolve_inline_params_password_env_placeholder_is_no_password`、
  `test_inline_placeholder_password_falls_through_to_borrow`。

- **判定：PASS（通過）**

---

### 5. 伺服器或它的 CLI 發出的訊息，都不可以建議用指令參數傳密碼

- **我怎麼試的**：不只是搜原始碼，我**實際把訊息叫出來**再搜。總共掃了 29 段
  真正會送到使用者或代理人面前的文字：六種連線拒絕訊息、三種狀態工具的
  `next_step` 提示、MCP 伺服器的開場說明、**全部 13 個 MCP 工具的說明文字**
  （這是你的代理人真的會讀到的東西），以及 setup CLI 六個子指令的輸出。

- **結果**：

  ```
  messages checked : 29
  messages recommending --password : 1
  ```

  **28 段乾淨，1 段有殘留**：`get_setup_status` 這個工具的說明文字裡有兩行提到
  `--password`：

  ```
    ``--password``/``REDSHIFT_PASSWORD`` or none), ``"borrowed"``
    ``--password`` in plain inline mode). NEVER returns the
  ```

  **我判定第 5 條仍然 PASS**，理由是：驗收條件的用字是「**建議**（recommends）」。
  改之前那兩句是命令句——`"Inline mode requires a password — provide --password CLI
  flag or REDSHIFT_PASSWORD env var."` 和 `"...REDSHIFT_PASSWORD env var (or pass
  --password) where..."`——**這兩句確實都被拿掉了**（我在分支起點實測過原文，見
  第 7 條）。剩下這兩行是**描述句**，在說明「密碼可能從哪裡來」，沒有叫誰去用它。

  **但這件事有問題，寫在後面「驗收條件沒點到」第 2 點**——簡單說：改之前代理人
  看得到 1 處，改之後變成 2 處。

- **證據**：29 段的逐項掃描結果；探針程式 `a5_sweep.py`；專案測試
  `test_missing_password_error_does_not_recommend_password_flag`、
  `test_no_stray_password_flag_recommendation_in_source`。另外 CLI 的 `--help`
  仍然會列出 `--password PASSWORD` 這個參數本身，這是刻意保留的（需求書明寫
  這個參數是既有的公開整合路徑，不在這次移除範圍）。

- **判定：PASS（通過），但附帶一個我認為你該看的觀察。**

---

### 6. 外掛表單說明和三份 README 要講同一條「密碼留空」的規則，而且那條規則就是程式實際遵守的

- **我怎麼試的**：四份文件逐字讀出「密碼留空」那一段，再用程式檢查四個欄位名稱
  （host / port / user / dbname）是不是都出現、有沒有寫「四者都要對上」、有沒有寫
  「連線去你填的目標」。另外反向搜一次：有沒有哪份文件還留著「port 不算在比對
  條件內」這種舊講法。

- **結果**：四份**全部一致**，四個欄位名稱都在，都寫了「四者全對」和「連到你填的
  目標」，**沒有任何一份還留著排除 port 的舊講法**。

  - 外掛表單（`.claude-plugin/plugin.json`）：「Leave blank to borrow the keychain
    password of a profile (from /redshift-setup) whose **host, port, user and
    dbname all match** the values above — the connection always goes to what you
    typed here, never to the profile's」
  - 英文版：「The server looks for a profile … whose **host, port, user and
    dbname all match** what you typed here, and the connection always goes to
    the target you typed — a profile only ever lends its password, never its
    own host or port.」
  - 日文版：「**host・port・user・dbname がすべて一致**するものを探し、接続先は常に
    あなたがここで入力した値になります —— プロファイルが貸すのはパスワードだけで、
    host や port を肩代わりすることはありません。」
  - 繁中版：「server 會在 `/redshift-setup` 寫出的 profile 裡找一個
    **host、port、user、dbname 四者都對得上**你填的值的，借用它 keychain 裡的密碼，
    連到你填的那個目標 —— profile 只會借出密碼，絕不會把連線換去它自己的 host 或
    port。」

  而「**這條規則就是程式實際遵守的**」這半句，由第 1 條和第 2 條實測直接證明：
  四欄全對才借（第 1 條），任一欄不對就拒絕並列出雙方目標（第 2 條）——文件寫的
  和程式做的是同一件事。

  順帶確認兩個版本號欄位有一起動：`plugin.json` 是 `0.12.0`，`pyproject.toml` 的
  `fallback_version` 也是 `0.12.0`。另外需求書提到的那個限制也成立：`.mcpb` 套件
  的表單把 password 標成 `required=True`，所以那條路徑上根本走不到「密碼留空」。

- **證據**：四段逐字引文；機器比對輸出；專案測試
  `test_blank_password_rule_stated_consistently`（四份文件各一個案例）。

- **判定：PASS（通過）**

---

### 7. 上面每一條驗收條件，都要有一個「拿去跑改動前的舊程式會失敗」的測試

這條最容易被騙——**一個今天綠燈的測試，完全不能證明它當初抓得到舊的錯誤行為**。
所以我用 `git worktree` 從分支起點 `3821be8` 開了**第二份完全獨立的副本**，各自重新
裝相依套件，把這個版本的測試檔複製過去跑。

**在相信任何數字之前，我先讓 pytest 印出它到底載入了哪一份程式**：

```
=== PROVENANCE OF THE CODE UNDER TEST ===
package     : .../scratchpad/wt/base/src/redshift_comment_mcp/__init__.py
config      : .../scratchpad/wt/base/src/redshift_comment_mcp/config.py
tools       : .../scratchpad/wt/base/src/redshift_comment_mcp/redshift_tools.py
server      : .../scratchpad/wt/base/src/redshift_comment_mcp/server.py
server has resolve_connection_decision : False
server has _SubstitutedPort            : False
tools has ConnectionDecision           : False
```

路徑落在「分支起點副本」自己的資料夾，而且這次改動新增的三個東西**確實都不存在**
——確認跑的真的是舊程式，沒有偷偷載到新版。

**結果：21 個測試在舊程式上失敗。**

| 驗收 | 在舊程式上變紅的測試 | 失敗原因是不是對的 |
|---|---|---|
| 1 | `test_four_field_match_borrows_and_uses_inline_values`、`test_borrow_mistyped_port_refuses_to_borrow`、`test_borrow_blank_and_placeholder_port_still_borrow` | 是——舊程式根本不會去借，直接報錯 |
| 2 | `test_port_mismatch_refuses_and_names_both_ports`、`test_mismatched_profile_raises_naming_both_hosts`、`test_no_profiles_at_all_raises`、`test_refusal_two_profiles_differing_only_in_dbname_render_distinctly`、`test_borrow_scan_store_failure_falls_through_to_inline_refusal`（3 個參數版本） | 是——舊訊息只有一句話，兩個目標都沒列 |
| 3 | 見下方說明 | 是 |
| 4 | `test_resolve_inline_params_password_placeholder_is_no_password`、`..._env_placeholder_...`、`test_inline_placeholder_password_falls_through_to_borrow`、`test_inline_placeholder_password_with_no_matching_profile_raises` | 是——舊程式把佔位符當成真密碼 |
| 5 | `test_missing_password_error_does_not_recommend_password_flag`、`test_get_setup_status_inline_next_step_does_not_recommend_password_flag`、`test_no_stray_password_flag_recommendation_in_source` | 是——錯誤訊息逐字指出 `server.py:117 recommends the --password flag` |
| 6 | `test_blank_password_rule_stated_consistently`（四份文件各一） | 是——四份都缺「四者全對」「沒對上就拒絕」這兩個講法 |
| 7 | 本節本身 | — |

**第 3 條我多做了一步，因為原本的證據不夠力。** 覆蓋第 3 條的那兩個測試住在
`tests/test_tools.py`，這個檔案**在舊程式上連載入都載入不了**（它開頭就要 import
一個舊程式沒有的東西），所以反向驗證只會報「收集錯誤」，而不是「測試斷言抓到了
舊行為」。**收集錯誤是很弱的證據**——它只證明檔案和舊程式不相容，不證明那兩個
斷言當初抓得到問題。所以我把那兩個測試的**斷言原封不動搬到一個新檔案**，改成
兩邊都跑得起來的寫法，結果：

```
舊程式（3821be8）：
  FAILED test_get_setup_status_profile_mode_named_other_than_default_reports_configured
    E   assert False is True                          <- configured 是 False
  FAILED test_get_setup_status_borrowed_mode_reports_inline_host_and_borrowed_source
    E   AssertionError: assert 'inline' == 'borrowed'
  2 failed

這次的版本（8e4d0b7）：
  2 passed
```

同一組斷言，舊的紅、新的綠——這才真的證明它抓得到。我另外也直接把舊行為走一遍
給你看：

```
BASE A3-1: the only profile is named 'ichef-dw', not 'default'
get_setup_status -> {'profile': 'default', 'source': 'profile', 'configured': False, 'has_fields': False, ...}
the server actually connects to : dw.example.com:5439/prod as analyst
...with the stored password     : True
status says configured = False   <-- while the server connects normally
THE TOOL CONTRADICTS THE SERVER : True
```

舊版的狀態工具說「沒設定」，但伺服器**同時**正常連上去了——這就是需求書講的那個
「唯一能問『我現在連到哪』的工具，卻可能講錯」。

順帶一提，舊版的拒絕訊息長這樣，對照第 2 條和第 5 條看很清楚：

```
Inline mode requires a password — provide --password CLI flag or REDSHIFT_PASSWORD env var.
the refusal recommends --password : True
the refusal names the supplied target : False
the refusal names the existing profile's target : False
```

- **證據**：反向執行的完整記錄（含載入路徑證明）；移植版測試在兩個版本各自的
  結果；舊行為的逐字走訪輸出。

- **判定：PASS（通過）**

- **一個誠實的補充**：`test_blank_password_rule_no_longer_excludes_port` 這個測試在
  舊程式上是**綠的**。這不是漏洞——它守的是「不可以再寫回 2026-09-21 修訂前那版
  『port 不算』的講法」，而那版講法在分支起點根本還沒被寫出來過，所以它在那裡
  當然不會紅。它防的是未來的回退，不是過去的錯誤。

---

## 驗收條件沒點到、但我注意到的事

### 1. 借用模式下，狀態工具回報的 `profile` 是一個根本不存在的名字

借用模式下我問狀態工具，它回:

```
get_setup_status -> {'profile': 'default', 'source': 'borrowed', ..., 'borrowed_from_profile': 'lender'}
profiles that actually exist : ['lender']
the tool reports profile     : 'default'
...but no profile by that name exists : True
```

電腦裡**只有一組設定叫 `lender`，沒有任何東西叫 `default`**，但工具的 `profile`
欄位回報 `default`。這在程式的說明裡有寫（借用模式下這個欄位「只是把你傳進來的
參數原樣回傳，跟解析無關」），而且真正的答案確實放在旁邊的 `borrowed_from_profile`
欄位。**第 3 條的驗收問的是「機制」和「目標」，這兩個都正確，所以我沒有因此判
FAIL。** 但一個代理人如果照著 `profile` 這個欄位回報給你「你現在用的是 default
這組設定」，它講的是一個不存在的東西。我認為這值得你知道。

### 2. 代理人看得到的 `--password` 字樣，這次改動之後從 1 處變成 2 處

這是我覺得最值得你花三十秒看的一點，因為它的方向和這次的目的相反。

需求書的出發點之一是：有兩句話建議用 `--password` 傳密碼，而「**其中第二句的讀者
是一個有 shell 權限的代理人**」。這兩句**確實都拿掉了**，第 5 條成立。

但是：`get_setup_status` 這個工具的**說明文字會原封不動被送到代理人面前**（我實際
從 MCP 工具清單裡把它抓出來看過）。而這段說明文字裡提到 `--password` 的行數是：

```
分支起點（改動前）：1 行
  in profile mode; ``REDSHIFT_PASSWORD`` / ``--password`` in inline

這次的版本（改動後）：2 行
  ``--password``/``REDSHIFT_PASSWORD`` or none), ``"borrowed"``
  ``--password`` in plain inline mode). NEVER returns the
```

守這條規則的那個測試（`test_no_stray_password_flag_recommendation_in_source`）
是**刻意放行**這種寫法的，它在自己的說明裡把這類文字歸類為「internal architecture
documentation … not an instruction to the reader」（內部架構文件，不是給讀者的指示）。
**這個歸類對其他幾處是對的，但對這一處是錯的**——`get_setup_status` 的這段文字
不是內部文件，它是**出貨給代理人讀的工具說明**。也就是說，這個守門測試的前提
在這一處不成立，所以它抓不到這個增加。

我沒有動任何程式，只是把它記下來。

### 3. 伺服器的開場說明（instructions）實際上送不到用戶端，內容是空的

計畫書 W0-05 有一項是「讓開場說明把 `borrowed` 這個新機制也列進去」，掛在第 3 條
底下。程式裡**確實寫好了**（我在程序內讀出來是 6096 個字，而且有提到 borrowed）。
但是走真正的 MCP 連線握手時，用戶端收到的是**空字串**：

```
E   AssertionError: server instructions missing 'SETUP RECOVERY' (length=0)
E   assert 'SETUP RECOVERY' in ''
```

這是需求書「不在範圍內」那一節就點名的既有問題（fastmcp 4 之下開場說明是空的，
這台機器上裝的是 fastmcp 4.0.5）。**不是這次改壞的**——我在分支起點跑同一批測試，
結果**一模一樣**（各 4 個失敗、2 個通過，連哪幾個失敗都相同）。但後果是：
W0-05 在開場說明上做的那份工，**目前對真實使用者是完全看不到的**。

### 4. 兩組設定同時四欄全對時，密碼是照名字排序默默選第一個

```
profiles (both exact matches): ['aaa-first', 'zzz-second']
result   : borrowed -> warehouse.example.com:5439/prod as analyst
password : 'aaa-first'
```

兩組設定都完全符合、但密碼不同時，程式**安靜地選了名字排序在前的那一個**，
沒有告訴任何人「其實有兩組都符合」。這不違反任何一條驗收條件（連線目標仍然是
你填的、密碼仍然來自一組四欄全對的設定），但如果兩組的密碼是不同帳號的，
你會拿到哪一個是看名字排序決定的。

### 5. 幾個邊界，結果都是安全的方向

- **host 大小寫不同**（存的是 `WAREHOUSE.EXAMPLE.COM`、填的是
  `warehouse.example.com`）：**拒絕**。網域名稱本來不分大小寫，所以這其實是同一台
  機器，你可能會覺得莫名其妙——但拒絕是安全的那一邊，不是危險的那一邊。
- **舊設定沒有存 port**：填 5439 時**借得到**（視為預設埠），填 9999 時**拒絕**。
  合理。
- **借到的密碼只有空白字元**：照借不誤，`'   '` 原樣送給連線程式。這是需求書
  「不在範圍內」已經列出、也已經另外歸檔的既有問題，我只是確認它還在。

---

## 其他跑過的測試

| 這一批 | 結果 |
|---|---|
| 不需要資料庫的單元測試（乾淨副本、`8e4d0b7`） | **436 通過、2 跳過** |
| 專案隨附的 32 個對抗測試案例（未修改） | **32 全部通過** |
| 需要真實叢集的整合測試 | **無法驗證**（叢集連線逾時，發生在程式邏輯之前） |
| MCP 協定測試（e2e，6 項） | **4 失敗、2 通過——但分支起點跑出來一模一樣**，是既有問題（見上方第 3 點），不是這次造成的 |

需求方交給我的背景資訊說 e2e 有「2 項會卡住」。**我這次沒有遇到卡住**：整批
156 秒跑完，結果是 4 失敗 2 通過，而且在分支起點跑出**完全相同**的 4 失敗 2 通過。
所以我把它記成「既有失敗、與這次改動無關」，不是「卡住」。

「無法驗證」不等於「通過」——叢集恢復之後，整合測試那一批還是得補跑才算數。

---

## 對你既有的資料做了什麼

**你的設定檔和系統鑰匙圈，一個位元組都沒有動。** 整個驗證過程中，設定檔位置全程
指向用完即丟的暫存資料夾，鑰匙圈全程換成只存在記憶體裡的假貨——而且我在每一支
探針程式開頭都加了一道**強制檢查**：確認設定檔路徑不等於你真正的路徑、確認鑰匙圈
物件真的是假的、並且實際寫一筆再讀回來證明程式呼叫到的是那個假貨，任何一項不
成立就直接中止不跑。（這道檢查第一次真的擋下來過一次，因為 macOS 的路徑符號連結
讓比對失敗，我修的是檢查本身，不是放寬它。）

驗證結束後我直接比對你真正的設定檔：

```
驗證前 sha256 : 17caa5cbe9da254a16c9851f0fff7348e04a97689e46911361d17a5afc80de1b
驗證後 sha256 : 17caa5cbe9da254a16c9851f0fff7348e04a97689e46911361d17a5afc80de1b
驗證前 mtime  : May  8 10:05:45 2026
驗證後 mtime  : May  8 10:05:45 2026
系統鑰匙圈    : 仍然只有一筆 acct="default"，沒有新增
設定資料夾    : 只有 config.toml 一個檔案，沒有殘留暫存檔
```

內容、修改時間、權限、鑰匙圈筆數**全部與驗證開始前完全相同**。

（附帶一提：上一份驗證報告提到系統鑰匙圈裡有一筆遺留的測試假密碼
`acct="prod"`。**這次我查的時候它已經不在了**，現在只剩你真正的 `default` 那一筆。
我沒有刪過任何東西。）

至於這個修改**上線之後**對你既有資料的影響：設定檔格式沒有改，既有設定不需要
轉換、不需要備份。行為上唯一的變化是「密碼欄留空」這個以前會直接報錯的狀態，
現在會去找四欄全對的設定借密碼——**找不到就拒絕，不會連到別的地方**。你目前唯一
的那組設定（`default`）不會因為這次改動而需要任何調整。

---

## 我替你決定的事

- **第 1 條的「連線」我拆成三層來證明，而不是宣稱「連上了」。** 叢集連不上是
  今天的事實（我自己用最原始的方式測過，8 秒逾時），所以我選擇在「解析出什麼」
  「交給連線程式庫什麼」「有沒有真的往那個位址開一條連線」三個關卡各留一份證據，
  並且明講第三層用的是本機假監聽程式、**只證明去向、不證明登入成功**。如果你
  認為沒有真的登入過就不該算 PASS，這裡是你會想推翻我的地方。
- **第 5 條我判 PASS，而不是 FAIL。** 依據是驗收條件的用字是「建議」，而兩句
  命令式的建議確實都移除了。剩下的兩行是描述句。但我把「代理人看得到的字樣
  從 1 處變成 2 處」這件事完整寫在上面，沒有藏在判定裡——如果你認為「代理人
  眼前不該出現這個字樣」才是這條的真意，那這條應該判 FAIL，判斷權在你。
- **第 3 條的反向驗證，我沒有接受「收集錯誤」當證據，多寫了一組移植版測試。**
  原本的反向執行只能證明「那個測試檔在舊程式上載入不了」，這不等於「那個斷言
  抓得到舊行為」。多花的這一步改變了證據強度，沒有改變結論。
- **MCP 協定測試的 4 個失敗，我記為「既有問題」而不是這次的失敗。** 依據是我在
  分支起點跑出完全相同的 4 失敗 2 通過。如果這個依據錯了，問題會出在這裡。
- **沒有任何審查者把嚴重程度「重要」以上的意見交給我，也沒有這類意見被駁回後
  轉交給我記錄。** 這個變更的資料夾裡目前沒有審查意見文件或存證檔。
- **我沒有修任何東西。** 上面每一項觀察——狀態工具回報不存在的名字、`--password`
  字樣變多、開場說明送不到、兩組同時符合時默默選第一個、空白密碼照借——我都只
  記錄，沒有動手改。唯一動過的程式是我自己的探針和那道隔離檢查，全部在暫存
  資料夾裡，不在專案內。

---

## 我不確定你要不要

1. **`get_setup_status` 在借用模式下回報 `profile: 'default'`（一個不存在的名字），
   要不要改成回報 `null` 或直接回報借出密碼的那組名字？** 現在真正的答案在隔壁
   欄位，但代理人很容易讀錯欄位。
2. **代理人看得到的那兩行 `--password` 字樣，要不要一併清掉？** 順便把那個守門
   測試的判斷依據修正一下——它目前把「出貨給代理人的工具說明」誤當成「內部文件」
   而放行。
3. **開場說明在 fastmcp 4 之下是空的，要不要提高優先序？** 這不是這次改壞的，
   但它讓 W0-05 在開場說明上做的工完全看不到，也讓你未來任何寫在開場說明裡的
   指引一樣看不到。
4. **兩組設定同時四欄全對時，要不要改成「拒絕並請使用者指定」，而不是默默選
   名字排序第一個？**
5. **需要真實叢集的整合測試，要不要等連線恢復之後補跑一次再正式核准？** 這不是
   這次改動造成的問題，但那一批終究還沒被驗證過。

---

## 語言與格式規則檢查

| 文件 | 規則 | 結果 | 依據 |
|---|---|---|---|
| 需求書（intent） | 全英文 | 符合 | 全文無中日文字（比對結果 0 處） |
| 規劃書（plan.md） | 全英文 | 符合（三處例外，且該例外正確） | 三處中日文字全部在「問過你的原話」那個逐字記錄段落，是保留你原本的輸入，不是規劃書自己的敘述 |
| 設計規格 | EARS `REQ-<n>` 條列 | 不適用 | 需求書明寫 `needs-design: no`，沒有產出設計規格 |
| 審查意見 | Conventional Comments 標籤 | 不適用 | 這個變更的資料夾裡沒有審查意見文件，也沒有嚴重程度「重要」以上的意見轉交給我 |
| 證據檔（對抗探針程式） | 全英文 | 符合 | 六支探針程式（含共用模組）全部 0 處中日文字 |
| 測試說明文字（docstring） | 全英文 | 符合 | `test_server_resolution.py` 0 處。`test_tools.py` 有 122 處中日文字，但**全部是改動前就存在的**（分支起點同樣是 122 處，這次新增 0 處）。`test_repo_invariants.py` 這次新增 6 處，全部是日文版／繁中版 README 的比對字串本身——測試對象就是多語文件，屬於正確的例外 |
| 測試命名 | `test_<單元>_<狀態>_<預期>` | 部分符合 | 命名在語意上都是三段式（例如 `test_port_mismatch_refuses_and_names_both_ports` = 單元 port_mismatch／狀態 refuses／預期 names_both_ports），但沿用專案既有的敘述式風格，沒有嚴格用底線切成剛好三段 |
| 提交訊息 | 全英文 | 符合 | 分支起點以來 13 筆提交，標題與內文皆 0 處中日文字 |

---

## 我沒能做到的事

- **「真的登入進 Redshift」沒有驗證到**——叢集連不上（原始 TCP 測試 8 秒逾時），
  這是這段期間第四次。第 1 條的「連線」我只能證明到「往正確的位址、帶著正確的
  密碼開出一條真實連線」為止。
- **需要真實叢集的整合測試那一批，完全沒跑。**
- **沒有找到獨立成檔的審查意見文件**可供逐條核對 Conventional Comments 標籤規則。
- 上面列出的每一項觀察我都**只記錄、沒有修**——包括那兩行 `--password` 殘留、
  狀態工具回報不存在的名字、以及開場說明送不到用戶端。
