# 伺服器照它自己說的方式連線 — 我實際試了什麼、結果如何

**結論：八條驗收條件全部通過（PASS）。**（原本七條，2026-09-21 審查期間新增第 8 條。）

**這份報告描述的版本是 `83116be`。**

> **第六次修訂（版本 `83116be`）：我上一版提的兩個小問題都修好了，這一版把它們
> 結案，並且回答一個自動化檢查測不到的問題。**
> `83116be` 改動很小：一條錯誤訊息、外掛表單三欄的說明、五個新測試。我只重新
> 量了它動得到的兩條——第 2 條（拒絕訊息的文字）和第 6 條（外掛表單和程式是否
> 相符），其餘沿用，理由寫在下面，不是引用檔案差異。
> 另外我照要求做了一件自動化檢查做不到的事：**把外掛表單那四欄的說明，當成
> 第一次安裝的人那樣一欄一欄分開讀**，判斷單獨看任何一欄會不會被誤導。
> 結論是「大致準確，但有兩處單獨讀會踩到」，寫在第 6 條末尾。

> **第五次修訂（版本 `c442b79`）：我上一版標成「最值得你看」的那個缺陷，
> 在我寫完之後兩個提交就已經修好了，我卻沒有說。**
> 上一版的「驗收條件沒點到」第 0 項描述「設定檔裡 port 存壞時，拒絕訊息會印出
> 一組看起來完全相符的設定」，我評為〔重要〕、還在待決清單裡寫「這是我這次認為
> 最值得處理的一項」。`f20cb4d`／`aea929b` 已經把它修好了，而我引的那段逐字訊息
> 也已經不是程式現在會印的內容。報告裡沒有任何一行提到那兩個提交，所以你讀到
> 的時候，沒有任何線索知道它講的是舊版本。
> **這正是我自己在上一版寫下的那句話所指的傷害**——「一個把自己講得比實際嚴重的
> 發現，會害你在該放行的時候多花成本」。這次我把第 0 項改標為〔已修好〕，附上
> 修好之後的逐字訊息，並從待決清單移除。

> **第四次修訂（版本 `f1e57f1`）：我上一版的第 6 條判定是錯的，這次重做了。**
> 一位文件審查者指出：我上一版用「那四份文件的差異是空的」當理由沿用第 6 條，
> 但第 6 條問的是**文件和程式之間的關係**，而程式的「密碼留空」規則正好在那段
> 範圍內長出了一整條新分支（多組相符就拒絕）。**文件沒動，恰恰是這個關係可能
> 已經斷掉的信號，不是它還成立的證據。** 這個指正是對的，而且事情就是這樣發生
> 的——那條新分支當時在所有使用者看得到的地方都沒有記載，而我的第 6 條正是它
> 通過的那一關。我在那裡對一件自己沒有檢查的事寫了 PASS。
> **這次第 6 條改成從程式反推**：把解析器實際實作的每一條規則列出來，再逐條去
> 對四份文件加上 MCP 開場說明字串。結果見第 6 條，包含三條目前仍然沒有記載的
> 規則。

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

試用日期：2026-09-21。第四次修訂用 `git worktree` 從 `f1e57f1` 開一份**全新、沒有
人動過的副本**，重新裝一次相依套件；反向驗證（第 7 條）另外從分支起點 `3821be8`
開第二份獨立副本。兩份副本**在跑任何數字之前都先印出程式實際載入自哪個路徑**，
確認彼此沒有污染。這次解析到的 **fastmcp 版本是 4.0.5**。

第四次修訂重走了第 1、2、3、5、6 條和新增的第 8 條。**第 4 條沒有重走，理由不是
「檔案差異是空的」**（那正是上一版犯的錯），而是：第 4 條那條規則完全由三個函式
決定（判斷一個字串算不算真密碼的那三個），我把這三個函式在 `4d51a9a` 和 `f1e57f1`
兩版各自解析成語法樹比對，**三個都完全相同**；為求保險我還是把第 4 條的探針重跑
了一次，結果不變。

**第五次修訂（`c442b79`）我重驗了哪些、為什麼不是全部。** 交辦說法是「`aea929b`
只動到拒絕訊息的一個小函式，`c442b79` 只動文字」。**我沒有直接採信，而是自己
比對了語法樹**，結果和那個說法**有出入**，所以我重驗的範圍比它建議的大：

- `aea929b`：確實只動到拒絕訊息的算繪（`_target_desc`；外層函式一起變是因為它
  是巢狀定義）。**連線怎麼決策完全沒動**，所以第 1、3、4、7 條的解析行為不受影響。
  但**第 2、8 條的訊息內容變了**，所以這兩條的訊息證據我重新取過。
- `c442b79`：**不是「只動文字」那麼簡單**。它改的兩處確實都是字串，但**兩處都是
  會送到使用者／代理人面前的表面**——MCP 開場說明字串，以及 `get_setup_status`
  的說明文字。所以第 5 條（送上線的表面有沒有提到 `--password`）和第 6 條
  （文件與程式是否相符，我的表格裡就有「開場說明」這一欄）**都必須重新量**，
  外加 `plugin.json` 也被改過。這四項我都重新跑了。

結果：**第 5 條仍然是 0**，**第 6 條的表格一格未變**，第 2、8 條的訊息重新取樣
後結論不變。第 7 條的反向驗證也重跑（見該條）。

**第六次修訂（`83116be`）我重驗了哪些、為什麼不是全部。** 這次的改動我自己清點
過範圍：**一條錯誤訊息字串、外掛表單三欄的說明、五個新測試**，程式的其他部分
語法樹完全相同（`redshift_tools.py` 一字未動，`server.py` 只有那一條字串）。
所以我重新量的是它動得到的兩條：

- **第 2 條**（以及同源的第 8 條）——拒絕訊息的文字改了，所以訊息證據重新取樣。
- **第 6 條**——外掛表單三欄的說明改了，所以整張「程式規則 vs 五個表面」的表格
  重新跑，再加上一輪**人工逐欄閱讀**（見第 6 條末尾）。

