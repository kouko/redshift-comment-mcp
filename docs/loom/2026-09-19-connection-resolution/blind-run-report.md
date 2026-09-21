# 伺服器照它自己說的方式連線 — 我實際試了什麼、結果如何

**結論：七條驗收條件全部通過（PASS）。**

**這份報告在 2026-09-21 重走過一次，版本從 `8e4d0b7` 換到 `47910d5`。** 第一次
走完之後我提出的三項觀察被接受並修好（W0-08），第三輪對抗又在那些修正裡找到三個
新缺陷、也一併修掉（W0-09），這些修正改動了第 1、2、3、5 條的行為。**舊版報告
描述的行為已經不是現在的行為，所以整份改寫，不是附註。** 第 6 條自從上次驗證後
完全沒有被動過（我用差異比對確認過，四份文件加版本檔的差異是空的），沿用上次的
證據；第 4 條的程式碼沒有被動到，但因為它會落到已經改過的「借用」路徑上，我還是
重跑了一次。

**第一次驗證最重要的發現這次已經歸零**：那時我量到「代理人看得到的 `--password`
字樣」從改動前的 1 處變成 2 處，方向和這次的目的相反。用**完全相同的量法**重量
一次，現在是 **0 處**。

**第三次修訂（版本 `166bf07`）——這次沒有重走七條驗收，只改正我自己寫錯的一句話，
並記錄我提的三個小問題都已修好。** 詳情在「驗收條件沒點到」那一節開頭。這次的兩筆
提交只動說明文字、沒有動任何一行會執行的程式碼——**這件事我自己驗證過，沒有採信
別人的說法**：我把改動前後兩個版本的兩支程式各自解析成語法樹、把說明文字（docstring）
拿掉之後比對，兩支都**完全相同**（註解本來就不會進語法樹）。所以第 1 到 7 條的
證據全部沿用，不需要重走。

但「只動說明文字」**不等於使用者看不到**——`get_setup_status` 的說明文字是會送到
你的代理人面前的。所以我還是重新量了兩件事：送上線的表面提到 `--password` 的
數量**仍然是 0**，多組相符的拒絕訊息**一字未變**（見第 2、5 條）。整套單元測試
**448 通過、2 跳過**，38 個對抗測試案例**全綠且未被修改**，與上次相同。

試用日期：2026-09-21。用 `git worktree` 從 `47910d5` 開一份**全新、沒有人動過的
副本**，重新裝一次相依套件再開始。反向驗證（第 7 條）另外從分支起點 `3821be8` 開
第二份獨立副本。兩份副本**在跑任何數字之前都先印出程式實際載入自哪個路徑**，
確認彼此沒有污染。第三次修訂的查證另外從 `166bf07` 開了第三份乾淨副本。

全程設定檔位置指向用完即丟的暫存資料夾，鑰匙圈**全程換成只存在記憶體裡的假貨**。
你電腦上真正的設定檔和系統鑰匙圈從頭到尾沒有被寫入過——驗證前後都比對過，結果
放在文末。

---

## 一句話：這個修改對你來說是什麼意思

你在 Claude Code 裝這個外掛時會看到一個表單，問你 host / port / user / dbname /
password。**改之前**，只要你填了前面幾欄、密碼欄留空，伺服器就直接報錯不讓你連——
就算你電腦裡已經存了一組**針對同一台機器、同一個帳號**、密碼也好好放在鑰匙圈裡的
設定，它也不看一眼。這就是 2026-09-17 發生在你自己機器上的那件事。而且外掛表單上
的說明文字和 README 講的是**相反**的規則。

**改之後**：密碼欄留空時，伺服器會去找一組 host、port、user、dbname **四個欄位
全部都對得上**你填的值的設定，借它鑰匙圈裡的密碼來用——**連線目標永遠是你填的
那個**，設定檔只借密碼，絕不會偷偷把你導去它自己的機器。四個欄位沒有全對上就直接
拒絕，並列出「你填的目標」和「每一組既有設定的目標」。

**這次重走新增的三件事**（都是上一輪之後才加進去的）：

- **如果有兩組以上的設定「四個欄位全都對得上」，伺服器不再默默挑名字排序第一個，
  而是直接拒絕並把每一組都列出來。** 這個情境最常見的來源是換密碼：舊的設定沒刪、
  新的設定建好，兩組指向同一台機器。默默挑一個可能挑到已經作廢的密碼，甚至可能
  把帳號鎖掉。**就算兩組的密碼其實一模一樣也照樣拒絕**——這是刻意的，讓你光看
  `config.toml` 就能預測會不會被拒絕，不必去翻鑰匙圈。
- **設定名稱裡如果夾了換行之類的控制字元，不會再污染錯誤訊息。** 以前這種名字能
  在訊息裡偽造出一整行「還有一組設定，主機是某某」的假內容，而讀這個訊息的正是
  你的代理人。
- **狀態查詢工具不再回報一個不存在的設定名稱。**

---

## 你要求的七件事，一條一條試

### 1. 填了連線欄位、沒有密碼 → 借用 host / port / user / dbname 四者全對的設定的密碼，並連到你填的目標

- **先說清楚我能證明到哪裡**：你的 Redshift 叢集目前**連不上**。我不透過這個專案的
  任何程式碼、直接對
  `ichef-data-warehouse.cjvlrn1rocv5.ap-northeast-1.redshift.amazonaws.com:5439`
  做最原始的連線測試，8 秒逾時。所以「真的登入成功」這件事我**沒辦法證明**，也不會
  假裝證明了。我改成從三個一層比一層深的關卡去確認。

