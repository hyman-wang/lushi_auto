# 推荐链路：盒子 CEF JSON（无 OCR）

> 2026-10 实测替换：推荐不再截图 + OCR，而是直接读盒子 CEF 页面推送的 JSON。
> 本文记录链路、数据结构、代码位置和排障方法。

## 1. 为什么换

旧链路：截「打法参考A」面板 → RapidOCR → 正则解析中文 → `ProposedAction`。
问题：识别失败会卡住整回合；卡名/目标靠猜；面板字号/皮肤/分辨率都会影响。

新链路：盒子本来就是把推荐算好后以 JSON 推给面板页面的，直接读那份 JSON：

```
HSAng.exe（原生/服务器算推荐）
   │  window.onUpdateLadderActionRecommend("<json>")
   ▼
CEF 页面 https://hs-web-embed.lushi.163.com/client-jipaiqi/ladder-opp
   ▲
   │  DevTools (CDP)  hook + 轮询 window.__boxRec
   │
HSArriver-Turbo  src/recommendation/cdp_source.py → mapper.py → 适配/点击
```

## 2. 前置条件

1. 盒子必须带调试端口启动（HSAng 的 manifest 要求管理员）：

   ```powershell
   Start-Process 'D:\炉石传说盒子\HSAng.exe' -ArgumentList '--remote-debugging-port=9222' -Verb RunAs
   ```

2. 验证端口：

   ```powershell
   curl http://127.0.0.1:9222/json/list
   ```

   空闲时能看到 `client-home` / `JiPai_wel`；**进对局后**才会出现
   `client-jipaiqi/ladder-opp`（真正出推荐的那一页）。

## 3. 数据长什么样

一次对局里实测（已脱敏）：

```json
{
  "status": 2,
  "error": "",
  "turnNum": 4,
  "optionId": 19,
  "choiceId": -1,
  "data": [
    {
      "actionName": "minion_attack",
      "card": {"ZONE_POSITION": 1, "cardId": "CATA_490", "cardName": "魔眼秘术师"},
      "oppTargetHero": {"cardId": "HERO_09a", "cardName": "泰兰德·语风", "health": 30},
      "using_disguised": 0
    }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `status` | 实测对局中恒为 2 |
| `turnNum` | 盒子自己的回合数（可直接和 Power.log 对齐） |
| `optionId` / `choiceId` | 本回合动作序号 / 抉择序号（普通动作 `-1`） |
| `data[0]` / `data[1]` | 打法参考A / 打法参考B |
| `actionName` | 动作枚举（见下表） |
| `card` | 对象或数组：`cardId` / `cardName` / `ZONE_POSITION`（手牌或场面号位） |
| `position` | 落位（`play_minion` 的「放置于我方 N 号位」） |
| `target` / `oppTarget` | 己方 / 对方目标（号位字段可能是 `position` 或 `ZONE_POSITION`） |
| `targetHero` / `oppTargetHero` | 目标是英雄时是**对象**（含 `cardId`/`health`） |
| `subOption` | 抉择/发现的子选项 |

### actionName 对照

| actionName | 面板文字 | 内部 ActionKind |
|---|---|---|
| `end_turn` | 结束回合 | `END_TURN` |
| `play_minion` | 打出N号位随从 | `PLAY_CARD`(MINION) |
| `play_special` | 打出N号位法术 | `PLAY_CARD`(SPELL) |
| `play_weapon` | 打出N号位武器 | `PLAY_CARD`(WEAPON) |
| `play_hero` | 打出N号位英雄 | `PLAY_CARD`(HERO) |
| `play_location` | 打出N号位地标 | `PLAY_CARD`(LOCATION) |
| `forge` / `trade` / `prepare` | 锻造/交易/预备N号位卡牌 | `TRADE_CARD` |
| `minion_attack` | 操作N号位随从攻击 | `ATTACK`(board_slot) |
| `hero_attack` | 操作我方英雄攻击 | `ATTACK`(hero) |
| `hero_skill` | 使用英雄技能 | `USE_HERO_POWER` |
| `location_power` | 操作N号位地标 | `USE_LOCATION` |
| `launch_starship` | 发射N号位星舰 | `LAUNCH_STARSHIP` |
| `choice` | 选择我方N号位卡牌 | `CHOOSE_DISCOVER` |
| `replace` | 替换N号位卡牌 / 保留全部卡牌 | `MULLIGAN` |
| `timeline_undo` / `timeline_keep` | 回溯 / 维持 | `TIMELINE_UNDO` / `TIMELINE_KEEP` |
| `titan_power` / `common_action` / `discard` / `choose` | — | 暂不支持（跳过，等盒子推下一条） |

## 4. 代码位置

| 文件 | 作用 |
|---|---|
| `src/recommendation/cdp_source.py` | 找 `ladder-opp` 页面、挂 hook、轮询 `window.__boxRec`；断线重连 |
| `src/recommendation/mapper.py` | JSON → `ProposedAction`（号位/目标/落位/文案） |
| `src/flow/recommendation_flow.py` | 用推送版本号判断「新推荐/没变」，替代原来的截图哈希 |
| `src/safety/recommendation_validator.py` | 去掉帧/DPI/OCR 校验，保留回合、日志版本、去重 |
| `FSM_action.py` | 初始化 source；换牌建议也走 `payload_to_action` |

OCR 仍保留给**非推荐**的三处读取（这些不是推荐数据，别删）：

- 结算界面段位数字（上分停止/控分）
- 左上角「AI胜率 X%」（自动投降）
- 换牌「确认」按钮是否还在（防盲点）

## 5. 排障

| 现象 | 处理 |
|---|---|
| 启动后一直 `recommendation_source_unavailable` | 盒子没带 9222，或已退出；`curl http://127.0.0.1:9222/json/list` 确认 |
| 列表里没有 `client-jipaiqi` | 还没进对局；面板是进对局才创建的 |
| 面板显示「AI推荐功能实行阶梯开放…」 | 推荐被名次/日期门槛挡了，`data` 为空是正常的 |
| 推荐到了但动作被跳过 | 看日志 `[推荐] 跳过不支持的动作：<code>`，补 mapper 的 actionName |
| 点了但不确认 | 看 `result_not_confirmed`；盒子推下一条的延迟超过 `result_timeout_seconds`（默认 3s） |