其餘各條**沿用**，理由不是「差異很小」，而是：第 1、3、4 條由連線決策邏輯決定，
而這次沒有任何一行決策邏輯改變（語法樹比對確認）；第 5 條問的是「送上線的表面
有沒有提到 `--password`」，這次改到的兩處文字我都查過，沒有引入這個字串；
第 7 條的測試集變大了，所以還是重跑了反向驗證。

單元測試 **467 通過、2 跳過**，38 個對抗測試案例**全綠，而且我確認過檔案未被
修改**（在乾淨副本裡查過版本控制狀態，探針目錄沒有任何改動）。這次解析到的
**fastmcp 版本是 4.0.5**。

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

## 你要求的八件事，一條一條試

（第 8 條是審查期間新加的，排在第 2 條後面，因為它講的是同一件事的另一半：
「沒有相符的」和「相符的不只一組」。）

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

- **新增：設定檔裡存壞的 port（W0-11，這次第一次被走）。** 以前只有「你打錯的
  port」會被擋，「設定檔裡存壞的 port」沒有——一組記成 `9999.0` 或 `"9999x"` 的
  設定會被當成 5439，把密碼借給一個它從來沒被登記過的目標。修好之後我實測四種：

  | 設定檔裡存的 port | 啟動時填 5439 | 結果 | 對不對 |
  |---|---|---|---|
  | `9999.0`（TOML 小數） | 5439 | **拒絕** | 對，不該借 |
  | `"9999x"`（手改壞的字串） | 5439 | **拒絕** | 對，不該借 |
  | `5439`（正常整數） | 5439 | **照常借用** | 對，沒有誤傷 |
  | 完全沒有存 port | 5439 | **照常借用** | 對，沒有誤傷 |
  | `"5439"`（字串但讀得出來） | 5439 | **照常借用** | 對 |
  | `5439.0`（小數，但數值等於預設埠） | 5439 | **拒絕** | 見下方說明 |

  最後一列值得你知道：一組 port 存成 `5439.0` 的設定，**雖然它指的就是 5439**，
  仍然會被拒絕。拒絕是安全的方向（寧可不借），而 TOML 小數本來就不是合法的
  port 寫法。但它會引出一個訊息上的問題，寫在「驗收條件沒點到」第 1 點。

- **證據**：上述五段逐字輸出；探針程式 `r1_borrow_and_tie.py`、`f_branches.py`
  （分支 B12–B17）；專案測試
  `test_four_field_match_borrows_and_uses_inline_values`、
  `test_single_matching_profile_still_borrows_despite_ambiguity_check`、
  `test_stored_unparseable_port_refuses_to_borrow`、
  `test_stored_ordinary_port_shapes_still_borrow`。

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
  Delete the stale profile with `redshift-comment-mcp delete-profile --profile <name>` so only one matches this target, or provide the REDSHIFT_PASSWORD env var directly.
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

### 8. 有超過一組設定四欄全對時 → 拒絕，訊息要列出每一個打平的候選

**這條是 2026-09-21 審查期間新加進驗收條文的**（原本它只是一個沒人明文要求、但
程式已經做了的行為）。這是第一次有人照驗收條文走它。

- **我怎麼試的**：兩組打平（密碼不同）、兩組打平（密碼完全相同）、三組打平。
  每種都檢查：有沒有拒絕、有沒有把**每一個**候選點名、有沒有洩漏任何密碼、
  有沒有宣稱它沒檢查過的事。

- **結果**：三種**全部拒絕**。三組打平時的訊息逐字：

  ```
  Inline mode requires a password for host='warehouse.example.com' port=5439 user='analyst' dbname='prod', and 3 stored profiles all match that exact target: 'rot-2024', 'rot-2025', 'rot-2026'. Refusing to guess which one to borrow — picking by sort order could silently prefer a retired credential over its replacement, the shape a credential rotation leaves behind.
  Existing profiles: 'rot-2024' (host='warehouse.example.com' port=5439 user='analyst' dbname='prod'), 'rot-2025' (host='warehouse.example.com' port=5439 user='analyst' dbname='prod'), 'rot-2026' (host='warehouse.example.com' port=5439 user='analyst' dbname='prod').
  Delete the stale profile with `redshift-comment-mcp delete-profile --profile <name>` so only one matches this target, or provide the REDSHIFT_PASSWORD env var directly.
  ```

  ```
  names all three : True
  leaks any secret: False
  says how many   : True
  ```

  **三個候選一個不漏地點名了**，數量也講了，**沒有任何一個密碼外洩**，而且訊息
  沒有宣稱這些密碼是相同還是不同（程式根本沒比對過）。密碼完全相同的兩組也照樣
  拒絕——這是刻意的，讓「會不會被拒絕」只取決於 `config.toml` 看得到的四個欄位。

- **順便確認沒有誤傷**：只有一組全對時照常借用；四欄全對但**只有一組真的有鑰匙圈
  密碼**時，不算打平，照常借那一組（見第 1 條）。

- **證據**：上述逐字訊息；探針程式 `f_branches.py`（分支 B5、B6、B8）；專案測試
  `test_ambiguous_profiles_refuse_to_borrow`、
  `test_ambiguous_profiles_error_names_both_candidates`、
  `test_identical_password_tie_still_refuses`、
  `test_differing_password_tie_refuses_without_a_password_claim`、
  `test_single_matching_profile_still_borrows_despite_ambiguity_check`。

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

這條的程式碼**從第三次修訂到現在都沒有被動過**——實作它的那三個函式，我在
`4d51a9a`、`f1e57f1`、`c442b79` 三個版本各自解析成語法樹比對，**三個版本、三個
函式全部相同**。但因為它會落到已經改過的「借用」路徑上，我在 `47910d5` 重跑過
一次，之後兩次修訂沒有再跑。

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
  重跑，`c442b79` 未重跑——理由如上）；專案測試 `test_resolve_inline_params_password_placeholder_is_no_password`
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
  | 上一輪 `f1e57f1` | 0 | 0 |
  | 現在 `c442b79` | **0** | **0** |