- **我怎麼試的（第一關：解析結果）**：暫存設定檔裡放兩組設定——`some-unrelated-name`
  （刻意不叫 `default`，證明名稱不參與比對）四欄正好等於目標，`decoy` 只有 host
  不同。用「填好四個欄位、完全沒有密碼」啟動。**這一關這次特別重要**，因為新加的
  「多組相符就拒絕」檢查有可能把單一相符也一起擋掉。

- **結果**：

  ```
  profiles                 : ['decoy', 'some-unrelated-name']
  mechanism                : 'borrowed'
  profile lending password : 'some-unrelated-name'
  ambiguous_profiles       : None
  connected target         : warehouse.example.com:5439/prod as analyst
  password is the stored one : True
  password is the decoy's    : False
  repr() of the decision   : ConnectionDecision(mechanism='borrowed', host='warehouse.example.com', port=5439, user='analyst', dbname='prod', has_fields=True, has_password=True, profile_name='some-unrelated-name', ambiguous_profiles=None)
  ```

  單一相符**照借不誤**，新的檢查沒有誤傷。順帶可以看到：把整個決策物件印出來時，
  密碼**不會出現**在裡面。

- **結果（第二關：真正交給連線程式庫的參數）**：把底層連線函式換成只記錄不連線的
  替身：

  ```
  connect(host=)            : 'warehouse.example.com'
  connect(port=)            : 5439
  connect(user=)            : 'analyst'
  connect(database=)        : 'prod'
  connect(password=)        : <redacted> is the stored profile password: True
  ```

  四個欄位**全部是我填的值**，密碼**確實是設定檔存的那一個**。

- **結果（第三關：真的開一條網路連線）**：本機開一個假監聽程式（不是 Redshift），
  讓伺服器真的連過去：

  ```
  stand-in listener at  : 127.0.0.1:49581
  resolved target       : 127.0.0.1:49581/prod as analyst
  borrowed correctly    : True
  connector failed AFTER connecting : InterfaceError
  listener accepted a TCP connection : True
  listener local address             : ('127.0.0.1', 49581)
  first bytes on the wire            : b'\x00\x00\x00\x08\x04\xd2\x16/'
  ```

  假監聽程式**確實收到一條真實的網路連線**，位址就是我填的那個。**這一關證明
  「連線真的往你填的目標送出去」，不證明「登入成功」**——那個假監聽程式不是
  Redshift，連線在握手階段就被擋下（`InterfaceError`）。

- **另外確認（新行為）**：四個欄位相同、但**只有其中一組真的有鑰匙圈密碼**時，
  不算「多組相符」，照樣正常借用：

  ```
  profiles           : ['has-pw', 'no-pw'] (only 'has-pw' has a password)
  mechanism          : 'borrowed'
  ambiguous_profiles : None
  borrowed from      : 'has-pw'
  correct password   : True
  ```

- **證據**：上述四段逐字輸出；探針程式 `r1_borrow_and_tie.py`；專案測試
  `test_four_field_match_borrows_and_uses_inline_values`、
  `test_single_matching_profile_still_borrows_despite_ambiguity_check`。

- **判定：PASS（通過）。** 三關都成立；**「真的登入進 Redshift」因為叢集連不上而
  無法驗證**，這不是這次改動的問題，但也請你知道它沒被驗證到。

---

### 2. 填了欄位、沒有密碼、又沒有四欄全對的設定 → 拒絕，訊息要同時列出你填的目標和每一組既有設定的目標

- **我怎麼試的**：先重跑上次那四種「只有一個欄位不對」的情境，再走三種這次新增的
  情境：兩組設定四欄全對且密碼**不同**、兩組四欄全對且密碼**完全相同**、以及設定
  名稱裡夾**控制字元**。

- **結果（四種單欄不符，不變）**：host / port / user / dbname 任一欄不同，**四種
  全部拒絕**，訊息一律以

  ```
  Inline mode requires a password for host='warehouse.example.com' port=5439 user='analyst' dbname='prod', and no stored profile's host/port/user/dbname all match it to borrow one from.
  ```

  開頭，第二行列出既有設定各自的完整目標。

- **結果（新：兩組四欄全對、密碼不同）**：

  ```
  profiles (both exact matches): ['rotated-new', 'rotated-old']
  mechanism           : 'inline'
  ambiguous_profiles  : ('rotated-new', 'rotated-old')
  result              : refused
  ```

  訊息逐字：

  ```
  Inline mode requires a password for host='warehouse.example.com' port=5439 user='analyst' dbname='prod', and 2 stored profiles all match that exact target: 'rotated-new', 'rotated-old'. Refusing to guess which one to borrow — picking by sort order could silently prefer a retired credential over its replacement, the shape a credential rotation leaves behind.
  Existing profiles: 'rotated-new' (host='warehouse.example.com' port=5439 user='analyst' dbname='prod'), 'rotated-old' (host='warehouse.example.com' port=5439 user='analyst' dbname='prod').
  Delete or rename the stale profile so only one matches this target, or provide the REDSHIFT_PASSWORD env var directly.
  ```

  我逐項檢查了這則訊息**有沒有亂講話**：

  ```
  names 'rotated-old'  : True
  names 'rotated-new'  : True
  leaks OLD secret     : False
  leaks NEW secret     : False
  claims they DIFFER   : False
  claims they MATCH    : False
  ```

  兩組都點名了、**兩個密碼都沒有外洩**、而且**沒有宣稱它們不同、也沒有宣稱它們
  相同**——只講「四個欄位打平」這件它真的檢查過的事。

