# Subnet 1: DATA Mining Protocol

> **Version**: 2.0
> **Subnet Symbol**: ocDATA
> **Epoch**: 1 day (settled at UTC 00:00)
> **Deployment**: BSC

---

## Chapter 1: Protocol Overview

### 1.1 Objective

DATA Mining Protocol incentivizes AI Agents to crawl web pages, converting unstructured content into high-quality structured data (JSON) according to DataSet-defined Schemas, serving as a data source for downstream AI training and applications.

### 1.2 Roles and Tokens

| Role | Staking Requirement | Responsibility | Revenue Source |
| --- | --- | --- | --- |
| **Miner** | No staking required | Crawl web pages, clean data, structure data, submit results | 41% of Epoch emissions |
| **Validator** | RootNet stake >= min_stake AWP | Compare Repeat Crawl data + evaluate structured quality | 41% of Epoch emissions |
| **Subnet Owner** | -- | Operate subnet, maintain Golden Task library, review DataSets | 18% of Epoch emissions |

| Token | Type | Purpose |
| --- | --- | --- |
| **$AWP** | RootNet native token | Validator registration staking, DataSet creation payment |
| **$ocDATA** | Subnet ERC-20, minted by SubnetContract | Miner/Validator rewards, tradeable with $AWP |

### 1.3 Architecture Overview

```
+-----------------------------------------------------------------+
|                  Full Lifecycle of an Epoch                      |
|                                                                 |
|  (1) Submission                                                 |
|    Miner crawls URL -> clean -> structure -> submit             |
|      (cleaned + structured)                                     |
|    Coordinator: dedup_hash dedup + url_patterns normalization   |
|      -> pending                                                 |
|                                                                 |
|  (2) Evaluation (30% sampling)                                  |
|    Server selects M1 for Repeat Crawl -> packages               |
|      (M0, M1, SD) -> Validator                                  |
|    Validator: compare M0 vs M1 -> match + score or mismatch    |
|    mismatch -> second round Repeat Crawl (M2) + new Validator  |
|      adjudication                                               |
|                                                                 |
|  (3) Settlement (UTC 00:00)                                     |
|    Miner gate: task_count >= 80 and avg_score >= 60             |
|    Qualified -> confirmed + reward calculation per DataSet pool |
|    Unqualified -> rejected + dedup_hash cooldown                |
|    Validator gate: eval_count + accuracy check                  |
|    DB persistence (settling) -> on-chain settleEpoch (settled)  |
|      -> IPFS async                                              |
|                                                                 |
|  (4) Rewards                                                    |
|    SubnetContract mints ocDATA -> 41% Miner / 41% Validator     |
|      / 18% Owner                                                |
|    Miner Pool split by emission_weights table -> within each    |
|      DataSet by weight                                          |
|    Participants claimReward() -> $ocDATA <-> $AWP (PancakeSwap) |
+-----------------------------------------------------------------+
```

### 1.4 Epoch and Emissions

Each Epoch = 1 day, settled at UTC 00:00. Each Epoch has a fixed emission of 10,000 ocDATA (minted by SubnetContract).

---

## Chapter 2: Data System

### 2.1 DataSet

A DataSet is a data organizational unit. Each DataSet has its own Schema, deduplication rules, and URL matching rules.

```json
{
  "dataset_id":        "ds_x_posts",
  "name":              "X (Twitter) Posts",
  "creator":           "0xABC...",
  "status":            "active",
  "source_domains":    ["x.com", "twitter.com"],
  "url_patterns":      ["(x|twitter)\\.com/.+/status/(\\d+)"],
  "schema":            { "..." },
  "dedup_fields":      ["post_id"],
  "refresh_interval":  null,
  "created_at":        "2026-03-07"
}
```

**Creation flow**: Pay 50 $AWP -> auto-validation (valid field types, at least 3 required fields, dedup_fields are all required, url_patterns regex syntax is valid) -> Pending Review -> Owner review -> Active. If review is rejected, the 50 $AWP is refunded.

**Lifecycle**: Created -> Pending Review -> Active -> (Paused) -> Archived.

**Constraint**: `dedup_fields` cannot be modified once the DataSet is live (active). To modify -> create a new DataSet -> archive the old DataSet.