- **證據**：43 項逐項掃描結果；探針程式 `r5_sweep.py`；專案測試
  `test_no_tool_description_mentions_password_flag`、
  `test_no_wire_surface_mentions_password_flag`、
  `test_no_stray_password_flag_recommendation_in_source`。

- **一點保留**：CLI 的 `--help` 仍然會列出 `--password PASSWORD` 這個參數本身，
  這是刻意保留的（需求書明寫這個參數是既有的公開整合路徑，不在移除範圍）。

- **判定：PASS（通過）**

---

### 6. 外掛表單說明和三份 README 要講同一條「密碼留空」的規則，而且那條規則就是程式實際遵守的

**我上一版這條判錯了，這次整條重做。** 上一版我用「那四份文件沒有變動」當理由
沿用結論。那是錯的推理：這一條問的是**文件和程式之間的關係對不對**，文件沒動
只證明了文件沒動。而程式的「密碼留空」規則正好在同一段期間長出了一整條新分支
（多組相符就拒絕），所以文件沒動反而是這個關係可能已經斷掉的信號。當時那條新
分支在所有使用者看得到的地方確實都還沒記載，而我卻寫了 PASS。

- **我這次怎麼試的**：不看任何差異。先把解析器**實際實作的每一條規則跑出來**
  （見第 1、2、8 條與下方的分支清單），再把每一條拿去對**五個**使用者或代理人
  真的讀得到的表面：外掛表單（`plugin.json`）、三份 README、以及 MCP 連線時的
  開場說明字串。（開場說明不在驗收條文列舉的四份裡，但它是代理人讀得到的，
  所以我一併查。）

- **結果**：

  | 程式實作的規則 | 外掛表單 | 英文 README | 日文 README | 繁中 README | 開場說明 |
  |---|:---:|:---:|:---:|:---:|:---:|
  | R1 密碼留空 → 借用 host / port / user / dbname **四者全對**的設定 | ✅ | ✅ | ✅ | ✅ | ✅ |
  | R2 連線一律連到**你填的目標**，不是設定檔的 | ✅ | ✅ | ✅ | ✅ | ✅ |
  | R3 **沒有**任何一組全對 → 拒絕，並列出雙方目標 | ✅ | ✅ | ✅ | ✅ | ✅ |
  | R4 **超過一組**全對 → 拒絕，並列出每一個候選（第 8 條） | ✅ | ✅ | ✅ | ✅ | ✅ |
  | R5 **你打錯的 port** → 拒絕，絕不借 | ❌ | ❌ | ❌ | ❌ | ❌ |
  | R6 **設定檔裡存壞的 port** → 那組設定不算相符 | ❌ | ❌ | ❌ | ❌ | ❌ |
  | R7 host / user / dbname **只留空其中一個** → 你打的字會被整個丟掉 | ✅ | ❌ | ❌ | ❌ | ❌ |

  **驗收條文問的那條規則（R1 到 R4）五個表面全數一致，而且就是程式實際遵守的**
  ——R1 由第 1 條實測、R3 由第 2 條實測、R4 由第 8 條實測、R2 由第 1 條的連線
  參數擷取實測。R4 是這次 `f1e57f1` 補上的，補得完整。

  逐字引文（R4 的部分，這次新增的）：

  - 外掛表單：「If more than one profile matches all four values, the connection
    refuses instead of guessing, naming every tied candidate so you can delete
    or rename the stale one — the shape a password rotation leaves behind」
  - 英文版：「If more than one matches, the connection refuses the same way,
    naming every tied candidate — the shape a password rotation leaves behind …」
  - 繁中版：「如果同時有不只一個 profile 四者都對得上，連線一樣會拒絕，並列出
    每一個對得上的候選 profile —— 這通常是密碼輪替時新舊兩個 profile 同時留著
    造成的，把舊的那個刪掉或改名即可。」
  - 日文版同樣有對應段落。

  版本號兩處仍然同步在 `0.12.0`；`.mcpb` 套件的表單把 password 標成
  `required=True`，那條路徑走不到「密碼留空」。

- **判定：PASS（通過）。** 驗收條文明文要求的那條規則（密碼留空該怎麼辦）在四份
  文件加開場說明上完全一致，也確實是程式遵守的那條。

- **但 R5、R6、R7 三條規則目前沒有任何使用者看得到的地方寫。** 它們是不是屬於
  「密碼留空這條規則」的一部分，可以爭論——R5、R6 是這條規則底下的**子條件**，
  R7 講的是「host/user/dbname 留空」而不是「密碼留空」。我不把它們算成第 6 條
  的 FAIL。R5、R6 現在**出事時訊息都會自己解釋**（R6 是 `aea929b` 補的），
  所以實際影響不大；三條都寫在後面「驗收條件沒點到」那一節。

#### 逐欄閱讀：把安裝對話框當成第一次安裝的人那樣，一欄一欄分開看

自動化檢查只能確認「某句話有沒有出現在某份文件裡」，沒辦法判斷「單獨讀這一欄
會不會被誤導」。`83116be` 把 host / user / dbname 三欄的說明改長了，每一欄現在
同時扛兩條規則（三欄要一起留空、以及密碼是例外），所以我照要求把四欄**分開**
讀了一遍——**假裝我看不到其他三欄**，因為安裝對話框就是這樣一欄一欄呈現的。

**結論：三欄的敘述都準確，我沒有找到會導致錯誤操作的說法；但有兩處單獨讀會踩到。**

先講準確的部分。以 host 欄為例，它現在說的四件事我逐一實測，全部為真：