- **結果（新：兩組四欄全對、密碼一模一樣）**：

  ```
  both passwords identical. mechanism: 'inline'
  ambiguous_profiles : ('twin-a', 'twin-b')
  result             : refused
  names both twins   : True
  leaks the secret   : False
  ```

  **一樣拒絕。** 這是刻意的設計：讓「會不會被拒絕」這件事只取決於 `config.toml`
  看得到的四個欄位，你不必去翻鑰匙圈才能預測。

- **結果（新：設定名稱夾控制字元）**：我存了一組名字是
  `evil\nExisting profiles: totally-legit (host='attacker.example.com' port=5439 user='root' dbname='prod')`
  的設定——企圖在錯誤訊息裡偽造出一整行假的「既有設定」。訊息逐字：

  ```
  Inline mode requires a password for host='warehouse.example.com' port=5439 user='analyst' dbname='prod', and no stored profile's host/port/user/dbname all match it to borrow one from.
  Existing profiles: 'evil' [truncated: name contains a control character] (host='zzz.example.com' port=5439 user='analyst' dbname='prod').
  Provide the REDSHIFT_PASSWORD env var, or configure a profile matching this exact host/port/user/dbname via /redshift-comment-mcp:redshift-setup.
  ```

  ```
  number of lines in the message : 3
  'Existing profiles:' appears N times : 1
  the forged host leaked verbatim into a line : False
  truncation marker present : True
  ```

  名字在第一個控制字元處被切斷、標注了「這個名字含控制字元」，偽造的那台
  `attacker.example.com` **沒有變成訊息裡的一行**。訊息仍然是 3 行、
  `Existing profiles:` 仍然只出現 1 次。

  **訊息的另外一半（點名打平候選的那一段）也擋住了**——我另外做了兩組四欄全對、
  其中一組名字夾換行的情境：

  ```
  ... and 2 stored profiles all match that exact target: 'plain-twin', 'sneaky' [truncated: name contains a control character]. ...
  number of lines : 3
  'Existing profiles:' appears N times : 1
  ```

  兩半用的是同一套處理，沒有其中一邊漏掉。

- **證據**：上述逐字訊息；探針程式 `r1_borrow_and_tie.py`；專案測試
  `test_ambiguous_profiles_refuse_to_borrow`、
  `test_ambiguous_profiles_error_names_both_candidates`、
  `test_identical_password_tie_still_refuses`、
  `test_differing_password_tie_refuses_without_a_password_claim`、
  `test_refusal_hostile_profile_name_with_newline_cannot_forge_a_line`。

- **判定：PASS（通過）**

---

### 3. `get_setup_status` 回報的機制與目標，要和伺服器真正會用的一致，包含名字不是 `default` 的設定

- **我怎麼試的**：每次都在同一個程序裡**問工具一次、問連線程式一次**再比對，走的是
  真正的 MCP 工具呼叫路徑（和你的代理人同一條）。這次把**三種機制全部走一遍**，
  因為上一輪我回報的「回報不存在的設定名稱」就是在這裡被改掉的。

- **結果**：

  | 情境 | `source` | `profile` 欄位 | 目標與連線程式一致 | 有洩漏密碼嗎 |
  |---|---|---|---|---|
  | 唯一設定叫 `ichef-dw`（非 default） | `profile` | `'ichef-dw'`（真名） | 是 | 否 |
  | 借用模式 | `borrowed` | **`None`** | 是 | 否 |
  | 一般 inline（有真密碼） | `inline` | **`None`** | 是 | 否 |
  | inline 完全沒密碼 | `inline` | **`None`** | 連線程式拒絕，工具也說 `configured: False` | 否 |
  | 借用模式，呼叫時硬塞 `profile='whatever'` | `borrowed` | **`None`**（沒有被回音） | 是 | 否 |

  借用模式的完整回傳：

  ```
  {'profile': None, 'source': 'borrowed', 'configured': True, 'has_fields': True, 'has_password': True, 'host': 'dw.example.com', 'port': 5439, 'user': 'analyst', 'dbname': 'prod', 'borrowed_from_profile': 'lender'}
  ```

  **上一輪這裡是 `'profile': 'default'`——一個電腦上根本不存在的名字。** 現在是
  `None`，而真正借出密碼的那組仍然清楚地放在 `borrowed_from_profile`。我特地測了
  「呼叫時硬塞一個名字進去」，確認它**不會被原樣回音**。

  profile 模式仍然正確回報真名 `ichef-dw`（改之前這裡會說 `configured: False`）。

- **證據**：五個情境的逐字回傳；探針程式 `r3_status.py`；專案測試
  `test_get_setup_status_profile_mode_named_other_than_default_reports_configured`、
  `test_get_setup_status_borrowed_mode_profile_field_is_none`、
  `test_get_setup_status_inline_mode_profile_field_is_none`。

- **判定：PASS（通過）。** 但「多組相符被拒絕」這個新情境下，這個工具給的建議會把
  人帶錯方向——寫在後面「驗收條件沒點到」第 1 點，我認為那是這次最值得你看的一項。

---

### 4. 密碼以「未被替換的設定佔位符」形式送進來時，要當成「沒有密碼」，不是「有一個叫這個名字的密碼」

這條的程式碼自從上次驗證後**沒有被動過**。但因為它會落到已經改過的「借用」路徑上，
我還是在 `47910d5` 重跑了一次。