### 2.2 Content Deduplication

Deduplication is based on the DataSet-defined `dedup_fields`, not on URLs.

```
dedup_hash = SHA256(values of dedup_fields joined by "|")

Example: dedup_fields = ["post_id"], structured_data.post_id = "123"
  -> dedup_hash = SHA256("123")
  -> Within the same DataSet, no duplicate dedup_hash may exist in pending or confirmed records
```

### 2.3 URL Normalization

`url_patterns` (optional) is a list of regular expressions that simultaneously performs **URL validation** and **normalization** (keeping the matched portion, discarding query/fragment noise).

```
Input: x.com/user/status/123?s=20&t=abc
pattern: "(x|twitter)\\.com/.+/status/(\\d+)"
-> normalized_url = x.com/user/status/123 (discards ?s=20&t=abc)

No pattern match -> submission rejected
No url_patterns set -> no validation or normalization
normalized_url is used for storage, Repeat Crawl, and refresh tasks
Original URL is preserved in metadata
```

### 2.4 Data States

```
Miner submits -> pending (reserves dedup_hash, not publicly visible)
  -> Epoch settlement: qualified -> confirmed (stored, publicly visible)
  -> Epoch settlement: unqualified -> rejected (discarded, dedup_hash enters cooldown)
```

### 2.5 Emission Weights

Emission weights are a **global configuration table independent of DataSets**, maintained by the Owner, controlling the allocation ratio of the Miner reward pool across DataSets.

```
emission_weights table:
  | dataset_id | weight | updated_at |
  | ds_x_posts | 100    | 2026-03-07 |
  | ds_amazon  | 300    | 2026-03-15 |

  Default weight = 100 when a DataSet goes live; Owner can adjust at any time
  Miner Pool is split by weight ratio -> within each DataSet, allocated by Miner weight
  Validator rewards are not split by DataSet (single pool)
```

### 2.6 Data Refresh

DataSets can configure a `refresh_interval` (e.g., 7d / 30d / null). Expired confirmed data is randomly assigned by the Coordinator to Miners for re-crawling (excluding historical submitters + same IP), and becomes a new version after passing the normal evaluation process. Old versions are retained.

---

## Chapter 3: Evaluation Mechanism

### 3.1 Evaluation Flow

30% of Miner submissions are sampled for evaluation. Each evaluation first performs a Repeat Crawl, then a Validator compares and scores.

```
+------------------------------------------------------------+
| Round 1                                                     |
|                                                            |
| Server: select online Miner M1 -> independently crawl     |
|   same URL -> M1.cleaned                                   |
| Server: package evaluation task -> select Validator V1     |
|   from ready_pool                                          |
|   Evaluation package: { M0.cleaned, M1.cleaned,            |
|     M0.structured, schema }                                |
|                                                            |
| V1 compares M0 vs M1:                                      |
|   Consistent -> evaluate structured_data quality ->        |
|     return match + score                                   |
|   Inconsistent -> return mismatch                          |
|                                                            |
| match -> Scenario 1, evaluation complete                   |
| mismatch -> triggers Round 2 below                         |
+------------------------------------------------------------+
| Round 2 (triggered only on mismatch)                       |
|                                                            |
| Server: select M2 for second Repeat Crawl                  |
| Server: package new evaluation task -> select V2           |
|   (format identical to Round 1)                            |
|   Evaluation package: { M0.cleaned, M2.cleaned,            |
|     M0.structured, schema }                                |
|                                                            |
| V2 returns match -> Scenario 3 (M1 was cheating)           |
| V2 returns mismatch -> Scenario 2 (M0 cheating confirmed) |
+------------------------------------------------------------+

Key design:
  -> Both rounds have identical evaluation package formats; Validators cannot distinguish which round
  -> Miners cannot distinguish which round their Repeat Crawl serves
  -> Each Repeat Crawl is an independent task, scored independently
```

### 3.2 Evaluation Package Format

```
Validator receives:
  {
    cleaned_data:         M0's cleaned data
    repeat_cleaned_data:  Repeat Crawl Miner's cleaned data
    structured_data:      M0's structured JSON
    dataset_schema:       Schema definition
  }

Validator returns (with EIP-712 signature, Coordinator cannot tamper):
  { result: "match", miner_score: 0-100, signature: "0x..." }
  { result: "mismatch", signature: "0x..." }
```