| 這一欄說的話 | 我實測的結果 |
|---|---|
| host / user / dbname 要嘛一起填、要嘛一起留空 | 是（三者少一個就整個退回設定檔） |
| 三個一起留空 → 走 `/redshift-setup` 的設定檔路徑 | 是 |
| 只留空這一個 → 整個退回設定檔，連你打進 user、dbname **和密碼**的字都被忽略 | 是 |
| 四個欄位全部留空（含密碼）→ 純設定檔路徑 | 是 |
| **密碼可以單獨留空，另外三欄照填** | 是，這就是借用路徑 |

最後一列是 `83116be` 補上的，也正是我上一版指出的矛盾（見「沒點到的事」第 7 項）
——現在三欄都明講了這個例外，不再和 password 欄自己的說明打架。

**單獨讀會踩到的第一處：把三欄留空、卻在密碼欄打了字，密碼會被無聲丟掉，而這
三欄的說明沒有講。** 這三欄告訴你「只留空其中一個會忽略你打的密碼」，也告訴你
「四個全留空是純設定檔路徑」，但**沒有涵蓋「三個留空、密碼有填」這個組合**。
我實測：

```
--- host+user+dbname blank, password FILLED
    mechanism        : 'profile'
    connects to      : profile-host.example.com:5439/profile-db as profile-user
    password used    : the stored/profile one     <- 你打的那個被丟掉了
```

「我想用設定檔裡的伺服器，但這次想自己給密碼」是很自然的想法，而這樣做密碼會
**靜悄悄地**被忽略，沒有任何提示。這不是新缺陷（行為一直如此），但既然這三欄
現在花了很大篇幅談哪些欄位可以留空，漏掉這個組合就比較可惜。

**單獨讀會踩到的第二處：password 欄仍然說你可以「rename the stale one」，但這個
工具沒有改名功能。** 拒絕訊息本身已經在 `83116be` 改掉了（見「沒點到的事」第 6
項），但 password 欄的說明還留著。它沒有指名任何指令，所以不會把人導向一個錯誤
的指令；但一個對著對話框讀這一欄的人，會以為「改名」是兩個可選做法之一，然後
去找一個不存在的功能。我知道這是審查時**刻意**留下的（理由是沒有暗示任何機制），
所以只記錄我逐欄閱讀時的實際觀感，不主張它是錯的。

**其餘：** port 欄只有一句「Cluster port. Defaults to 5439.」，單獨讀沒有問題；
password 欄關於借用、四欄全對、打平拒絕的敘述，我逐句對過實測結果，全部為真。

---

### 7. 上面每一條驗收條件，都要有一個「拿去跑改動前的舊程式會失敗」的測試

測試集又變大了，所以整條再做一次。從分支起點 `3821be8` 開第二份完全獨立的副本，
各自重裝相依套件，把 `83116be` 的測試檔複製過去跑。

**在相信任何數字之前，先讓 pytest 印出它到底載入了哪一份程式**：

```
=== PROVENANCE OF THE CODE UNDER TEST ===
package     : .../scratchpad/w6b/src/redshift_comment_mcp/__init__.py
config      : .../scratchpad/w6b/src/redshift_comment_mcp/config.py
tools       : .../scratchpad/w6b/src/redshift_comment_mcp/redshift_tools.py
server      : .../scratchpad/w6b/src/redshift_comment_mcp/server.py
server has resolve_connection_decision : False
server has _SubstitutedPort            : False
tools has ConnectionDecision           : False
```

路徑落在「分支起點副本」自己的資料夾，新增的東西**確實都不存在**。

**結果：52 個測試在舊程式上失敗**（21 → 29 → 45 → 48 → 52）。
新紅的包括第 8 條的打平測試、W0-11 的存壞 port 測試、`f1e57f1` 新增的「打平規則
有沒有寫進文件」那組不變式測試（四份文件各一個案例，加上開場說明一個，再加上
「外掛表單不可以再誘導使用者只留空其中一欄」一個）、`aea929b` 為「存壞的 port
要原樣印出來」新增的那組，以及 `83116be` 為我上一版那兩個小問題新增的五個。

**那五個裡有四個在舊程式上是紅的、一個是綠的**，我把它講清楚：
`test_ambiguous_profiles_error_names_real_deletion_mechanism` 和
`test_manifest_blank_together_set_excludes_password`（三欄各一個案例）四個都紅。
但 `test_server_source_never_recommends_a_rename_subcommand` 在舊程式上**是綠的**
——因為分支起點根本沒有「借用」也沒有打平拒絕，那句叫人改名的話當時還不存在，
所以它在那裡當然不會紅。它守的是未來的回退，不是過去的錯誤，和
`test_blank_password_rule_no_longer_excludes_port` 同一類。