- **結果**：

  ```
    launch: --password ${user_config.password}
      mechanism                       : 'borrowed'
      treated as a real password?     : False
      password actually used is the placeholder text : False
      password actually used is the stored one       : True

    launch: REDSHIFT_PASSWORD=${user_config.password}
      （同上）

    launch: --password '' (blank field)
      （同上）

    CONTROL: a real password must still win over the stored one
      mechanism                       : 'inline'
      uses the inline password        : True
  ```

  三種送法**都沒有拿佔位符文字去登入**，全部正確改走借用；真密碼的對照組也正常。
  把能借的設定拿掉再問狀態工具，它也老實回報 `configured: False`。

- **證據**：上述逐字輸出；探針程式 `a34_status_placeholder.py`（在 `47910d5` 上
  重跑）；專案測試 `test_resolve_inline_params_password_placeholder_is_no_password`
  等四項。

- **判定：PASS（通過）**

---

### 5. 伺服器或它的 CLI 發出的訊息，都不可以建議用指令參數傳密碼

**這條是上一輪唯一附帶警告的一條，現在乾淨了。**

- **我怎麼試的**：用**和上次完全相同的量法**（實際把訊息叫出來再搜，不是搜原始碼），
  並且照 W0-09 的說法多加了兩個上次沒量的表面：MCP 的**開場說明字串**，以及
  **每個工具的輸入參數結構**。這次總共掃了 **43 段**（上次 29 段）。

- **結果**：

  ```
  messages checked : 43
  messages naming --password : 0
  ```

  逐項全部 `ok`：7 種連線拒絕訊息（含新增的「多組相符」拒絕）、3 種狀態工具提示、
  開場說明字串、13 個工具說明、13 個工具參數結構、6 個 CLI 子指令輸出。

- **可對照的那個數字**（這是上一輪提出這項修正的原因，所以照同樣方式再量一次）：

  | 版本 | `get_setup_status` 工具說明裡提到 `--password` 的行數 | 所有送上線的表面合計 |
  |---|---|---|
  | 分支起點 `3821be8` | 1 | 1 |
  | 上一輪 `8e4d0b7` | **2** | 2 |
  | 現在 `47910d5` | **0** | **0** |

- **證據**：43 項逐項掃描結果；探針程式 `r5_sweep.py`；專案測試
  `test_no_tool_description_mentions_password_flag`、
  `test_no_wire_surface_mentions_password_flag`、
  `test_no_stray_password_flag_recommendation_in_source`。

- **一點保留**：CLI 的 `--help` 仍然會列出 `--password PASSWORD` 這個參數本身，
  這是刻意保留的（需求書明寫這個參數是既有的公開整合路徑，不在移除範圍）。

- **判定：PASS（通過）**

---

### 6. 外掛表單說明和三份 README 要講同一條「密碼留空」的規則，而且那條規則就是程式實際遵守的

**這一條自從上次驗證（`8e4d0b7`）後完全沒有被動過，沿用上次的證據，沒有重新推導。**
我用差異比對確認了這件事：四份文件加上兩個版本號檔案，在 `8e4d0b7..47910d5` 之間的
差異是**空的**。

上次驗證的結論：四份文件**全部一致**，四個欄位名稱都在，都寫了「四者全對」和
「連到你填的目標」，**沒有任何一份還留著排除 port 的舊講法**。

- 外掛表單：「Leave blank to borrow the keychain password of a profile … whose
  **host, port, user and dbname all match** the values above — the connection
  always goes to what you typed here, never to the profile's」
- 英文版：「… whose **host, port, user and dbname all match** what you typed
  here, and the connection always goes to the target you typed …」
- 日文版：「**host・port・user・dbname がすべて一致**するものを探し、接続先は常に
  あなたがここで入力した値になります …」
- 繁中版：「找一個 **host、port、user、dbname 四者都對得上**你填的值的，借用它
  keychain 裡的密碼，連到你填的那個目標 …」

「這條規則就是程式實際遵守的」這半句，由本次重走的第 1 條和第 2 條直接證明。
版本號兩處仍然同步在 `0.12.0`；`.mcpb` 套件的表單把 password 標成 `required=True`，
那條路徑走不到「密碼留空」。

- **判定：PASS（通過，沿用上次證據）**

---

### 7. 上面每一條驗收條件，都要有一個「拿去跑改動前的舊程式會失敗」的測試

測試集這次變大了（新增 12 個測試），所以整條重做。從分支起點 `3821be8` 開第二份
完全獨立的副本，各自重裝相依套件，把 `47910d5` 的測試檔複製過去跑。

**在相信任何數字之前，先讓 pytest 印出它到底載入了哪一份程式**：

```
=== PROVENANCE OF THE CODE UNDER TEST ===
package     : .../scratchpad/wt2/base/src/redshift_comment_mcp/__init__.py
server      : .../scratchpad/wt2/base/src/redshift_comment_mcp/server.py
server has resolve_connection_decision : False
server has _SubstitutedPort            : False
tools has ConnectionDecision           : False
```

路徑落在「分支起點副本」自己的資料夾，新增的東西**確實都不存在**。

**結果：29 個測試在舊程式上失敗**（上一輪是 21 個）。