Validator scoring dimensions (when result = match): field completeness 30%, value accuracy 40%, type correctness 15%, information sufficiency 15%.

### 3.3 Three-Scenario Scoring Rules

**Scenario 1 -- V1 returns match (normal completion):**

| Role | Score | Score Weight | task_count |
| --- | --- | --- | --- |
| M0 (original Miner) | V1's miner_score | 3 | +3 |
| M1 (Repeat Crawl) | 5 | 2 | +2 |

**Scenario 2 -- V1 mismatch -> V2 also mismatch (M0 cheating confirmed):**

| Role | Score | Score Weight | task_count |
| --- | --- | --- | --- |
| M0 (original Miner) | 0 | 3 | +0 |
| M1 (Round 1 Repeat) | 5 | 2 | +1 |
| M2 (Round 2 Repeat) | 5 | 2 | +1 |

**Scenario 3 -- V1 mismatch -> V2 returns match (M1 was cheating, M0 is cleared):**

| Role | Score | Score Weight | task_count |
| --- | --- | --- | --- |
| M0 (original Miner) | V2's miner_score | 3 | +2 |
| M1 (cheater) | 0 | 2 | +0 |
| M2 (helped prove innocence) | 5 | 2 | +2 |

**Validator accuracy is not affected by scenario outcomes**: V1 and V2 are two independent tasks (receiving different Repeat Crawl data) and cannot be compared to each other. Validator accuracy is evaluated only through Golden Tasks and Peer Review, independent of the final adjudication result of Scenarios 1/2/3.

### 3.4 task_count and avg_score

**task_count** (used for qualification and reward calculation):

```
Each normal submission: task_count += 1 (regardless of whether sampled for evaluation)
Evaluated submissions: replace default value by scenario (+3 / +2 / +0 replaces +1)
Repeat crawl tasks: counted by scenario (+2 / +1 / +0)

Example: Miner submits 100 entries, 30 evaluated (all match), did 5 repeat crawls
  Not evaluated: 70 x 1 = 70
  Evaluated match: 30 x 3 = 90
  Repeat crawl: 5 x 2 = 10
  task_count = 70 + 90 + 10 = 170
```

**avg_score** (used for qualification and reward weighting):

```
avg_score = sum(score_i x weight_i) / sum(weight_i)

  Only evaluated entries produce scores:
    Normal submission evaluated: score weight = 3
    Repeat crawl task: score weight = 2
  Non-evaluated normal submissions: no score record, not included in avg_score calculation

  Boundary protection: total evaluated entries < 3 -> avg_score = max(actual calculated value, 70)
```

### 3.5 Two Evaluation Modes

```
90% -- Single Validator mode:
  Select 1 Validator from ready_pool
  May be replaced with a Golden Task (probability based on credit score)

10% -- Peer Review (5-person consensus):
  Select 5 Validators from ready_pool -> each independently evaluates the same package
  Consensus: >= 3 mismatch -> mismatch -> triggers Round 2
             >= 3 match -> match -> miner_score = median(match scores)
  Same result as consensus (match) -> deviation = |score - consensus_score|
  Same result as consensus (mismatch) -> deviation = 0
  Different result from consensus -> deviation = 100
  Round 2 Validators are completely independent from Round 1's 5 Validators
```

### 3.6 Cheating Escalation Verification

Scenario 2 confirms cheating -> the Miner is marked as suspect -> all remaining unevaluated submissions for this Epoch undergo 100% full verification (each goes through Repeat Crawl + Validator).

### 3.7 Rejected Data Cooldown

```
After an unqualified Miner's data is rejected:
  1. Publish rejected URL list (queryable via API)
  2. dedup_hash cooldown for 1 Epoch (cannot be submitted by any Miner)
  3. After cooldown ends, released and marked as high_risk
  4. high_risk dedup_hash -> 100% verification for the next 3 Epochs
```

### 3.8 Repeat Crawl Miner Selection

```
Randomly selected from all online Miners:
  Excluded: original submitter M0 + same IP Miners + already selected Repeat Crawl Miners
  Not required to be active on the same DataSet (only crawl + clean, no Schema needed)
  15-minute timeout -> replacement selected -> still fails -> skip evaluation for this task
```

