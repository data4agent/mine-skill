# LinkedIn Profile 字段来源分析

**Last Updated**: 2026-04-03

## Bug Fixes Applied

### About字段页脚内容Bug ✅ FIXED (2026-04-03)
- **问题**: about字段提取到LinkedIn页脚内容而非用户简介
- **原因**: HTML fallback提取时_section_text_by_heading返回页脚
- **修复**: 添加_is_linkedin_footer_content()验证函数
- **文件**: crawler/platforms/linkedin.py

## 1. API可直接提取的字段 (15个)
从 voyager API 响应中直接获取：

| 字段 | API路径 | 状态 |
|------|---------|------|
| name | firstName + lastName | ✅ |
| headline | headline | ✅ |
| linkedin_num_id | entityUrn | ✅ |
| public_identifier | publicIdentifier | ✅ |
| city | geoLocation.geo.defaultLocalizedName | ✅ |
| country_code | geoLocation.countryISOCode | ✅ |
| is_premium | premium | ✅ |
| is_influencer | influencer | ✅ |
| is_creator | creator | ✅ |
| content_creator_tier | topVoiceBadge.badgeText | ✅ |
| profile_url | 构造 | ✅ |
| avatar | profilePicture | ✅ |
| timestamp | created | ✅ |
| personal_website | creatorInfo.creatorWebsite | ✅ |
| featured_content_themes | 已提取 | ✅ |

## 2. 需要HTML提取的字段 (10个)
API不返回，必须从页面HTML提取：

| 字段 | 页面位置 | 当前状态 | 浏览器验证(2026-04-03) |
|------|----------|----------|------------------------|
| followers | "40,147,671 位关注者" | ✅ 已正确提取 | 确认存在 |
| about | 个人简介section | ✅ 修复后可提取 | "Chair of the Gates Foundation..." |
| banner_image | 封面照片URL | ✅ 已提取 | 确认存在 |
| connections | 好友数(名人不显示) | ❌ 页面不显示 | Bill Gates页面无此字段 |
| people_also_viewed | 推荐档案carousel | ⚠️ 部分提取 | 确认存在"更多职业档案推荐" |
| recent_posts | 动态section | ❌ 需添加提取 | 确认存在"精选"动态 |
| experience | 经验section | ❌ 留空 | Bill Gates页面无此section |
| education | 教育section | ❌ 留空 | Bill Gates页面无此section |
| skills | 技能section | ❌ 留空 | Bill Gates页面无此section |
| certifications | 证书section | ❌ 留空 | Bill Gates页面无此section |

### 浏览器检查结果 (Bill Gates页面)
**实际页面about内容**:
> Chair of the Gates Foundation. Founder of Breakthrough Energy. Co-founder of Microsoft. Voracious reader. Avid traveler. Active blogger.

## 3. 需要LLM Enrich的字段 (59个)
无法从原始数据提取，需要AI分析生成：

### 身份分析
- name_gender_inference
- name_ethnicity_estimation
- profile_language_detected

### About分析
- about_summary
- about_sentiment
- about_topics
- about_readability_score

### 职业分析
- standardized_job_title
- seniority_level
- job_function_category
- current_company (需推断)
- career_trajectory_vector
- career_narrative_type
- career_transition_detected
- job_change_signal_strength
- experience_gap_analysis

### 教育分析
- education_structured
- highest_degree
- education_level

### 影响力分析
- influence_score
- credibility_assessment
- engagement_rate
- content_activity_level

### 招聘相关
- open_to_work (可能在API)
- cold_outreach_hooks
- interview_questions_suggested
- culture_fit_indicators

### 完整性评估
- profile_completeness_score
- internal_consistency_flags

### 高级分析
- investor_brief
- full_profile_narrative
- skills_extracted (从about推断)

## 4. 行动计划

### 短期 (修复现有代码)
1. 修复schema_contract.py中的API字段映射
2. 确保voyager API返回的字段都正确提取

### 中期 (增强HTML提取)
1. 在API失败时fallback到playwright/camoufox
2. 添加HTML提取逻辑获取followers, about, banner_image

### 长期 (LLM Enrich)
1. 实现enrich pipeline处理59个分析字段
2. 分组处理：identity, about_analysis, career_analysis等