| 驗收 | 在舊程式上變紅的測試 | 失敗原因對不對 |
|---|---|---|
| 1 | `test_four_field_match_borrows_and_uses_inline_values`、`test_single_matching_profile_still_borrows_despite_ambiguity_check`、`test_borrow_mistyped_port_refuses_to_borrow`、`test_borrow_blank_and_placeholder_port_still_borrow` | 是——舊程式根本不會去借 |
| 2 | `test_port_mismatch_refuses_and_names_both_ports`、`test_mismatched_profile_raises_naming_both_hosts`、`test_no_profiles_at_all_raises`、`test_refusal_two_profiles_differing_only_in_dbname_render_distinctly`、`test_borrow_scan_store_failure_...`（3 個參數版本）、**`test_ambiguous_profiles_refuse_to_borrow`**、**`test_ambiguous_profiles_error_names_both_candidates`**、**`test_identical_password_tie_still_refuses`**、**`test_differing_password_tie_refuses_without_a_password_claim`**、**`test_render_profile_name_clean_name_unaffected`**、**`test_render_profile_name_truncates_at_first_control_character`**、**`test_refusal_hostile_profile_name_with_newline_cannot_forge_a_line`** | 是 |
| 3 | 見下方說明 | 是 |
| 4 | `test_resolve_inline_params_password_placeholder_is_no_password` 等四項 | 是——舊程式把佔位符當成真密碼 |
| 5 | `test_missing_password_error_does_not_recommend_password_flag`、`test_get_setup_status_inline_next_step_does_not_recommend_password_flag`、`test_no_stray_password_flag_recommendation_in_source`，另見下方說明 | 是——訊息逐字指出 `server.py:117 recommends the --password flag` |
| 6 | `test_blank_password_rule_stated_consistently`（四份文件各一） | 是——四份都缺「四者全對」「沒對上就拒絕」 |

**第 3、5 條我一樣多做了一步。** 覆蓋這兩條的六個測試住在 `tests/test_tools.py`，
這個檔案**在舊程式上連載入都載入不了**，所以反向執行只報「收集錯誤」，而不是
「斷言抓到了舊行為」。收集錯誤是很弱的證據。所以我把那**六個測試的斷言原封不動
搬到一個兩邊都跑得起來的新檔案**：

```
舊程式（3821be8）：6 failed
  test_..._profile_mode_named_other_than_default_reports_configured
    E   assert False is True                       <- configured 是 False
  test_..._borrowed_mode_reports_inline_host_and_borrowed_source
    E   AssertionError: assert 'inline' == 'borrowed'
  test_get_setup_status_borrowed_mode_profile_field_is_none
    E   AssertionError: assert 'default' is None
  test_get_setup_status_inline_mode_profile_field_is_none
    E   AssertionError: assert 'default' is None
  test_no_tool_description_mentions_password_flag
    E   AssertionError: tool descriptions naming --password: ['get_setup_status']
  test_no_wire_surface_mentions_password_flag
    E   AssertionError: wire surfaces naming --password: ['get_setup_status.description']

這次的版本（47910d5）：6 passed
```

同一組斷言，舊的紅、新的綠。最後兩項特別值得一提：它們正是**從我上一輪那個發現
長出來的測試**，而且它們在舊程式上**確實抓到了那 1 處**。

- **判定：PASS（通過）**

- **一個誠實的補充**（沿用上輪）：`test_blank_password_rule_no_longer_excludes_port`
  在舊程式上是綠的。它守的是「不可以再寫回修訂前那版『port 不算』的講法」，而那版
  講法在分支起點還沒存在過，所以它在那裡當然不會紅。它防的是未來的回退。

---

## 驗收條件沒點到、但我注意到的事

> **這一節在第三次修訂時有一項更正、三項結案。**
> 第 1 項我原本評為「重要」，理由是「照著狀態工具給的建議做不會解決問題」。
> **那句話是錯的，我後來實測推翻了自己第一次的判讀**——照它的建議做**確實會**
> 解決問題。我已經把嚴重程度降為「小問題」並改寫理由（見下）。這種錯誤的方向
> 特別糟：一個把自己講得比實際嚴重的發現，會害你在該放行的時候多花成本，比
> 講得太輕還傷人，所以我把更正的經過完整留在這裡，不是默默改掉。
> 第 2、3、4 項都已經修好了，各項底下記錄了修在哪裡。

### 1. 「多組相符被拒絕」時，狀態查詢工具沒有點出真正的原因〔小問題〕

**先講更正。** 我第一版寫的是「照狀態工具的建議做**不會**解決問題」。我後來
在 `166bf07` 上實際跑了一次，**推翻了自己這個判讀**：

```
step 1 — tie, no env var:
   refused. names both candidates : True

step 2 — same tie, with REDSHIFT_PASSWORD set:
   CONNECTED to warehouse.example.com:5439/prod as analyst
   mechanism                       : 'inline'
   uses the operator's own password: True
   borrowed a tied secret instead  : False
   ambiguous_profiles              : None
```

你自己給了密碼，程式就**根本不會去翻設定檔借密碼**，所以「兩組打平」這件事
從一開始就不會發生。**那個建議是對的、而且有效。** 我原本的說法是錯的。

**那還剩下什麼問題？** 只剩「不夠省事」跟「沒說原因」這兩點小事：

兩組設定四欄全對時，連線程式拒絕得非常清楚，而且給了**兩條**路：

```
... 2 stored profiles all match that exact target: 'tie-a', 'tie-b'. Refusing to guess ...
Delete or rename the stale profile so only one matches this target, or provide the REDSHIFT_PASSWORD env var directly.
```

但**同一個時刻**去問 `get_setup_status`——那是代理人唯一能問「我現在是什麼狀態」
的工具——它回的是：