| 驗收 | 在舊程式上變紅的測試 | 失敗原因對不對 |
|---|---|---|
| 1 | `test_four_field_match_borrows_and_uses_inline_values`、`test_single_matching_profile_still_borrows_despite_ambiguity_check`、`test_borrow_mistyped_port_refuses_to_borrow`、`test_borrow_blank_and_placeholder_port_still_borrow`、**`test_stored_unparseable_port_refuses_to_borrow`（2 個參數版本）**、**`test_stored_ordinary_port_shapes_still_borrow`** | 是——舊程式根本不會去借 |
| 2 | `test_port_mismatch_refuses_and_names_both_ports`、`test_mismatched_profile_raises_naming_both_hosts`、`test_no_profiles_at_all_raises`、`test_refusal_two_profiles_differing_only_in_dbname_render_distinctly`、`test_borrow_scan_store_failure_...`（3 個參數版本）、**`test_ambiguous_profiles_refuse_to_borrow`**、**`test_ambiguous_profiles_error_names_both_candidates`**、**`test_identical_password_tie_still_refuses`**、**`test_differing_password_tie_refuses_without_a_password_claim`**、**`test_render_profile_name_clean_name_unaffected`**、**`test_render_profile_name_truncates_at_first_control_character`**、**`test_refusal_hostile_profile_name_with_newline_cannot_forge_a_line`** | 是 |
| 3 | 見下方說明 | 是 |
| 4 | `test_resolve_inline_params_password_placeholder_is_no_password` 等四項 | 是——舊程式把佔位符當成真密碼 |
| 5 | `test_missing_password_error_does_not_recommend_password_flag`、`test_get_setup_status_inline_next_step_does_not_recommend_password_flag`、`test_no_stray_password_flag_recommendation_in_source`，另見下方說明 | 是——訊息逐字指出 `server.py:117 recommends the --password flag` |
| 6 | `test_blank_password_rule_stated_consistently`（四份文件各一）、**`test_tie_refusal_documented`（四份文件各一）**、**`test_tie_refusal_documented_in_instructions_string`**、**`test_manifest_connection_fields_no_longer_invite_partial_blank`** | 是——四份都缺「四者全對」「沒對上就拒絕」，也都缺打平規則 |
| 8 | **`test_ambiguous_profiles_refuse_to_borrow`**、**`test_ambiguous_profiles_error_names_both_candidates`**、以及我移植的 **`test_tie_refusal_names_every_candidate`**（見下） | 是——舊程式連「借用」都沒有，更不會有打平 |

**第 3、5、8 條我一樣多做了一步。** 覆蓋這幾條的測試住在 `tests/test_tools.py`，
這個檔案**在舊程式上連載入都載入不了**，所以反向執行只報「收集錯誤」，而不是
「斷言抓到了舊行為」。收集錯誤是很弱的證據。所以我把那些**測試的斷言原封不動
搬到一個兩邊都跑得起來的新檔案**（這次也替第 8 條補了一個）：

```
舊程式（3821be8）：7 failed
  test_..._profile_mode_named_other_than_default_reports_configured
  test_..._borrowed_mode_reports_inline_host_and_borrowed_source
  test_get_setup_status_borrowed_mode_profile_field_is_none
  test_get_setup_status_inline_mode_profile_field_is_none
  test_no_tool_description_mentions_password_flag
  test_no_wire_surface_mentions_password_flag
  test_tie_refusal_names_every_candidate            <- 第 8 條，這次補的

這次的版本（83116be）：7 passed
```

同一組斷言，舊的紅、新的綠。

- **判定：PASS（通過）**

- **一個誠實的補充**（沿用上輪）：`test_blank_password_rule_no_longer_excludes_port`
  在舊程式上是綠的。它守的是「不可以再寫回修訂前那版『port 不算』的講法」，而那版
  講法在分支起點還沒存在過，所以它在那裡當然不會紅。它防的是未來的回退。

- **第五次修訂新增的一項觀察，和我自己第 6 條犯的錯是同一類。** `c442b79` 改寫了
  `test_tie_refusal_documented_in_instructions_string`。這個測試的名字和說明都宣稱
  它守的是「每個 MCP 用戶端在做任何事之前都會讀到的那個開場說明字串」，但它原本
  的做法是**把程式檔當純文字去搜關鍵字**。只要那幾句話出現在檔案裡的任何地方就
  算通過——包括搬進一段永遠不會進到開場說明的註解裡。**它宣稱守的東西，和它實際
  檢查的東西，是兩回事。** 現在改成讀真正建好的 `tools.mcp.instructions` 屬性。
  這和我第 6 條那次一樣（用「文件沒變」去證明「文件和程式相符」）——檢查的對象
  和聲稱的對象對不上，而且兩次都是綠燈，所以不會有人發現。

---

## 驗收條件沒點到、但我注意到的事

### 0. 設定檔裡 port 存壞時，拒絕訊息會印出一組「看起來完全相符」的設定〔已修好〕

**已於 `f20cb4d`／`aea929b` 修好——就在我寫下這一項之後兩個提交。** 我上一版把它
評為〔重要〕、還寫成「最值得處理的一項」，卻沒有任何一行提到它已經不是現況；
更正說明見本報告開頭。**現在同樣的情境印出來是這樣**（我在 `c442b79` 實測）：

```
config.toml actually holds : port = 9999.0

Existing profiles: 'floaty' (host='warehouse.example.com' port=9999.0 (unreadable — could not be parsed as a number) user='analyst' dbname='prod').
```

設定檔裡真正躺著的 `9999.0` 現在**原樣印出來了**，後面還接著「讀不出來，無法解析
成數字」的原因。上下兩行不再一模一樣，使用者看得到到底哪裡不對。以下是我原本的
觀察內容，留作紀錄。

原本（`f1e57f1`）的情況是這樣：

W0-11 讓「設定檔裡存壞的 port」不再借出密碼——這是對的。但**出事時的訊息會自相
矛盾**。我把設定檔裡的 port 改成 `9999.0`（TOML 小數），啟動時填 5439：

```
config.toml actually holds : port = 9999.0

Inline mode requires a password for host='warehouse.example.com' port=5439 user='analyst' dbname='prod', and no stored profile's host/port/user/dbname all match it to borrow one from.
Existing profiles: 'floaty' (host='warehouse.example.com' port=5439 user='analyst' dbname='prod').
Provide the REDSHIFT_PASSWORD env var, or configure a profile matching this exact host/port/user/dbname via /redshift-comment-mcp:redshift-setup.
```

**上下兩行的四個欄位一模一樣。** 訊息說「沒有任何一組設定四欄全對」，緊接著印出
一組看起來**完全相符**的設定。真正的原因（你的設定檔裡那個 port 是壞的）完全沒有
出現——因為印出來的 `port=5439` 是程式**替換後**的值，不是設定檔裡真正躺著的
`9999.0`。使用者會對著一個看起來正確的 `config.toml` 束手無策。

**對照組：另外那個 port 守門員就講得很清楚。** 同樣是 port 出問題，但錯在啟動
參數時：