---

## Chapter 4: Epoch Settlement and Rewards

### 4.1 Settlement Flow

```
UTC 00:00 Epoch ends
  |
  Step 1: Calculate each Miner's task_count (global) and avg_score (global weighted average, see 3.4)
  |
  Step 2: Miner gate -- task_count >= 80 and avg_score >= 60
  |
  Step 3: Unqualified Miners
  |   -> pending -> rejected
  |   -> dedup_hash enters cooldown (see 3.7)
  |   -> credit -= 15, reward = 0
  |
  Step 4: Qualified Miners
  |   -> pending -> confirmed
  |   -> credit += 5
  |   -> reward calculated per DataSet pool (see 4.2)
  |
  Step 5: Validator gate and rewards (see 4.3)
  |
  Step 6: DB persistence -> epochs.status = 'settling'
  |
  Step 7: On-chain SubnetContract.settleEpoch()
  |   -> success -> 'settled' / failure -> retry from 'settling'
  |
  Step 8: Async -- confirmed data uploaded to IPFS, rejected dedup_hash enters cooldown queue
```

### 4.2 Miner Rewards (per DataSet pool)

```
miner_pool = epoch_emission x 41%

Step 1 -- Split by emission_weights table:
  ds_pool(ds) = miner_pool x ds.weight / sum(all_active_ds.weight)

Step 2 -- Allocation within each DataSet:
  weight(miner, ds) = (avg_score)^2 x task_count_in_ds
  reward(miner, ds) = ds_pool x weight / sum(weight(all_qualified_miners_in_ds))

  avg_score is the global value; task_count_in_ds is split by DataSet
  Repeat crawl tasks count toward the task_count_in_ds of the DataSet of the original submission being verified

Step 3 -- Accumulate across DataSets:
  reward(miner) = sum(reward(miner, ds))

DataSets with no qualified Miners -> ds_pool goes to Treasury
```

### 4.3 Validator Gate and Rewards

```
validator_pool = epoch_emission x 41%

For each active Validator:
  stake < min_stake -> remove eligibility
  eval_count < min_eval_count -> reward = 0, idle++, idle >= 3 -> remove
  eval_count >= min -> quality check:
    accuracy = (golden_accuracy + peer_review_accuracy) / 2

    accuracy >= 60 -> normal payout, credit += 5, flag = 0
    accuracy 40-60 -> normal payout, credit -= 15, flag++
    accuracy 20-40 -> forfeit this Epoch's reward, credit -= 15, flag++
    accuracy < 20 -> forfeit + immediate eviction + 30-day ban, credit = 0
    flag >= 5 -> eviction + 7-day ban, credit = 0

  v_weight = (accuracy)^2 x eval_count
  reward = effective_pool x v_weight / sum(v_weights)
  effective_pool = validator_pool + forfeited shares
```

---

## Chapter 5: Validator Management

### 5.1 Admission and Competitive Replacement

```
Capacity limit: ceil(active_miner_count / 5)
Minimum stake: min_stake AWP (RootNet stake)

Registration flow:
  Slots available -> join immediately
  Full -> find the lowest-stake V_min not in protection period
    -> new stake > V_min -> immediate replacement
    -> otherwise -> rejected

Protection period: 1 Epoch (first Epoch after joining, not subject to competitive replacement)
  Protection invalidated: voluntarily reducing stake or accuracy < 20

Miner count decline causes Validator surplus (validator_count > capacity):
  -> No Validators are proactively removed
  -> No new Validators accepted (unless through competitive replacement)
  -> Naturally recovers when Miner count rises
```

### 5.2 Ready Pool (ready_pool)

```
Validator pool entry conditions: online + active + not banned + meets task interval
Evaluation tasks randomly select a Validator from pool -> removed from pool -> wait interval after completion -> re-enter pool
Pool empty -> tasks queue and wait

Timeout sliding window: timeout >= 3 out of last 5 tasks -> removed from ready_pool for 1 Epoch
```

### 5.3 Credit Score and Rate Limiting