```
{'profile': None, 'source': 'inline', 'configured': False, 'has_fields': True,
 'has_password': False, 'host': 'dw.example.com', ..., 'next_step':
 "Inline mode: the server was launched with host/user/dbname but no password.
  Set the REDSHIFT_PASSWORD env var where the MCP server is launched ...
  then restart the MCP client."}
```

它給的是那兩條路裡**比較費事的那一條**（設環境變數、重開 MCP 用戶端），而且
**完全沒有提到「有兩組設定打平」這件事**——所以比較省事的那一條（刪掉或改名其中
一組，一勞永逸）你不會從這個工具知道。決策物件裡其實有 `ambiguous_profiles`
這個欄位帶著答案，狀態工具沒有把它放進回傳。

**而且有一個現成的補救**，我實測確認過：連線程式那則完整的拒絕訊息（含兩組打平
的名字、含「刪掉或改名」這條省事的路）**會原封不動出現在任何一個資料庫工具的
「尚未設定」回應裡**。我呼叫 `list_schemas` 拿到的回應中：

```
list_schemas returned keys : ['error', 'exception_class', 'message', 'next_step']
   names 'rotated-old' : True
   names 'rotated-new' : True
   carries 'Delete or rename' (the cheap remedy) : True
   leaks a tied secret : False
```

也就是說，**省事的那條路離代理人只有一次工具呼叫的距離**——它只是不會主動從
狀態查詢工具那裡得到。

嚴格講第 3 條仍然 PASS：它問的「機制」（`inline`）和「目標」都正確，工具也沒有
謊稱自己連得上，而且它給的建議確實有效。剩下的只是「可以更省事、可以更清楚」，
所以我評為**小問題**。（我第一版評為「重要」，那是基於上面那個已被我自己推翻的
錯誤判讀。）

### 2. 程式註解說「不會去讀那些打平設定的密碼」——實際上會讀，只是不比對〔已修好〕

**已於 `166bf07` 修好，而且修得比我找到的還徹底。** 我當時只找到 2 處，實際上
有 **4 處**都寫錯了，四處全部改成「每組候選會讀一次密碼——正是這個讀取決定它算不算
候選——但從不比對」，同時保留了「絕不外洩」這個本來就為真的說法。以下是我原本的
觀察內容，留作紀錄。

程式和資料結構的說明文字都寫著「The scan never reads the tied profiles' passwords
to decide this」。我實際量了一次**單一次**解析過程中對鑰匙圈的讀取：

```
ONE resolve_connection_params call on a 2-profile tie
  keychain get_password calls : 2 -> ['tie-1', 'tie-2']
  both tied secrets were read into memory : True
  either secret appears in the message    : False

For comparison, a SINGLE match (no tie):
  keychain get_password calls : 1 -> ['tie-1']
```

每一組相符的設定**都會被讀出密碼**（因為「有沒有密碼」正是它算不算候選的條件），
兩個密碼都短暫進到記憶體裡。程式**沒有做的是「比對」它們**，訊息也確實沒有洩漏
或宣稱任何關於密碼的事。

所以**行為是對的、安全性也沒問題**，但那句說明寫得比實際情況強。如果有人日後
根據「這條路徑不碰鑰匙圈」來做判斷（例如假設沒有鑰匙圈的機器也能走到這裡），
就會判斷錯。

### 3. 計畫書上 W0-09 的描述和實際出貨的行為不一致〔已修好〕

**已於 `e03b27e` 修好**：計畫書 W0-09 那一段改成描述實際出貨的「一律拒絕」規則，
不再是被推翻的「密碼相同就借出」。以下是我原本的觀察內容，留作紀錄。

計畫書 W0-09 那一段原本寫的是：

- 測試項：「A3 positive: **identical-password-tie-lends**」（密碼相同的打平**會借出**）
- 風險決策：「**compare the collected secrets** rather than dropping the claim,
  since a tie with one secret has nothing to guess between」（去**比對**收集到的密碼）

但**實際出貨的程式是：任何四欄打平一律拒絕，而且從不比對密碼**——我實測密碼
完全相同的兩組設定，照樣被拒絕（見第 2 條）。專案自己的測試也叫做
`test_identical_password_tie_still_refuses`（「仍然拒絕」）。

**出貨的行為我認為是對的**（理由很好：讓你光看 `config.toml` 就能預測結果）。
問題在於計畫書還留著被推翻前的那個版本，任何人照著計畫書讀都會以為密碼相同時
會借出。

### 4. 名字開頭就是控制字元時，訊息說不出是哪一組出問題〔已修好〕

**已於 `166bf07` 修好**：那句過強的說明改成正確描述「前綴為空」這個情況，並且把我
實測出來的切斷範圍一併記進去（換行、歸位字元、ANSI 跳脫、NUL、DEL 會被切斷；
U+2028 / U+2029 不切斷，改由引號轉義處理）。以下是我原本的觀察內容，留作紀錄。

控制字元的防護本身很紮實。我試了換行、歸位字元、ANSI 終端跳脫序列、NUL、DEL
五種，**全部在第一個控制字元處被切斷**，沒有一種能偽造出多一行：

```
  carriage return        -> 'abc' [truncated: name contains a control character]
  ANSI escape            -> 'abc' [truncated: name contains a control character]
  NUL byte               -> 'abc' [truncated: name contains a control character]
  DEL 0x7f               -> 'abc' [truncated: name contains a control character]
```

我也試了 Unicode 的行分隔符 U+2028 / U+2029（不在控制字元範圍內）——它們**沒有
被切斷，但也不構成問題**，因為外面那層引號處理會把它們轉成 ` ` 這樣的字面
文字，同樣切不出新的一行。這點是安全的。