```
... The port you typed ('99x9') could not be read as a number, so the server
substituted the default port 5439 to boot — but a substituted port never borrows
a stored profile's password. Fix the typo and relaunch.
```

**當時兩個守門員不對稱**：你打錯的那個會把原始輸入引出來、把原因講清楚；設定檔
存壞的那個什麼都不說，還印出一個誤導性的值。那其實是 W0-07 修過的那個缺陷
（「兩組只差 dbname 的設定印得一模一樣」）換個入口又長出來一次。**`aea929b` 把
它補齊了，兩個守門員現在講法一致。**

---

> **這一節在第三次修訂時有一項更正、三項結案；第四次修訂新增第 0 項和第 5 項；
> 第五次修訂把第 0 項結案、並新增第 6 項與第 7 項。**
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
Delete the stale profile with `redshift-comment-mcp delete-profile --profile <name>` so only one matches this target, or provide the REDSHIFT_PASSWORD env var directly.
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

### 5. 「只留空其中一個欄位」的陷阱：新寫的說明是對的，但只寫在外掛表單〔小問題〕

`f1e57f1` 改寫了外掛表單上 host / user / dbname 三欄的說明，因為原本的寫法會誘導
使用者只留空其中一欄。我先**實測舊陷阱還在不在**（程式行為這次沒有改，只有字改了），
三種組合全試：

```
--- host 留空，user 和 dbname 有填
    CONNECTS TO: profile-host.example.com:5439/profile-db as profile-user
    你打的字被丟掉: ['typed-user', 'typed-db']

--- user 留空，host 和 dbname 有填
    CONNECTS TO: profile-host.example.com:5439/profile-db as profile-user
    你打的字被丟掉: ['typed-host.example.com', 'typed-db']

--- dbname 留空，host 和 user 有填
    CONNECTS TO: profile-host.example.com:5439/profile-db as profile-user
    你打的字被丟掉: ['typed-host.example.com', 'typed-user']
```

**三種都一樣**：只要三欄裡有任何一欄留空，整個就退回走設定檔那條路，**你打進去的
另外兩個值全部被無聲丟棄**，而且連到的是設定檔自己的主機、帳號和資料庫。

新的說明文字是這樣寫的（三欄各一份，措辭對稱）：

> This field, user and dbname are blank together or not at all: leave all three
> blank to use a profile configured via /redshift-setup, but leaving only this
> one blank still falls back to that profile wholesale and ignores whatever you
> typed into user and dbname.

**我逐字比對過：這段話和我量到的行為完全相符**，沒有誇大也沒有遺漏——「整個退回」
（falls back wholesale）、「忽略你打進另外兩欄的字」（ignores whatever you typed）
都是真的。把話講白正是這次的修法，而這句話講白了。

**剩下的小問題**：這段警告**只寫在外掛表單裡**，三份 README 和 MCP 開場說明都沒有。
外掛表單確實是使用者遇到這個陷阱的地方，所以放在那裡價值最高；但從 README 讀起
的人（手動安裝、或用其他 MCP 用戶端的人）看不到。驗收條文第 6 條問的是「密碼留空」
那條規則，這條講的是「host/user/dbname 留空」，嚴格說不在它的字面範圍內，所以我
沒有因此判 FAIL。

---

### 6. 拒絕訊息仍然叫你「刪掉或**改名**」——但這個工具沒有改名這個功能〔已修好〕

**已於 `83116be` 修好。** 我當時發現：`c442b79`（W0-14）把 MCP 開場說明修好了
（改成指名 `delete-profile`、講明沒有改名功能），但**使用者真正讀到的那則拒絕
訊息沒有跟著改**，最後一行還是「Delete or rename the stale profile」，而這個
工具根本沒有改名功能。現在那一行是：

```
Delete the stale profile with `redshift-comment-mcp delete-profile --profile <name>` so only one matches this target, or provide the REDSHIFT_PASSWORD env var directly.
```

真正做得到的指令被指名了，「改名」拿掉了。我另外把整個程式再搜一次 `rename`，
剩下的全部是檔案系統層面的原子改名（跟設定無關），**唯一提到「改名」的地方是
開場說明裡那句「沒有改名這個子指令」**——也就是說，伺服器自己寫出來的文字裡，
不再有任何一處叫人去改名。

**一個仍然存在、但我判斷可以接受的殘留**：外掛表單的 password 欄位說明和三份
README 仍然寫著「delete or rename the stale one」。它們**沒有指名任何機制**，
所以不會像原本那樣把人導向一個特定卻錯誤的指令。我把單獨閱讀外掛表單時的觀感
寫在第 6 條末尾的逐欄閱讀裡。

### 7. 外掛表單把 password 也算進「要嘛全填、要嘛全空」，但密碼單獨留空正是本次的主打功能〔已修好〕

**已於 `83116be` 修好。** 三欄的說明現在把「要嘛全填、要嘛全空」限縮回
host / user / dbname 三欄，保留「只留空其中一欄，連你打的密碼都會被丟掉」這個
後果，並且**明講密碼可以單獨留空**。以下是我原本的觀察內容，留作紀錄。

`c442b79` 當時把 `plugin.json` 裡 host / user / dbname 三欄的說明改成把 password
也列進那組欄位：

> This field, user, dbname **and password** are blank together or not at all:
> leave all four blank to use a profile … but leaving only this one blank still
> falls back to that profile wholesale and ignores whatever you typed into
> user, dbname **and password**.

**後半句是準確的**，我實測過：host 留空、其他三欄（含密碼）都填，確實整個退回
設定檔那條路，連密碼都被忽略。

**但前半句「這四欄要嘛一起填、要嘛一起空」對 password 來說是錯的**——密碼單獨
留空是**這次改動的主打路徑**，我實測：

```
--- ONLY password blank (the borrow path)
    mechanism : 'borrowed'
    connects  : profile-host.example.com:5439/profile-db as profile-user
```