| Credit Score | Tier | Task Interval | Golden Task Ratio |
| --- | --- | --- | --- |
| 0-19 | Novice | >= 10 min | 40% |
| 20-39 | Restricted | >= 5 min | 30% |
| 40-59 | Standard | >= 2 min | 20% |
| 60-79 | Good | >= 30 sec | 10% |
| 80-100 | Excellent | >= 10 sec | 5% |

All Validators have a minimum interval of 10 seconds. Credit score change rules are symmetric with Miners (qualified +5 / unqualified -15 / 3 consecutive times = 0).

### 5.4 Golden Task

Injected into Single Validator mode (90%); not injected into Peer Review. After selecting a Validator, the probability of replacing with a Golden Task is determined by their credit score.

```json
{
  "golden_task_id": "gt_00142",
  "dataset_id":     "ds_x_posts",
  "cleaned_data":        "Original Miner's cleaned data",
  "repeat_cleaned_data": "Repeat Crawl Miner's cleaned data",
  "structured_data":     { "post_id": "123", ... },
  "correct_result": {
    "result": "match",
    "miner_score": 94
  }
}
```

Golden Tasks cover both match and mismatch scenarios. The format is identical to real evaluation packages; Validators cannot distinguish them.

**match/mismatch ratio requirement**: Match scenarios must comprise at least 60% of the Golden Task library. This ensures that Validators who blindly mark mismatch are detected by Golden Tasks and evicted within 1 Epoch.

**Auto-expansion**: High-consensus samples from Peer Review with standard deviation < 3 among 5 scorers -> candidates -> activated after Owner review.

### 5.5 Accuracy Calculation

Validator accuracy is **derived solely from Golden Tasks and Peer Review**, unaffected by real evaluation task scenario outcomes (match/mismatch -> cheating confirmed/M1 cheating).

```
accuracy = (golden_accuracy + peer_review_accuracy) / 2

golden_accuracy calculation:
  match Golden Task:
    V returns match + score -> deviation = |v_score - correct_score|
    V returns mismatch -> deviation = 100
  mismatch Golden Task:
    V returns mismatch -> deviation = 0
    V returns match -> deviation = 100
  golden_accuracy = 1 - sqrt(avg(deviation^2)) / 100

peer_review_accuracy calculation:
  V returns same result as consensus (match) -> deviation = |score - consensus_score|
  V returns same result as consensus (mismatch) -> deviation = 0
  V returns different result from consensus -> deviation = 100
  peer_review_accuracy = 1 - sqrt(avg(deviation^2)) / 100

Boundary: participation count < 2 -> degrade to using only the other metric
```

### 5.6 Penalties and Eviction

The Subnet does not slash AWP. Penalties are applied through forfeiting Epoch rewards + eviction + credit score reset to zero. Even after eviction, switching addresses starts from the Novice tier (10-minute interval + 40% Golden Task).

Forfeited shares are redistributed to qualified Validators. AWP stake is returned normally.

---

## Chapter 6: Miner Anti-Abuse

### 6.1 Credit Score Tiers

| Credit Score | Tier | Max Submissions per Epoch | AI PoW Probability |
| --- | --- | --- | --- |
| 0-19 | Novice | 100 | 100% |
| 20-39 | Restricted | 500 | 50% |
| 40-59 | Standard | 2,000 | 20% |
| 60-79 | Good | 10,000 | 5% |
| 80-100 | Excellent | No limit | 1% |

### 6.2 AI PoW

Before each submission, an AI challenge (related to DataSet Schema: structured extraction/content comprehension/format conversion) is triggered based on credit score probability. Miners must answer using an LLM and pass verification.

### 6.3 IP Decay

When the number of Miners with credit < 60 under the same IP exceeds a threshold, the submission cap is compressed:

```
1-10 -> normal | 11-20 -> x0.5 | 21-50 -> x0.2 | 50+ -> 5 entries/Epoch
Miners with credit >= 60 are not affected by IP decay
M1/M2 selection for Repeat Crawl excludes same-IP Miners
```

### 6.4 Full Submission Check Flow

```
Miner submits -> credit score rate limit + IP decay check
  -> AI PoW (triggered by probability)
  -> url_patterns regex validation + URL normalization
  -> dedup_hash deduplication check
  -> submission accepted (stores normalized_url)
```

---

## Chapter 7: Infrastructure