唯一不理想的是：如果名字的**第一個字元**就是控制字元，切出來的前綴是空的：

```
Existing profiles: '' [truncated: name contains a control character] (host='zz.example.com' port=5439 user='u' dbname='d')
```

程式註解說「操作者仍然看得到是哪一組出問題（那個被切斷的前綴）」——這個情況下
看不到。不過旁邊仍然印著那一組的 host / port / user / dbname，所以你還是有辦法
認出來，只是不能靠名字。影響很小，但那句註解的說法過強。

---

## 其他跑過的測試

| 這一批 | 結果 |
|---|---|
| 不需要資料庫的單元測試（乾淨副本、`47910d5`） | **448 通過、2 跳過**（上輪 436／2） |
| 專案隨附的對抗測試案例（未修改） | **38 個全部通過**（上輪 32 個） |
| 需要真實叢集的整合測試 | **無法驗證**（叢集連線逾時，發生在程式邏輯之前） |
| MCP 協定測試（e2e，6 項） | **4 失敗、2 通過**——既有問題，非這次造成 |

**關於 e2e，有兩件事要更正上一版報告和交辦說明：**

1. **它們不會無限卡住。** 底層連線程式庫自己有 60 秒逾時，整批 156 秒跑完。
   上一版報告寫「有 2 項會卡住」是錯的，這裡更正。
2. **失敗幾項取決於 fastmcp 版本。** 我這次和上次解析到的都是 **fastmcp 4.0.5**，
   在這個版本下 MCP 開場說明在連線握手時是**空字串**，所以兩項檢查開場說明的
   測試會失敗，加上兩項需要真實叢集的，共 4 失敗 2 通過。交辦說明提到的
   **fastmcp 3.2.4** 環境下開場說明正常，只有需要叢集的那 2 項失敗。差異完全來自
   套件版本，不是程式碼。

   我實測：程式內部的開場說明字串在 `47910d5` 有 6096 個字、有提到 borrowed、
   也不含 `--password`；但走真正的 MCP 握手時用戶端收到 `''`。分支起點的副本
   同樣解析到 fastmcp 4.0.5，e2e 結果也同樣是 4 失敗 2 通過——**所以這不是這次
   改壞的**。後果是：W0-05／W0-09 在開場說明上做的工，在 fastmcp 4 環境下對真實
   使用者是看不到的。

「無法驗證」不等於「通過」——叢集恢復之後，整合測試那一批還是得補跑才算數。

---

## 對你既有的資料做了什麼

**你的設定檔和系統鑰匙圈，一個位元組都沒有動。** 全程設定檔位置指向用完即丟的
暫存資料夾，鑰匙圈全程換成只存在記憶體裡的假貨——每一支探針程式開頭都有一道
**強制檢查**：確認設定檔路徑不等於你真正的路徑、確認鑰匙圈物件是假的、並且實際
寫一筆再讀回來證明程式呼叫到的是那個假貨，任何一項不成立就中止不跑。

兩次驗證結束後都直接比對你真正的設定檔：

```
第一次驗證前 sha256 : 17caa5cbe9da254a16c9851f0fff7348e04a97689e46911361d17a5afc80de1b
這次驗證後   sha256 : 17caa5cbe9da254a16c9851f0fff7348e04a97689e46911361d17a5afc80de1b
第一次驗證前 mtime  : May  8 10:05:45 2026
這次驗證後   mtime  : May  8 10:05:45 2026
系統鑰匙圈          : 仍然只有一筆 acct="default"，沒有新增
設定資料夾          : 只有 config.toml 一個檔案，沒有殘留暫存檔
```

內容、修改時間、權限、鑰匙圈筆數**全部與第一次驗證開始前完全相同**。

至於這個修改**上線之後**對你既有資料的影響：設定檔格式沒有改，既有設定不需要
轉換、不需要備份。行為上的變化是「密碼欄留空」這個以前會直接報錯的狀態，現在會
去找四欄全對的設定借密碼——**找不到、或找到超過一組，都拒絕，不會連到別的地方**。
你目前唯一的那組設定（`default`）不會因為這次改動而需要任何調整。

**唯一值得你留意的情境**：如果你哪天換密碼時，新舊兩組設定指向同一台機器、同一個
帳號、同一個資料庫、同一個埠都留著，那麼「密碼欄留空」這條路會**拒絕連線**。這是
刻意的，但如果你不知道，可能會覺得莫名其妙。要解開有兩條路，實測兩條都有效：
刪掉或改名其中一組（一勞永逸，比較省事），或是直接把密碼填進表單／設
`REDSHIFT_PASSWORD`（你自己給了密碼，程式就不會去借，打平的問題自然不存在）。
拒絕訊息本身兩條路都寫了。

---

## 我替你決定的事

- **第 1 條的「連線」我拆成三層來證明，而不是宣稱「連上了」。** 叢集連不上是今天
  的事實（我自己用最原始的方式測過，8 秒逾時），所以我在三個關卡各留一份證據，
  並明講第三層用的是本機假監聽程式、**只證明去向、不證明登入成功**。如果你認為
  沒有真的登入過就不該算 PASS，這裡是你會想推翻我的地方。
- **第 3 條我判 PASS。** 依據是驗收條件問的「機制」和「目標」兩者都正確，工具也
  沒有謊稱自己連得上，而且它給的建議實測有效。