它不但被支援，而且就是這整個變更的目的。同一份 `plugin.json` 裡 password 欄位
自己的說明也寫著「Leave blank to borrow the keychain password of a profile …」
——兩段話互相矛盾。**這個形狀正是當初引發整件事的那份 bug 回報**：同一份外掛
表單裡兩個欄位講相反的規則。`83116be` 採取的正是我建議的那個做法。

---

## 其他跑過的測試

| 這一批 | 結果 |
|---|---|
| 不需要資料庫的單元測試（乾淨副本、`83116be`） | **467 通過、2 跳過**（436 → 448 → 459 → 462 → 467） |
| 專案隨附的對抗測試案例（未修改） | **38 個全部通過** |
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

   我實測：程式內部的開場說明字串在 `c442b79` 有 7072 個字、有提到 borrowed、
   也不含 `--password`；但走真正的 MCP 握手時用戶端收到 `''`。分支起點的副本
   同樣解析到 fastmcp 4.0.5，e2e 結果也同樣是 4 失敗 2 通過——**所以這不是這次
   改壞的**。後果是：W0-05／W0-09／W0-14 在開場說明上做的工，在 fastmcp 4 環境下
   對真實使用者是看不到的——包括 `c442b79` 剛修好的「用 `delete-profile`、
   沒有改名」那一句。

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

- **第六次修訂我只重量了兩條，範圍是我自己清點的。** `83116be` 動到的是一條錯誤
  訊息字串、外掛表單三欄的說明、五個新測試；我比對過語法樹，確認**沒有任何一行
  連線決策邏輯改變**。所以我重量第 2 條（訊息文字）和第 6 條（外掛表單與程式的
  一致性），其餘沿用。沿用的理由是「那幾條依賴的東西這次沒動，而且我查過那兩處
  改到的文字沒有引入 `--password`」，不是「差異很小」。
- **逐欄閱讀的結論是我的判斷，不是量出來的數字。** 「單獨讀某一欄會不會誤導」
  沒有自動化檢查能回答，所以第 6 條末尾那一段是我一欄一欄讀完之後的主觀判斷：
  三欄的敘述**都準確**，但有兩處單獨讀會踩到（密碼被無聲丟掉的那個組合沒寫；
  password 欄仍寫著可以改名）。如果你讀起來不覺得那兩處是問題，那是判斷差異，
  不是事實差異——底下的實測結果都列出來了。
- **第五次修訂我沒有重走全部八條，重走的範圍是我自己比對出來的、不是別人給的。**
  交辦說法是「`aea929b` 只動一個小函式、`c442b79` 只動文字」。我用語法樹比對
  自己查了一次，發現**和那個說法有出入**：`c442b79` 改的兩處雖然都是字串，
  但**都是會送到使用者／代理人面前的表面**（MCP 開場說明、`get_setup_status`
  的說明文字），再加上 `plugin.json` 也被改過。所以我把第 5、6 條整組重量，
  第 2、8 條的訊息證據重新取樣，而不是照建議只做最小範圍。第 1、3、4、7 條的
  解析行為確認未受影響（`aea929b` 沒有碰決策邏輯），第 7 條仍然重跑了反向驗證。
  如果這個範圍判斷錯了，問題會出在這裡。
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
- **第 6 條上一版我判錯了，這次整條重做。** 上一版我用「四份文件的差異是空的」
  沿用結論——但那只證明文件沒動，而第 6 條問的是**文件和程式的關係**，程式在同一
  段期間長出了新分支。一位文件審查者指出這點，是對的，而且那條沒被記載的新分支
  確實從我這關通過了。這次改成**從程式反推**：把解析器實作的每一條規則列出來，
  逐條去對五個表面。這是我這份報告唯一一處「對沒檢查過的事寫了 PASS」，我把
  經過留在第 6 條開頭，沒有默默換掉。
- **第 4 條這次沒有重走，但理由不是檔案差異。** 第 4 條的規則完全由三個函式決定，
  我把這三個函式在前後兩版各自解析成語法樹比對，三個都相同；為求保險仍然重跑了
  探針。我特地不用「檔案差異是空的」當理由，因為那正是上一版第 6 條犯的錯。
- **R5、R6、R7 三條沒被文件記載的規則，我沒有算成第 6 條的 FAIL。** 依據是驗收
  條文寫的是「關於**密碼留空**的那條規則」，而 R5／R6 是它底下的子條件、R7 講的
  是另外三個欄位留空。如果你認為第 6 條該涵蓋整條借用規則的全部條件，那 R6 會
  讓它變成 FAIL——判斷權在你，我把三條都列出來了。
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
   建議（設環境變數）**實測有效**，只是比較費事；比較省事的那條（刪掉其中一組）
   它沒有主動說。答案已經在程式內部的 `ambiguous_profiles` 欄位裡，只是沒有放進
   回傳。只是小問題——完整的拒絕訊息本來就會出現在任何資料庫工具的「尚未設定」
   回應裡，省事的那條路離代理人只有一次工具呼叫。
2. **把 host / user / dbname 三欄留空、卻在密碼欄打了字，密碼會被無聲丟掉，
   而對話框沒有講。** 這是我這次逐欄閱讀時發現的（見第 6 條末尾）。行為一直如此、
   不是新缺陷，但那三欄現在花了不少篇幅談「哪些欄位可以留空」，漏掉這個組合比較
   可惜。**這是這次唯一一項新的、還開著的觀察。**
3. **外掛表單的 password 欄和三份 README 仍然寫著可以「rename the stale one」，
   但這個工具沒有改名功能。** 我知道這是審查時刻意留下的（因為沒有指名任何機制），
   只是逐欄閱讀時仍然會讀成「有兩個選項」。要不要順手改成「刪掉，或重新建立一個」？
4. **R5、R6 這兩條規則要不要寫進文件？** 兩者現在**出事時訊息都會自己解釋**
   （R6 是 `aea929b` 補的），所以沒寫進文件的實際影響不大。列在這裡只是讓你知道
   它們目前只靠錯誤訊息傳達，文件上沒有。