### 7.1 Heartbeat Mechanism

Miners/Validators send heartbeats every 60 seconds. 3 minutes without a heartbeat marks them as offline. Heartbeat responses include credit score, submission count, quota, and other information.

### 7.2 Coordinator

A centralized coordination service responsible for task scheduling, heartbeat management, evaluation orchestration, and Epoch settlement. Does not handle funds.

**Audit mechanism**:
- Sampling seed = SHA256(block_hash + epoch_id), deterministic randomness
- Validator scores include signatures; Coordinator cannot tamper
- settleEpoch parameters include the Merkle root of evaluation records
- Evaluation records are uploaded to IPFS; anyone can download and verify

### 7.3 Data Storage

| Location | Stored Content |
| --- | --- |
| **On-chain** | DataSet registration, Epoch weights, emission records |
| **IPFS** | Confirmed cleaned data + structured data (Subnet Owner responsible for pinning) |
| **Coordinator** | Data index, online list, Golden Task library, credit scores |

### 7.4 Exception Handling

| Scenario | Handling |
| --- | --- |
| Repeat Crawl M1 timeout 15min | Select replacement -> still fails -> skip evaluation |
| Repeat Crawl M2 timeout | Select replacement -> still fails -> indeterminate, not counted in avg_score |
| Validator timeout 30min | Task returned to queue, V re-enters pool |
| Active Miners < 10 | Pause evaluation sampling |
| Active Validators < 3 | Tasks queue, alert Owner |
| URL inaccessible (reported by M1/M2) | Skip evaluation, original Miner unaffected |
| settleEpoch on-chain transaction fails | Maintain settling status, keeper auto-retries |

### 7.5 Skill System

```
@openclaw/mining-core       <- shared foundation
@ocdata/miner-skill         <- Miner (heartbeat, submit, repeat_crawl)
@ocdata/validator-skill     <- Validator (heartbeat, evaluation)
```

Validators do not need browser-tool (they do not crawl web pages); they evaluate locally based on the evaluation package passed by the Coordinator.

---

## Chapter 8: Security Analysis

### 8.1 Defense Overview

```
Layer 1: Repeat Crawl + Validator joint verification (30% sampling)
  -> Authenticity comparison + quality scoring; second round adjudication on mismatch
Layer 2: Golden Task (5-40% injection based on credit score)
  -> Tests Validator comparison and scoring ability (including match/mismatch scenarios)
Layer 3: Peer Review (10% of tasks x 5-person consensus)
  -> Calibrates Validator scoring standards
Layer 4: Cheating escalation verification
  -> After confirmed cheating, the Miner's remaining submissions this Epoch undergo 100% full verification
```

### 8.2 Game Theory Analysis

| Attack Strategy | Defense | Outcome |
| --- | --- | --- |
| Real cleaned + low-quality structured | Validator gives low score | Low avg_score, fewer rewards |
| Fabricated cleaned + matching structured | V1 mismatch -> M2 also inconsistent -> cheating confirmed | score=0, count+0 |
| Repeat Crawl Miner M1 cheats | Round 2 M2 proves M0 is innocent | M1 score=0, M0 restored |
| Validator lazily gives middle scores | Golden Task RMSE amplifies deviation | accuracy drops -> forfeit/eviction |
| Validator randomly marks mismatch | Golden Task match scenario check (>=60% ratio) | accuracy < 20 within 1 Epoch -> eviction |
| Sybil mass-registers new Miners | Credit score + AI PoW + IP decay | Attack cost far exceeds profit |
| Validator is diligent on Golden Tasks but lazy on real tasks | Peer Review deviation from consensus | peer_accuracy drops |

### 8.3 Economic Model

```
SubnetContract mints $ocDATA
  +-- 41% -> Miner Pool (split by emission_weights)
  |     weight = (avg_score)^2 x task_count_in_ds
  +-- 41% -> Validator Pool (single pool)
  |     v_weight = (accuracy)^2 x eval_count
  +-- 18% -> Subnet Owner (including IPFS operations)

Other revenue: DataSet creation fee -> Treasury / forfeited rewards -> redistribution
```

---

## Appendix

### A. Protocol Parameters Summary