- **我把自己一個原本評為「重要」的發現，親手降級為「小問題」。** 我原本寫「照狀態
  工具的建議做不會解決問題」，後來實測**推翻了自己**：照做確實會解決。降級的理由
  和完整經過都留在「沒點到的事」第 1 點，沒有默默改掉。我認為你有權看到我判錯過
  這件事——一份把問題講得比實際嚴重的報告，會害你在該放行的時候多花成本。
- **第三次修訂我沒有重走七條驗收，只查證「那兩筆提交真的只動說明文字」。** 依據是
  我自己做的語法樹比對（把說明文字拿掉後兩個版本完全相同），不是採信交辦說法。
  另外因為說明文字會送到代理人面前，我額外重量了 `--password` 數量（仍為 0）和
  多組相符的拒絕訊息（一字未變）。如果這個依據錯了，問題會出在這裡。
- **第 5 條這次判 PASS 沒有附帶警告**，因為用同一套量法量出來是 0。上一輪我在這裡
  附了警告，那個警告後來被接受並修掉了。
- **第 6 條我沒有重新推導，直接沿用上次證據。** 依據是 `8e4d0b7..47910d5` 對那四份
  文件與兩個版本號檔案的差異是空的。如果這個依據錯了，問題會出在這裡。
- **第 3、5 條的反向驗證，我沒有接受「收集錯誤」當證據**，另外寫了一組兩邊都跑得
  起來的移植測試。多花的這一步改變了證據強度，沒有改變結論。
- **MCP 協定測試的 4 個失敗，我記為「既有問題」而不是這次的失敗。** 依據是分支
  起點跑出完全相同的結果，而且差異可由 fastmcp 版本完整解釋。
- **沒有任何審查者把嚴重程度「重要」以上的意見交給我、也沒有這類意見被駁回後轉交
  給我記錄。** 上一輪我提出的三項觀察都被接受並修掉了（W0-08），不是被駁回。
- **我沒有修任何東西。** 上面每一項觀察我都只記錄。唯一動過的程式是我自己的探針
  和隔離檢查，全部在暫存資料夾裡，不在專案內。

---

## 我不確定你要不要

1. **「多組相符被拒絕」時，要不要讓 `get_setup_status` 也講出這件事？** 它現在給的
   建議（設環境變數）**實測有效**，只是比較費事；比較省事的那條（刪掉或改名其中
   一組）它沒有主動說。答案已經在程式內部的 `ambiguous_profiles` 欄位裡，只是沒有
   放進回傳。**這是目前唯一還開著的一項，而且只是小問題**——因為完整的拒絕訊息
   本來就會出現在任何資料庫工具的「尚未設定」回應裡，省事的那條路離代理人只有
   一次工具呼叫。
2. **開場說明在 fastmcp 4 之下是空的，要不要提高優先序？** 這不是這次改壞的，但它
   讓 W0-05／W0-09 在開場說明上做的工完全看不到。
3. **需要真實叢集的整合測試，要不要等連線恢復之後補跑一次再正式核准？**

（上一版列在這裡的第 2、3 項——計畫書 W0-09 的描述、以及「不會讀密碼」那句註解
——都已經修好了，分別在 `e03b27e` 和 `166bf07`，不再是待決事項。）

---

## 語言與格式規則檢查

| 文件 | 規則 | 結果 | 依據 |
|---|---|---|---|
| 需求書（intent） | 全英文 | 符合 | 全文無中日文字 |
| 規劃書（plan.md） | 全英文 | 符合（三處例外，且該例外正確） | 三處中日文字全部在「問過你的原話」逐字記錄段落，是保留你原本的輸入 |
| 設計規格 | EARS `REQ-<n>` 條列 | 不適用 | 需求書明寫 `needs-design: no` |
| 審查意見 | Conventional Comments 標籤 | 不適用 | 這個變更的資料夾裡沒有審查意見文件，也沒有「重要」以上的意見被駁回後轉交給我 |
| 證據檔（對抗探針程式） | 全英文 | 符合 | 六支探針程式全部 0 處中日文字 |
| 測試說明文字（docstring） | 全英文 | 符合 | `test_server_resolution.py` 0 處。`test_tools.py` 有 122 處，**全部是改動前就存在的**（分支起點同樣 122 處，本分支新增 0 處）。`test_repo_invariants.py` 新增 6 處，全部是日文版／繁中版 README 的比對字串本身——測試對象就是多語文件，屬於正確的例外 |
| 測試命名 | `test_<單元>_<狀態>_<預期>` | 部分符合 | 語意上都是三段式（例如 `test_identical_password_tie_still_refuses` = 單元 identical_password_tie／狀態 still／預期 refuses），但沿用專案既有的敘述式風格，沒有嚴格用底線切成剛好三段 |
| 提交訊息 | 全英文 | 符合 | 分支起點以來 22 筆提交（含本報告前兩版那兩筆），標題與內文皆 0 處中日文字 |

---

## 我沒能做到的事

- **「真的登入進 Redshift」沒有驗證到**——叢集連不上（原始 TCP 測試 8 秒逾時）。
  第 1 條的「連線」只能證明到「往正確的位址、帶著正確的密碼開出一條真實連線」。
- **需要真實叢集的整合測試那一批，完全沒跑。**
- **第 6 條沒有重新推導**，沿用上次證據，依據是那四份文件的差異為空。
- **沒有找到獨立成檔的審查意見文件**可供逐條核對 Conventional Comments 標籤規則。
- 上面列出的每一項觀察我都**只記錄、沒有修**。