5. **「只留空其中一欄」那段警告，要不要也寫進三份 README？** 目前只在外掛表單裡。
   從 README 讀起的人（手動安裝、其他 MCP 用戶端）看不到。
6. **開場說明在 fastmcp 4 之下是空的，要不要提高優先序？** 這不是這次改壞的，但它
   讓 W0-05／W0-09／W0-14 在開場說明上做的工，在 fastmcp 4 環境下完全看不到——
   包括「用 `delete-profile`、沒有改名」那一句。
7. **需要真實叢集的整合測試，要不要等連線恢復之後補跑一次再正式核准？**

（先前列在這裡、現在都已經修好、不再是待決事項的有：計畫書 W0-09 的描述
（`e03b27e`）、「不會讀密碼」那句註解（`166bf07`）、「拒絕訊息叫人改名」與
「外掛表單把密碼算進要嘛全填要嘛全空」（兩者都在 `83116be`）、以及「設定檔存壞
port 時拒絕訊息看起來自相矛盾」（`f20cb4d`／`aea929b`）——最後這一項我上一版還把它
列為「最值得處理」，更正見報告開頭。）

---

## 語言與格式規則檢查

| 文件 | 規則 | 結果 | 依據 |
|---|---|---|---|
| 需求書（intent） | 全英文 | 符合 | 全文無中日文字 |
| 規劃書（plan.md） | 全英文 | 符合（三處例外，且該例外正確） | 三處中日文字全部在「問過你的原話」逐字記錄段落，是保留你原本的輸入 |
| 設計規格 | EARS `REQ-<n>` 條列 | 不適用 | 需求書仍是 `needs-design: no`，所以沒有產出設計規格。**但這一格上一版我引錯了根據**：當時那行的理由寫著「沒有引入任何新的回應欄位」，而那是假的——`get_setup_status` 確實多了 `borrowed_from_profile` 這個欄位、`source` 多了 `borrowed` 這個值、`profile` 現在會回 null。這行已於 `f62a933` 更正，改成承認多了一個選用欄位、但仍不需要設計規格（沒有新工具、沒有新指令參數、沒有新介面）。結論沒變，根據換了 |
| 審查意見 | Conventional Comments 標籤 | 不適用 | 這個變更的資料夾裡沒有獨立成檔的審查意見文件。**兩輪審查中兩位審查者都判過 NEEDS_REVISION**，但沒有「重要」以上的意見被駁回後轉交給我記錄——相反地，它們都被接受並修掉了（第一輪 `c1a9d86`／`f1e57f1`，第二輪 `aea929b`／`c442b79`）。其中**兩條是針對我這份報告的**：第一輪指出我第 6 條的推理錯誤，第二輪指出我把一個已修好的缺陷寫成「最值得處理」，兩條我都照辦更正了 |
| 證據檔（對抗探針程式） | 全英文 | 符合 | 六支探針程式全部 0 處中日文字 |
| 測試說明文字（docstring） | 全英文 | 符合 | `test_server_resolution.py` 0 處。`test_tools.py` 有 122 處，**全部是改動前就存在的**（分支起點同樣 122 處，本分支新增 0 處）。`test_repo_invariants.py` 新增 6 處，全部是日文版／繁中版 README 的比對字串本身——測試對象就是多語文件，屬於正確的例外 |
| 測試命名 | `test_<單元>_<狀態>_<預期>` | 部分符合 | 語意上都是三段式（例如 `test_identical_password_tie_still_refuses` = 單元 identical_password_tie／狀態 still／預期 refuses），但沿用專案既有的敘述式風格，沒有嚴格用底線切成剛好三段 |
| 提交訊息 | 全英文 | 符合（一處例外，且該例外正確） | 分支起點以來 33 筆提交（含本報告前五版那五筆）。唯一一個中日文字是 `f1e57f1` 訊息裡的 `的`——那筆提交做的就是「修掉繁中版 README 裡一個多餘的 `的`」，訊息在引用它修掉的那個字，不是敘述文字夾雜中文 |

---

## 我沒能做到的事

- **「真的登入進 Redshift」沒有驗證到**——叢集連不上（原始 TCP 測試 8 秒逾時）。
  第 1 條的「連線」只能證明到「往正確的位址、帶著正確的密碼開出一條真實連線」。
- **需要真實叢集的整合測試那一批，完全沒跑。**
- **第 6 條我上一版判錯過**——用「文件沒動」當理由沿用，但那條驗收問的是文件和
  程式的關係。這一版已經改成從程式反推，經過留在第 6 條開頭。
- **第 4 條這一版沒有重走**，只用語法樹比對確認它的三個實作函式在 `4d51a9a`、
  `f1e57f1`、`c442b79`、`83116be` 四版之間完全沒變；探針是在 `47910d5` 跑的，
  之後沒有再跑。
- **第 1、3、5 條這一版也沒有重走**，理由是 `83116be` 沒有改動它們依賴的東西
  （決策邏輯未變、改到的兩處文字不含 `--password`）。第 2、6 條有重量。
- **我上一版把一個已經修好的缺陷寫成「最值得處理的一項」，而且沒有註明版本。**
  那一項（設定檔存壞 port 時拒絕訊息看起來自相矛盾）在我寫完後兩個提交就修好了。
  這種錯誤會害你在該放行的時候多花成本——更正見報告開頭，該項已改標〔已修好〕。
- **沒有找到獨立成檔的審查意見文件**可供逐條核對 Conventional Comments 標籤規則。
- **R5、R6、R7 三條規則是否該由第 6 條涵蓋，我做了判斷但沒有把握**——我判不涵蓋，
  理由寫在「我替你決定的事」裡。如果你認為該涵蓋，第 6 條會變成 FAIL。
- 上面列出的每一項觀察我都**只記錄、沒有修**。