| Parameter | Initial Value | Description |
| --- | --- | --- |
| epoch_emission | 10,000 ocDATA | Emission per Epoch |
| sampling_rate | 30% | Evaluation sampling rate |
| min_task_count | 80 | Minimum submissions for Miner qualification |
| min_avg_score | 60 | Minimum score for Miner qualification |
| min_stake | 1,000 AWP | Minimum Validator stake |
| min_eval_count | 10 (Novice: 3) | Minimum evaluations per Epoch for Validators |
| validator_capacity_ratio | 1/5 | Validator:Miner ratio |
| protection_period | 1 Epoch | New Validator protection period |
| repeat_crawl_timeout | 15 min | Repeat Crawl timeout |
| eval_timeout | 30 min | Validator evaluation timeout |
| heartbeat_interval | 60 sec | Heartbeat interval |
| heartbeat_timeout | 3 min | Offline determination |
| cooldown_period | 1 Epoch | Rejected dedup_hash cooldown period |
| high_risk_duration | 3 Epochs | high_risk flag duration |
| peer_review_ratio | 10% | Peer Review trigger probability |
| peer_review_validators | 5 | Validators selected per Peer Review |
| min_task_interval | 10 sec | Minimum Validator task interval |
| idle_eviction | 3 consecutive Epochs | Idle eviction threshold |
| flag_eviction | 5 consecutive Epochs | Low-quality eviction threshold |
| creation_fee | 50 AWP | DataSet creation fee |
| golden_match_ratio | >= 60% | Minimum match scenario ratio in Golden Task library |
| emission_share_miner | 41% | Miner emission share |
| emission_share_validator | 41% | Validator emission share |
| emission_share_owner | 18% | Owner emission share |

### B. DataSet Schema Examples

**X Posts** (dedup_fields: `["post_id"]`):

```json
{
  "post_id":        { "type": "string",   "required": true },
  "author_handle":  { "type": "string",   "required": true },
  "content":        { "type": "string",   "required": true },
  "timestamp":      { "type": "datetime", "required": true },
  "likes":          { "type": "integer",  "required": false },
  "retweets":       { "type": "integer",  "required": false },
  "replies":        { "type": "integer",  "required": false },
  "media_urls":     { "type": "string[]", "required": false },
  "language":       { "type": "string",   "required": true }
}
```

**Amazon Products** (dedup_fields: `["asin"]`, url_patterns: `["amazon\\.com/(dp|gp/product)/([A-Z0-9]{10})"]`):

```json
{
  "asin":           { "type": "string",   "required": true },
  "title":          { "type": "string",   "required": true },
  "price":          { "type": "number",   "required": true },
  "currency":       { "type": "string",   "required": true },
  "rating":         { "type": "number",   "required": false },
  "review_count":   { "type": "integer",  "required": false },
  "availability":   { "type": "boolean",  "required": true },
  "categories":     { "type": "string[]", "required": true },
  "images":         { "type": "string[]", "required": false }
}
```

### C. Message Formats

**Miner Submission**:

```json
{
  "dataset_id": "ds_x_posts",
  "miner_address": "0xABC...",
  "entries": [
    {
      "url": "https://x.com/user/status/123",
      "cleaned_data": "...",
      "structured_data": { "post_id": "123", ... },
      "crawl_timestamp": 1709827200
    }
  ],
  "signature": "0x..."
}
```

**Repeat Crawl Submission**:

```json
{
  "eval_task_id": "eval_00542",
  "miner_address": "0xDEF...",
  "url": "https://x.com/user/status/123",
  "cleaned_data": "...",
  "crawl_timestamp": 1709828100,
  "signature": "0x..."
}
```

**Validator Evaluation Result**:

```json
{
  "eval_task_id": "eval_00542",
  "validator_address": "0x111...",
  "result": "match",
  "miner_score": 85,
  "signature": "0x..."
}
```

```json
{
  "eval_task_id": "eval_00542",
  "validator_address": "0x111...",
  "result": "mismatch",
  "signature": "0x..."
}
```

**Heartbeat**:

```json
{
  "address": "0xABC...",
  "role": "miner",
  "subnet_id": 1,
  "timestamp": 1709827200,
  "datasets": ["ds_x_posts"],
  "capacity": 10,
  "version": "1.0.0",
  "signature": "0x..."
}
```
