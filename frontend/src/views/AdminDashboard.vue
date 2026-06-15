<template>
  <div class="admin-layout">
    <!-- Left: Character List -->
    <div class="char-panel">
      <div class="panel-header">
        <span class="panel-title">角色库 <span class="count-badge">{{ chars.characters.length }}</span></span>
        <div style="display:flex;gap:6px">
          <button class="btn btn-ghost" style="padding:6px 10px;font-size:12px" @click="openImportModal">导入/导出</button>
          <button class="btn btn-primary" style="padding:6px 12px;font-size:12px" @click="openCreateModal">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            新建
          </button>
        </div>
      </div>

      <!-- Search -->
      <div style="padding:12px 12px 0">
        <input class="input" v-model="searchQ" placeholder="搜索角色…" style="font-size:12px"/>
      </div>

      <div class="char-list">
        <div v-if="chars.loading" class="loading-state">
          <div class="spinner"></div>
        </div>
        <template v-else>
          <div v-for="c in filteredChars" :key="c.id"
            class="char-item" :class="{ active: activeChar?.id === c.id }"
            @click="selectChar(c)">
            <div class="char-avatar-sm" :style="{ background: c.avatar_color }">{{ c.name[0] }}</div>
            <div class="char-info">
              <div class="char-name">{{ c.name }}</div>
              <div class="char-role">{{ c.role || '无角色' }}</div>
            </div>
            <div class="char-version">v{{ c.version }}</div>
          </div>
          <div v-if="!filteredChars.length" class="empty-hint">{{ searchQ ? '无匹配结果' : '点击"新建"创建角色' }}</div>
        </template>
      </div>
    </div>

    <!-- Center: Detail & Graph tabs -->
    <div class="detail-panel">
      <div v-if="!activeChar" class="no-select">
        <div class="ns-icon">◈</div>
        <div class="ns-title">选择角色查看详情</div>
        <div class="ns-desc">或切换到关系图谱总览</div>
        <button class="btn btn-ghost" style="margin-top:16px" @click="activeTab = 'graph'">查看关系图谱</button>
      </div>

      <template v-else>
        <!-- Tabs -->
        <div class="detail-tabs">
          <button v-for="t in tabs" :key="t.key"
            class="tab-btn" :class="{ active: activeTab === t.key }"
            @click="activeTab = t.key">{{ t.label }}</button>
        </div>

        <!-- ── PROFILE TAB ── -->
        <div v-if="activeTab === 'profile'" class="tab-content">
          <div class="profile-header">
            <div class="big-avatar" :style="{ background: activeChar.avatar_color }">{{ activeChar.name[0] }}</div>
            <div class="profile-meta">
              <div class="profile-name">{{ activeChar.name }}</div>
              <div class="profile-role">{{ activeChar.role }}</div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
                <span v-for="tag in (activeChar.personality_tags || [])" :key="tag" class="tag">{{ tag }}</span>
              </div>
              <div v-if="profileView?.completeness" class="completeness-row" :title="completenessTooltip">
                <div class="completeness-track">
                  <div class="completeness-fill" :style="{ width: profileView.completeness.score + '%', background: completenessColor(profileView.completeness.score) }"></div>
                </div>
                <span class="completeness-text">档案完整度 {{ profileView.completeness.score }}%</span>
                <span v-if="profileView.completeness.missing?.length" class="completeness-missing">缺：{{ profileView.completeness.missing.slice(0, 3).join('、') }}{{ profileView.completeness.missing.length > 3 ? '…' : '' }}</span>
                <span v-else-if="profileView.completeness.thin?.length" class="completeness-missing">偏薄：{{ profileView.completeness.thin.slice(0, 3).join('、') }}</span>
              </div>
            </div>
            <div class="profile-actions">
              <button class="btn btn-ghost" @click="openEditModal(activeChar)">编辑</button>
              <button class="btn btn-ghost" @click="handleSuggestUpdate" :class="{ loading: loadingSuggest }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
                AI 建议
              </button>
              <button class="btn btn-ghost" @click="showMergeModal = true" title="把另一个重复角色并入当前角色">合并</button>
              <button class="btn btn-danger" @click="handleDelete(activeChar.id)">删除</button>
            </div>
          </div>

          <div class="section">
            <div class="section-title">基础信息</div>
            <div class="info-grid">
              <div class="info-item">
                <div class="info-label">名字</div>
                <div class="info-value">{{ currentProfile.basic_info?.name || activeChar.name }}</div>
              </div>
              <div class="info-item">
                <div class="info-label">身份</div>
                <div class="info-value">{{ currentProfile.basic_info?.role || '—' }}</div>
              </div>
              <div class="info-item">
                <div class="info-label">年龄</div>
                <div class="info-value">{{ currentProfile.basic_info?.age ?? '—' }}</div>
              </div>
              <div class="info-item">
                <div class="info-label">背景故事</div>
                <div class="info-value">{{ currentProfile.basic_info?.background || '—' }}</div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">人格模型</div>
            <div class="info-grid">
              <div class="info-item">
                <div class="info-label">人格特征</div>
                <div style="display:flex;gap:6px;flex-wrap:wrap">
                  <span v-for="tag in (currentProfile.personality_model?.tags || [])" :key="`trait-${tag}`" class="tag">{{ tag }}</span>
                  <span v-if="!(currentProfile.personality_model?.tags || []).length" class="empty-hint" style="padding:0">暂无人格特征</span>
                </div>
              </div>
              <div class="info-item">
                <div class="info-label">大五人格</div>
                <div class="traits-grid">
                  <div v-for="(val, key) in (currentProfile.personality_model?.core_traits || {})" :key="key" class="trait-row">
                    <span class="trait-name">{{ traitLabel(key) }}</span>
                    <div class="trait-bar-track">
                      <div class="trait-bar-fill" :style="{ width: `${Math.max(0, Number(val || 0)) * 100}%`, background: traitColor(Number(val || 0)) }"></div>
                    </div>
                    <span class="trait-val">{{ val == null ? '—' : Math.round(Number(val) * 100) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">行为模式</div>
            <div class="behavior-grid">
              <div v-for="(items, category) in behaviorPatternGroups" :key="category" class="behavior-group card">
                <div class="obs-field">{{ category }}</div>
                <div v-if="!items.length" class="empty-hint" style="padding:16px 0">暂无标签</div>
                <div v-else style="display:flex;gap:8px;flex-wrap:wrap">
                  <button
                    v-for="item in items"
                    :key="`behavior-${category}-${item.id || item.label}`"
                    type="button"
                    class="tag behavior-tag-btn"
                    @click="toggleBehaviorItem(`${category}-${item.id || item.label}`)"
                  >
                    {{ item.label }}
                  </button>
                </div>
                <div v-for="item in items" :key="`behavior-detail-${category}-${item.id || item.label}`">
                  <div v-if="isBehaviorExpanded(`${category}-${item.id || item.label}`)" class="obs-reason" style="margin-top:8px">
                    <div>来源：{{ item.source || 'AI自动识别' }}</div>
                    <div>依据：{{ item.evidence || '暂无' }}</div>
                    <div>置信度：{{ Number(item.confidence || 0).toFixed(2) }}</div>
                    <div v-if="item.trigger">触发：{{ item.trigger }}</div>
                    <div v-if="item.example">示例：{{ item.example }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">核心动机</div>
            <div class="card section-card">{{ currentProfile.core_motivation || '—' }}</div>
          </div>

          <div class="section">
            <div class="section-title">核心弱点</div>
            <div class="card section-card">{{ currentProfile.core_weakness || '—' }}</div>
          </div>

          <div class="section">
            <div class="section-title">说话风格</div>
            <div class="card section-card">
              <div>{{ currentProfile.speaking_style?.summary || '—' }}</div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
                <span v-for="tag in (currentProfile.speaking_style?.tags || [])" :key="`style-${tag}`" class="tag">{{ tag }}</span>
              </div>
            </div>
          </div>

          <!-- 立体人物模型（八维度） -->
          <div class="section" v-if="hasExtendedProfile">
            <div class="section-title">立体人物模型</div>
            <div class="card section-card extended-grid">
              <div v-for="dim in extendedDimensions" :key="`ext-${dim.key}`" class="ext-block">
                <div class="ext-label">{{ dim.label }}</div>
                <div class="ext-items">
                  <div v-for="(line, i) in dim.lines" :key="`ext-${dim.key}-${i}`" class="ext-item">{{ line }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 系统正在琢磨的假设（活的分析） -->
          <div class="section" v-if="(profileView?.hypotheses || []).length">
            <div class="section-title">进行中的人物假设 <span class="count-badge">{{ profileView.hypotheses.length }}</span></div>
            <div class="card section-card" style="display:flex;flex-direction:column;gap:10px">
              <div class="obs-reason" style="opacity:.7">系统根据对话与导入持续验证这些猜想，置信度达 80% 自动写入档案。</div>
              <div v-for="h in profileView.hypotheses" :key="`hypo-${h.id}`" class="hypo-row">
                <div class="hypo-track">
                  <div class="hypo-fill" :style="{ width: Math.round(h.confidence * 100) + '%', background: completenessColor(h.confidence * 100) }"></div>
                </div>
                <div class="hypo-body">
                  <span class="tag" style="font-size:10px">{{ dimensionLabel(h.dimension) }}</span>
                  <span class="hypo-text">{{ h.hypothesis }}</span>
                </div>
                <span class="hypo-conf">{{ Math.round(h.confidence * 100) }}%
                  <small v-if="h.supporting_count">+{{ h.supporting_count }}</small><small v-if="h.contradicting_count" class="neg">-{{ h.contradicting_count }}</small>
                </span>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">关系网络</div>
            <div class="card section-card">
              <div v-if="!(currentProfile.relationship_network || []).length">—</div>
              <div v-else style="display:flex;gap:8px;flex-wrap:wrap">
                <span v-for="rel in currentProfile.relationship_network" :key="`profile-rel-${rel.id || rel.target_name}`" class="tag">
                  {{ rel.target_name }} · {{ relTypeLabel(rel.rel_type) }}
                </span>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">事件时间线</div>
            <div class="card section-card">
              <div v-if="!(currentProfile.event_timeline || []).length">—</div>
              <div v-else class="compact-list">
                <div v-for="event in currentProfile.event_timeline.slice(0, 5)" :key="`profile-event-${event.id || event.title}`">
                  {{ event.title }}{{ event.event_date ? ` · ${event.event_date}` : '' }}
                </div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">AI自动更新</div>
            <div class="card section-card update-summary-card">
              <div>
                <div style="font-size:16px;font-weight:700;color:var(--text-primary)">✔ 本次更新：{{ aiUpdateSummary.total || 0 }}项</div>
                <div class="obs-reason" style="margin-top:6px">已自动应用 {{ aiUpdateSummary.approved || 0 }} 项，待确认 {{ aiUpdateSummary.pending || 0 }} 项</div>
              </div>
              <button class="btn btn-primary" @click="openAiUpdates">查看详情</button>
            </div>
          </div>

          <div class="section">
            <div class="section-title">档案版本（融合出错可随时回滚）</div>
            <div v-if="!snapshots.length" class="card section-card">暂无快照</div>
            <div v-else class="card section-card" style="display:flex;flex-direction:column;gap:8px">
              <div v-for="snap in snapshots.slice(0, 6)" :key="`snap-${snap.id}`" class="snapshot-row">
                <span class="tag" style="font-size:10px">v{{ snap.version }}</span>
                <span style="font-size:12px;color:var(--text-secondary)">{{ snap.source || '未知来源' }}</span>
                <span class="tl-date" style="margin-left:auto">{{ formatSnapDate(snap.created_at) }}</span>
                <button class="btn btn-ghost" style="font-size:11px;padding:3px 10px" @click="restoreSnapshot(snap)">恢复</button>
              </div>
            </div>
          </div>
        </div>

        <!-- ── TIMELINE TAB ── -->
        <div v-if="activeTab === 'timeline'" class="tab-content">
          <div class="timeline-header">
            <div class="section-title" style="margin:0">人物事迹时间线</div>
            <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="showEventModal = true">＋ 添加事件</button>
          </div>
          <div v-if="!events.length" class="empty-hint" style="padding:40px 0">暂无事迹记录</div>
          <div class="timeline">
            <div v-for="ev in sortedEvents" :key="ev.id" class="timeline-item">
              <div class="tl-dot" :style="{ background: ev.arc_marker ? 'var(--violet, #7c3aed)' : importanceColor(ev.importance) }"></div>
              <div class="tl-line"></div>
              <div class="tl-body card" :class="{ 'arc-event': ev.arc_marker }">
                <div class="tl-top">
                  <span class="tl-title">{{ ev.arc_marker ? '⚡ ' : '' }}{{ ev.title }}</span>
                  <div style="display:flex;gap:6px;align-items:center">
                    <span v-if="ev.arc_marker" class="tag violet" style="font-size:10px">人物转折</span>
                    <span v-if="ev.emotion_label" class="tag" style="font-size:10px">{{ ev.emotion_label }}</span>
                    <span class="tl-date">{{ ev.event_date }}</span>
                    <button class="del-btn" @click="deleteEvent(ev.id)">✕</button>
                  </div>
                </div>
                <div class="tl-desc">{{ ev.description }}</div>
                <div v-if="ev.psychological_impact" class="tl-impact">心理影响：{{ ev.psychological_impact }}</div>
                <div class="importance-dots">
                  <span v-for="i in 5" :key="i" class="imp-dot" :class="{ filled: i <= ev.importance }"></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── RELATIONSHIPS TAB ── -->
        <div v-if="activeTab === 'relations'" class="tab-content">
          <div class="rel-header">
            <div class="section-title" style="margin:0">关系网络</div>
            <span v-if="importCompletionNotice" class="tag green" style="font-size:11px">{{ importCompletionNotice }}</span>
            <button class="btn btn-ghost" style="font-size:12px;padding:6px 12px" @click="showRelModal = true">＋ 添加关系</button>
          </div>
          <div class="rel-list">
            <div v-for="rel in charRelationships" :key="rel.id" class="rel-card card">
              <div class="rel-parties">
                <div class="rel-char">
                  <div class="char-avatar-sm" :style="{ background: getCharColor(rel.source_id) }">{{ getCharLetter(rel.source_id) }}</div>
                  <span>{{ getCharName(rel.source_id) }}</span>
                </div>
                <div class="rel-type-badge" :class="rel.rel_type">{{ relTypeLabel(rel.rel_type) }}</div>
                <div class="rel-char">
                  <div class="char-avatar-sm" :style="{ background: getCharColor(rel.target_id) }">{{ getCharLetter(rel.target_id) }}</div>
                  <span>{{ getCharName(rel.target_id) }}</span>
                </div>
              </div>
              <div class="rel-metrics">
                <div class="rel-metric">
                  <span class="rel-m-label">关系强度</span>
                  <div class="mini-bar">
                    <div class="mini-fill" :style="{ width: (rel.strength*100)+'%', background: 'var(--cyan)' }"></div>
                  </div>
                  <span class="rel-m-val">{{ Math.round(rel.strength*100) }}%</span>
                </div>
                <div class="rel-metric">
                  <span class="rel-m-label">情感极性</span>
                  <div class="mini-bar">
                    <div class="mini-fill" :style="{ width: Math.abs(rel.sentiment)*50+'%', marginLeft: rel.sentiment < 0 ? 'auto' : '0', background: rel.sentiment >= 0 ? 'var(--green)' : 'var(--red)' }"></div>
                  </div>
                  <span class="rel-m-val">{{ rel.sentiment >= 0 ? '+' : '' }}{{ rel.sentiment.toFixed(1) }}</span>
                </div>
              </div>
              <!-- 关系深度分析（导入时自动生成） -->
              <div v-if="hasRelAnalysis(rel)" class="rel-deep">
                <div v-if="rel.analysis_json.power_dynamic" class="rel-deep-row"><span class="rel-deep-k">权力结构</span><span>{{ rel.analysis_json.power_dynamic }}</span></div>
                <div v-if="rel.analysis_json.interaction_pattern" class="rel-deep-row"><span class="rel-deep-k">互动模式</span><span>{{ rel.analysis_json.interaction_pattern }}</span></div>
                <div v-if="rel.analysis_json.perception_gap" class="rel-deep-row"><span class="rel-deep-k">认知差</span><span>{{ rel.analysis_json.perception_gap }}</span></div>
                <div v-if="(rel.analysis_json.tensions || []).length" class="rel-deep-row"><span class="rel-deep-k">张力</span><span>{{ rel.analysis_json.tensions.join('；') }}</span></div>
                <div v-if="rel.analysis_json.trajectory" class="rel-deep-row"><span class="rel-deep-k">演化</span><span>{{ rel.analysis_json.trajectory }}</span></div>
              </div>
              <div v-else-if="rel.description" class="rel-deep">
                <div class="rel-deep-row"><span class="rel-deep-k">说明</span><span>{{ rel.description }}</span></div>
              </div>
              <div style="display:flex;gap:6px;margin-top:8px">
                <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" @click="openEditRel(rel)">编辑</button>
                <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" @click="analyzeRel(rel.id)">AI分析</button>
                <button class="btn btn-danger" style="font-size:11px;padding:4px 10px" @click="chars.deleteRelationship(rel.id)">删除</button>
              </div>
            </div>
            <div v-if="!charRelationships.length" class="empty-hint" style="padding:40px 0">暂无关系记录</div>
          </div>
        </div>
      </template>
    </div>

    <!-- Right: Global Relationship Graph -->
    <div class="graph-panel">
      <div class="panel-header">
        <span class="panel-title">全局关系图谱</span>
        <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" @click="renderGraph">刷新</button>
      </div>
      <canvas ref="graphCanvas" class="graph-canvas"></canvas>
      <div v-if="!chars.characters.length" class="graph-empty">
        <div style="font-size:32px;color:var(--border-strong)">◈</div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:8px">创建角色后显示图谱</div>
      </div>

      <!-- AI Analysis Result -->
      <div v-if="relAnalysis" class="rel-analysis card fade-up">
        <div style="display:flex;justify-content:space-between;margin-bottom:8px">
          <span style="font-size:12px;font-weight:600">AI 关系分析</span>
          <button @click="relAnalysis=null" style="background:none;border:none;color:var(--text-muted);cursor:pointer">✕</button>
        </div>
        <p style="font-size:12px;color:var(--text-secondary);line-height:1.7">{{ relAnalysis.relationship_summary }}</p>
        <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
          <span class="tag" :class="trendClass(relAnalysis.predicted_trend)">趋势: {{ trendLabel(relAnalysis.predicted_trend) }}</span>
          <span v-for="t in relAnalysis.key_tensions" :key="t" class="tag violet" style="font-size:10px">{{ t }}</span>
        </div>
      </div>
    </div>

    <!-- ── CREATE/EDIT CHARACTER MODAL ── -->
    <Teleport to="body">
      <div v-if="showCharModal" class="modal-overlay" @click.self="showCharModal = false">
        <div class="modal card fade-up" style="width:520px;max-height:85vh;overflow-y:auto">
          <div class="modal-header">
            <span>{{ editingChar ? '编辑角色' : '创建角色' }}</span>
            <button class="btn-close" @click="showCharModal = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:14px">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div>
                <label class="label">姓名 *</label>
                <input class="input" v-model="charForm.name" placeholder="角色姓名"/>
              </div>
              <div>
                <label class="label">角色定位</label>
                <input class="input" v-model="charForm.role" placeholder="如：CEO、顾问、朋友"/>
              </div>
            </div>
            <div>
              <label class="label">别名 / 其他称呼（逗号分隔）</label>
              <input class="input" v-model="charForm.aliases_text" placeholder="如：张总, 老张 —— 导入时按别名自动归并到本角色"/>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div>
                <label class="label">年龄</label>
                <input class="input" v-model.number="charForm.age" type="number" placeholder="可选"/>
              </div>
              <div>
                <label class="label">头像颜色</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px">
                  <input type="color" v-model="charForm.avatar_color" style="width:36px;height:36px;border:none;background:none;cursor:pointer;border-radius:4px"/>
                  <span style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono)">{{ charForm.avatar_color }}</span>
                </div>
              </div>
            </div>
            <div>
              <label class="label">背景故事</label>
              <textarea class="input" v-model="charForm.background" rows="3" placeholder="角色的背景、经历、身份信息…" style="resize:vertical"></textarea>
            </div>
            <div>
              <label class="label">核心动机</label>
              <input class="input" v-model="charForm.motivation" placeholder="驱动这个角色的深层需求或目标"/>
            </div>
            <div>
              <label class="label">核心弱点</label>
              <input class="input" v-model="charForm.weakness" placeholder="心理弱点或容易被攻破的地方"/>
            </div>
            <div>
              <label class="label">说话风格</label>
              <input class="input" v-model="charForm.speaking_style" placeholder="如：直接犀利、绕弯子、喜欢问反问句…"/>
            </div>
            <div>
              <label class="label">人格特征（逗号分隔）</label>
              <input class="input" v-model="charForm.personality_tags_text" placeholder="如：自信, 控制欲, 攻击性"/>
            </div>
            <div v-if="editingChar">
              <label class="label">大五人格（拖动调整）</label>
              <div class="form-traits">
                <div v-for="key in BIG_FIVE_KEYS" :key="`form-trait-${key}`" class="form-trait-row">
                  <span class="trait-name">{{ traitLabel(key) }}</span>
                  <input type="range" v-model.number="charForm.core_traits[key]" min="0" max="1" step="0.05" style="flex:1;accent-color:var(--cyan)"/>
                  <span class="trait-val">{{ Math.round((charForm.core_traits[key] ?? 0) * 100) }}</span>
                </div>
              </div>
            </div>
            <!-- AI 待确认建议：导入/对话分析产生的档案补充，可一键采纳进档案 -->
            <div v-if="editingChar && pendingProfileObs.length">
              <label class="label">AI 待确认建议（{{ pendingProfileObs.length }} 条）</label>
              <div style="display:flex;flex-direction:column;gap:8px">
                <div v-for="obs in pendingProfileObs" :key="`suggest-${obs.id}`" class="card suggest-card">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
                    <span class="tag violet" style="font-size:10px">{{ profileFieldLabel(obs.field) }} · {{ obs.metadata_json?.change_type || '更新' }}</span>
                    <div style="display:flex;gap:6px">
                      <button class="btn btn-ghost" style="font-size:11px;padding:3px 10px" @click="adoptSuggestion(obs)">采纳</button>
                      <button class="btn btn-ghost" style="font-size:11px;padding:3px 10px;opacity:.7" @click="dismissSuggestion(obs)">忽略</button>
                    </div>
                  </div>
                  <div class="obs-reason" style="margin-top:6px">{{ obs.new_value }}</div>
                  <div v-if="obs.metadata_json?.evidence" class="obs-reason" style="opacity:.65;font-size:11px">依据：{{ obs.metadata_json.evidence }}</div>
                </div>
              </div>
            </div>
            <div>
              <label class="label">行为模式（可编辑）</label>
              <div style="display:flex;flex-direction:column;gap:10px">
                <div v-for="(pattern, idx) in charForm.behavior_patterns" :key="pattern.localId" class="card" style="padding:12px;border:1px solid var(--border)">
                  <div style="display:grid;grid-template-columns:1fr 120px 100px;gap:8px">
                    <input class="input" v-model="pattern.new_value" placeholder="行为模式名称"/>
                    <select class="input" v-model="pattern.category">
                      <option value="攻击型行为">攻击型行为</option>
                      <option value="防御型行为">防御型行为</option>
                      <option value="互动策略">互动策略</option>
                    </select>
                    <input class="input" v-model.number="pattern.confidence" type="number" min="0" max="1" step="0.01" placeholder="置信度"/>
                  </div>
                  <input class="input" v-model="pattern.source" placeholder="来源，如：AI自动识别 / 手动编辑" style="margin-top:8px"/>
                  <input class="input" v-model="pattern.trigger" placeholder="触发条件，如：被挑战时" style="margin-top:8px"/>
                  <input class="input" v-model="pattern.example" placeholder="示例" style="margin-top:8px"/>
                  <div style="display:flex;justify-content:flex-end;margin-top:8px">
                    <button class="btn btn-danger" style="padding:4px 10px;font-size:11px" @click="removeBehaviorPatternForm(idx)">删除</button>
                  </div>
                </div>
                <button class="btn btn-ghost" style="width:fit-content" @click="addBehaviorPatternForm">＋ 新增行为模式</button>
              </div>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px">
              <button class="btn btn-ghost" @click="showCharModal = false">取消</button>
              <button class="btn btn-primary" @click="submitChar" :disabled="!charForm.name.trim()">
                {{ editingChar ? '保存更改' : '创建 (AI 自动生成档案)' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- ── MERGE CHARACTER MODAL ── -->
      <div v-if="showMergeModal && activeChar" class="modal-overlay" @click.self="showMergeModal = false">
        <div class="modal card fade-up" style="width:440px">
          <div class="modal-header">
            <span>合并角色到「{{ activeChar.name }}」</span>
            <button class="btn-close" @click="showMergeModal = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:14px">
            <div class="obs-reason">
              选择一个与「{{ activeChar.name }}」实为同一人物的角色。其全部事件、记忆、证据、关系将并入当前角色，
              其名字自动成为当前角色的别名，然后该角色被删除。此操作不可撤销。
            </div>
            <div>
              <label class="label">被并入的角色（将被删除）</label>
              <select class="input" v-model.number="mergeSourceId">
                <option :value="null" disabled>选择角色…</option>
                <option v-for="c in mergeCandidates" :key="`merge-${c.id}`" :value="c.id">{{ c.name }}{{ c.role ? `（${c.role}）` : '' }}</option>
              </select>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
              <button class="btn btn-ghost" @click="showMergeModal = false">取消</button>
              <button class="btn btn-primary" :disabled="!mergeSourceId" @click="handleMergeCharacter">确认合并</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ── ADD RELATIONSHIP MODAL ── -->
      <div v-if="showRelModal" class="modal-overlay" @click.self="showRelModal = false">
        <div class="modal card fade-up" style="width:440px">
          <div class="modal-header">
            <span>{{ editingRel ? '编辑关系' : '创建关系' }}</span>
            <button class="btn-close" @click="showRelModal = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:14px">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px" v-if="!editingRel">
              <div>
                <label class="label">角色 A</label>
                <select class="input" v-model.number="relForm.source_id">
                  <option v-for="c in chars.characters" :key="c.id" :value="c.id">{{ c.name }}</option>
                </select>
              </div>
              <div>
                <label class="label">角色 B</label>
                <select class="input" v-model.number="relForm.target_id">
                  <option v-for="c in chars.characters" :key="c.id" :value="c.id">{{ c.name }}</option>
                </select>
              </div>
            </div>
            <div>
              <label class="label">关系类型</label>
              <select class="input" v-model="relForm.rel_type">
                <option value="ally">盟友</option>
                <option value="rival">对手</option>
                <option value="friend">朋友</option>
                <option value="family">家人</option>
                <option value="romantic">恋人</option>
                <option value="neutral">中立</option>
              </select>
            </div>
            <div>
              <label class="label">关系强度 {{ Math.round(relForm.strength * 100) }}%</label>
              <input type="range" v-model.number="relForm.strength" min="0" max="1" step="0.05" style="width:100%;accent-color:var(--cyan)"/>
            </div>
            <div>
              <label class="label">情感极性 {{ relForm.sentiment >= 0 ? '+' : '' }}{{ relForm.sentiment.toFixed(1) }}</label>
              <input type="range" v-model.number="relForm.sentiment" min="-1" max="1" step="0.1" style="width:100%;accent-color:var(--cyan)"/>
            </div>
            <div>
              <label class="label">关系描述</label>
              <textarea class="input" v-model="relForm.description" rows="2" placeholder="简要描述两人关系…" style="resize:vertical"></textarea>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
              <button class="btn btn-ghost" @click="showRelModal = false">取消</button>
              <button class="btn btn-primary" @click="submitRel">{{ editingRel ? '保存' : '创建关系' }}</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ── ADD EVENT MODAL ── -->
      <div v-if="showEventModal" class="modal-overlay" @click.self="showEventModal = false">
        <div class="modal card fade-up" style="width:440px">
          <div class="modal-header">
            <span>添加事件</span>
            <button class="btn-close" @click="showEventModal = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:14px">
            <div><label class="label">事件标题 *</label><input class="input" v-model="eventForm.title" placeholder="事件名称"/></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div><label class="label">事件日期</label><input class="input" v-model="eventForm.event_date" placeholder="如：2024-03"/></div>
              <div><label class="label">情绪标签</label><input class="input" v-model="eventForm.emotion_label" placeholder="如：愤怒、喜悦"/></div>
            </div>
            <div>
              <label class="label">重要程度 {{ eventForm.importance }}/5</label>
              <input type="range" v-model.number="eventForm.importance" min="1" max="5" step="1" style="width:100%;accent-color:var(--cyan)"/>
            </div>
            <div><label class="label">详细描述</label><textarea class="input" v-model="eventForm.description" rows="3" style="resize:vertical" placeholder="描述事件经过…"></textarea></div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
              <button class="btn btn-ghost" @click="showEventModal = false">取消</button>
              <button class="btn btn-primary" @click="submitEvent">添加事件</button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="showImportModal" class="modal-overlay">
        <div class="modal card fade-up" style="width:880px;max-height:88vh;overflow-y:auto">
          <div class="modal-header">
            <span>智能导入 / 导出</span>
            <div class="import-steps">
              <span class="step" :class="{ active: importStep === 'upload', done: importStep !== 'upload' }">① 上传</span>
              <span class="step" :class="{ active: importStep === 'preview', done: ['running','done'].includes(importStep) }">② 确认</span>
              <span class="step" :class="{ active: importStep === 'running', done: importStep === 'done' }">③ 入库</span>
              <span class="step" :class="{ active: importStep === 'done' }">④ 完成</span>
            </div>
            <button class="btn-close" @click="closeImportModal">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:16px">

            <!-- ① 上传 -->
            <div v-if="importStep === 'upload' || importStep === 'preview'" class="section" style="margin-bottom:0">
              <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                <input ref="importFileInput" type="file" class="input" accept=".txt,.md,.pdf,.docx,.json,.csv" style="max-width:340px" @change="handleImportFileChange"/>
                <button type="button" class="btn btn-primary" :disabled="!selectedImportFile || importLoading" @click.prevent="previewImport">
                  {{ importLoading ? '解析中…' : (importPreviewPending ? 'AI增强处理中…' : '上传并解析') }}
                </button>
                <button type="button" class="btn btn-ghost" @click.prevent="downloadExport">导出全量 JSON</button>
              </div>
              <div v-if="importError" class="tag red" style="width:fit-content;margin-top:8px">{{ importError }}</div>
              <div v-else-if="importNotice" class="tag amber" style="width:fit-content;margin-top:8px">{{ importNotice }}</div>
              <div class="empty-hint" style="padding:8px 0 0;text-align:left">支持 TXT / MD / PDF / DOCX / JSON / CSV。上传后先生成预览，确认无误再写入系统。</div>
            </div>

            <!-- ② 预览确认 -->
            <template v-if="importStep === 'preview' && importPreview">
              <!-- 统计条 -->
              <div class="import-stats">
                <span class="stat-chip">角色 <b>{{ importPreview.role_mappings?.length || 0 }}</b></span>
                <span class="stat-chip">对话 <b>{{ importPreview.interaction_units?.length || 0 }}</b></span>
                <span class="stat-chip">事件 <b>{{ importPreview.events?.length || 0 }}</b></span>
                <span class="stat-chip">关系 <b>{{ importPreview.relationships?.length || 0 }}</b></span>
                <span class="stat-chip amber" v-if="importPreview.low_confidence_units?.length">低置信 <b>{{ importPreview.low_confidence_units.length }}</b></span>
              </div>
              <div v-if="importPreview.plot_summary?.main_conflict" class="card" style="padding:12px 16px">
                <div class="obs-field">主冲突</div>
                <div class="obs-reason">{{ importPreview.plot_summary.main_conflict }}</div>
                <div v-if="importPreview.plot_summary?.relationship_path" class="obs-field" style="margin-top:8px">关系演化</div>
                <div v-if="importPreview.plot_summary?.relationship_path" class="obs-reason">{{ importPreview.plot_summary.relationship_path }}</div>
              </div>

              <div class="import-grid">
                <!-- 角色确认 -->
                <div class="card import-card">
                  <div class="section-title">角色确认（可改名 / 映射 / 跳过）</div>
                  <div v-if="!importPreview.role_mappings?.length" class="empty-hint">暂无角色</div>
                  <div v-else class="import-list">
                    <div v-for="mapping in importPreview.role_mappings" :key="mapping.original_name" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>{{ mapping.original_name }}</strong>
                        <span class="tag" :class="mapping.status === 'confirmed' ? 'green' : mapping.status === 'ambiguous' ? 'amber' : 'violet'">
                          {{ { confirmed: '已匹配', ambiguous: '疑似重名', new: '新角色' }[mapping.status] || mapping.status }}
                        </span>
                      </div>
                      <div style="display:grid;grid-template-columns:1fr 92px;gap:8px;margin-top:8px">
                        <input class="input" v-model="mapping.resolved_name" placeholder="确认名称 / 合并名称"/>
                        <select class="input" v-model="mapping.action">
                          <option value="create">新建</option>
                          <option value="link">映射</option>
                          <option value="skip">跳过</option>
                        </select>
                      </div>
                      <div v-if="importPreview.character_profiles?.[mapping.original_name]" style="display:flex;gap:5px;flex-wrap:wrap;margin-top:8px">
                        <span v-for="trait in (importPreview.character_profiles[mapping.original_name].personality_model?.tags || []).slice(0, 5)" :key="`${mapping.original_name}-${trait}`" class="tag" style="font-size:10px">{{ trait }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 内容预览（标签页切换） -->
                <div class="card import-card">
                  <div class="preview-tabs">
                    <button class="ptab" :class="{ active: previewTab === 'facts' }" @click="previewTab = 'facts'">
                      人物事实 <b v-if="(importPreview.persona_facts || []).length">{{ importPreview.persona_facts.length }}</b>
                    </button>
                    <button class="ptab" :class="{ active: previewTab === 'units' }" @click="previewTab = 'units'">对话样例</button>
                    <button class="ptab" :class="{ active: previewTab === 'relationships' }" @click="previewTab = 'relationships'">关系</button>
                    <button class="ptab" :class="{ active: previewTab === 'events' }" @click="previewTab = 'events'">事件</button>
                  </div>

                  <div v-if="previewTab === 'facts'" class="import-list">
                    <div v-if="!importPreview.persona_facts?.length" class="empty-hint">未抽取出人物事实</div>
                    <div v-for="(fact, idx) in (importPreview.persona_facts || []).slice(0, 30)" :key="`fact-${idx}`" class="import-item">
                      <div style="display:flex;gap:8px;align-items:center">
                        <span class="tag violet" style="font-size:10px">{{ fact.subject }}</span>
                        <span class="tag" style="font-size:10px">{{ fact.category }}</span>
                        <span v-if="fact.time_hint" class="tl-date">{{ fact.time_hint }}</span>
                      </div>
                      <div class="obs-reason" style="margin-top:6px">{{ fact.content }}</div>
                    </div>
                    <div v-if="(importPreview.persona_facts || []).length > 30" class="empty-hint" style="padding:6px 0">
                      共 {{ importPreview.persona_facts.length }} 条事实，全部将沉淀为人物证据
                    </div>
                  </div>

                  <div v-if="previewTab === 'units'" class="import-list">
                    <div v-if="!importPreview.interaction_units?.length" class="empty-hint">未识别出对话</div>
                    <div v-for="(unit, idx) in (importPreview.interaction_units || []).slice(0, 8)" :key="`unit-${idx}`" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>{{ unit.speaker }} → {{ unit.receiver || '待推断' }}</strong>
                        <span class="tag" :class="unit.receiver_confidence >= 0.6 ? 'green' : 'amber'">{{ Math.round((unit.receiver_confidence || 0) * 100) }}%</span>
                      </div>
                      <div class="obs-reason" style="margin-top:6px">{{ unit.content }}</div>
                      <div v-if="unit.psychological_label" class="tag violet" style="margin-top:6px;width:fit-content;font-size:10px">{{ unit.psychological_label }}</div>
                    </div>
                    <div v-if="(importPreview.interaction_units || []).length > 8" class="empty-hint" style="padding:6px 0">
                      共 {{ importPreview.interaction_units.length }} 条，导入后可在只读会话中查看全部
                    </div>
                  </div>

                  <div v-if="previewTab === 'relationships'" class="import-list">
                    <div v-if="!importPreview.relationships?.length" class="empty-hint">未识别出关系</div>
                    <div v-for="(rel, idx) in (importPreview.relationships || []).slice(0, 10)" :key="`rel-${idx}`" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>{{ rel.source }} → {{ rel.target }}</strong>
                        <span class="tag">{{ relTypeLabel(rel.rel_type || 'neutral') }}</span>
                      </div>
                      <div class="obs-reason" style="margin-top:6px">{{ rel.description || '暂无关系说明' }}</div>
                      <div style="display:flex;gap:8px;margin-top:6px;flex-wrap:wrap">
                        <span class="tag" style="font-size:10px">强度 {{ Math.round((rel.strength || 0) * 100) }}%</span>
                        <span class="tag" style="font-size:10px">极性 {{ ((rel.sentiment || 0) > 0 ? '+' : '') + Number(rel.sentiment || 0).toFixed(2) }}</span>
                      </div>
                    </div>
                  </div>

                  <div v-if="previewTab === 'events'" class="import-list">
                    <div v-if="!importPreview.events?.length" class="empty-hint">未识别出事件</div>
                    <div v-for="(ev, idx) in (importPreview.events || []).slice(0, 10)" :key="`ev-${idx}`" class="import-item">
                      <strong>{{ ev.summary || ev.action || '事件' }}</strong>
                      <div class="obs-reason" style="margin-top:4px">
                        {{ [ev.actor, ev.time, ev.location].filter(Boolean).join(' · ') || '细节待入库后补全' }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 真实聊天导入：标记「我是谁」（决定后续分析为谁服务） -->
              <div v-if="(importPreview.speakers || []).length >= 2" class="card" style="padding:14px 16px;margin-bottom:12px">
                <div class="obs-field">这段聊天里，哪个是「我」（你本人）？</div>
                <div class="obs-reason" style="margin:4px 0 10px">选中后，另一方会被建模为你要洞察的「对方」，分析将围绕“他什么意思 / 我该怎么接”展开。</div>
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                  <button v-for="sp in importPreview.speakers" :key="sp.name" type="button"
                    class="btn" :class="importOptions.self_name === sp.name ? 'btn-primary' : 'btn-ghost'"
                    style="font-size:12px;padding:6px 14px"
                    @click="importOptions.self_name = sp.name">
                    {{ sp.name }} · {{ sp.count }}条
                  </button>
                  <button type="button" class="btn" :class="!importOptions.self_name ? 'btn-primary' : 'btn-ghost'"
                    style="font-size:12px;padding:6px 14px" @click="importOptions.self_name = ''">都不是 / 暂不指定</button>
                </div>
              </div>

              <!-- 写入选项 + 提交 -->
              <div class="card" style="padding:14px 16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
                <label class="check-row"><input type="checkbox" v-model="importOptions.create_readonly_conversation"/> 生成只读会话</label>
                <label class="check-row"><input type="checkbox" v-model="importOptions.auto_archive"/> 自动归档更新关系</label>
                <select class="input" v-model="importOptions.scenario" style="max-width:160px">
                  <option value="general">通用对话</option>
                  <option value="bar_chat">老友酒吧闲聊</option>
                  <option value="business">商务谈判</option>
                  <option value="hr_interview">HR面试</option>
                  <option value="counseling">心理咨询</option>
                </select>
                <button type="button" class="btn btn-primary" style="margin-left:auto" :disabled="importLoading || importPreviewPending" @click.prevent="commitImport">
                  {{ importPreviewPending ? '等待 AI 增强完成…' : '确认导入并写入系统' }}
                </button>
              </div>
            </template>

            <!-- ③ 入库进行中 -->
            <div v-if="importStep === 'running'" class="import-running">
              <div class="spinner"></div>
              <div class="running-title">正在后台导入…</div>
              <div class="obs-reason" style="text-align:center">{{ importNotice || 'AI 审核代理正在处理，可关闭此窗口，完成后会有提示。' }}</div>
            </div>

            <!-- ④ 完成结果页 -->
            <template v-if="importStep === 'done' && importResult">
              <div class="import-done-head">
                <span class="done-icon">✓</span>
                <div>
                  <div class="running-title" style="text-align:left">导入完成</div>
                  <div v-if="importReviewSummary" class="obs-reason">AI 审核摘要：{{ importReviewSummary }}</div>
                </div>
              </div>
              <div class="import-stats">
                <span class="stat-chip green">角色 <b>{{ importResult.created_characters?.length || 0 }}</b></span>
                <span class="stat-chip green">人物事实 <b>{{ importResult.persona_facts || 0 }}</b></span>
                <span class="stat-chip green">对话 <b>{{ importResult.interaction_units || 0 }}</b></span>
                <span class="stat-chip green">事件 <b>{{ importResult.events || 0 }}</b></span>
                <span class="stat-chip green">关系 <b>{{ importResult.relationships || 0 }}</b></span>
                <span class="stat-chip green">深度关系 <b>{{ importResult.deep_relationships || 0 }}</b></span>
                <span class="stat-chip green">档案变更 <b>{{ importResult.profile_changes || 0 }}</b></span>
                <span class="stat-chip green" v-if="importResult.hypotheses">新假设 <b>{{ importResult.hypotheses.new || 0 }}</b></span>
              </div>
              <div v-if="(importResult.created_characters || []).length" class="card" style="padding:14px 16px">
                <div class="obs-field" style="margin-bottom:8px">涉及角色（点击查看档案）</div>
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                  <button v-for="name in importResult.created_characters" :key="`done-${name}`" class="tag tag-btn" @click="openCharacterFromImport(name)">{{ name }}</button>
                </div>
              </div>
              <div v-if="importResult.plot_summary?.main_conflict" class="card" style="padding:12px 16px">
                <div class="obs-field">剧情概要</div>
                <div class="obs-reason">{{ importResult.plot_summary.main_conflict }}</div>
              </div>
              <div v-if="importFailureCount" class="card" style="padding:12px 16px;border-color:rgba(245,158,11,.4)">
                <div class="obs-field">部分内容降级（{{ importFailureCount }} 项）</div>
                <div class="obs-reason">个别交互的 AI 分析失败或超时，已用解析结果兜底入库，可稍后在会话中对单条手动补全分析。</div>
              </div>
              <div style="display:flex;gap:10px;justify-content:flex-end">
                <button v-if="importResult.conversation_id" class="btn btn-ghost" @click="goToImportedConversation">查看只读会话</button>
                <button class="btn btn-primary" @click="closeImportModal">完成</button>
              </div>
            </template>

            <!-- 失败 -->
            <div v-if="importStep === 'failed'" class="import-running">
              <span class="done-icon failed">✕</span>
              <div class="running-title">导入失败</div>
              <div class="obs-reason" style="text-align:center">{{ importError || '请查看后台日志确认原因。' }}</div>
              <button class="btn btn-ghost" @click="importStep = importPreview ? 'preview' : 'upload'">返回重试</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCharacterStore } from '../stores/characters.js'
import { characterApi, relationshipApi } from '../api/index.js'
import { toast, confirmDialog } from '../utils/notify.js'

const chars = useCharacterStore()
const router = useRouter()
const route = useRoute()

const searchQ = ref('')
const activeChar = ref(null)
const activeTab = ref('profile')
const events = ref([])
const observations = ref([])
const profileView = ref(null)
const aiUpdateSummary = ref({ total: 0, approved: 0, pending: 0 })
const relAnalysis = ref(null)
const loadingSuggest = ref(false)
const importLoading = ref(false)
const showImportModal = ref(false)
const importFileInput = ref(null)
const selectedImportFile = ref(null)
const importPreview = ref(null)
const importResult = ref(null)
const importError = ref('')
const importNotice = ref('')
const importCompletionNotice = ref('')
const importTaskId = ref(null)
const importPreviewPending = ref(false)
const importStep = ref('upload')         // upload | preview | running | done | failed
const previewTab = ref('units')
const importReviewSummary = ref('')
const importOptions = ref({
  scenario: 'general',
  create_readonly_conversation: true,
  auto_archive: true,
  self_name: '',   // 真实聊天导入时标记哪一方是「我」
})
const importFailureCount = computed(() => {
  const failures = importResult.value?.failures || {}
  return Object.values(failures).reduce((sum, list) => sum + (Array.isArray(list) ? list.length : 0), 0)
})
let importPollTimer = null
let importPollCount = 0
const MAX_POLL_COUNT = 120  // 最多轮询 120 次（配合退避策略约等于 10 分钟上限）

function getNextPollDelay(count) {
  // 指数退避：前 5 次 2s，5-20 次 5s，20 次以后 10s
  if (count < 5) return 2000
  if (count < 20) return 5000
  return 10000
}

const showCharModal = ref(false)
const showRelModal = ref(false)
const showEventModal = ref(false)
const showMergeModal = ref(false)
const mergeSourceId = ref(null)
const snapshots = ref([])
const editingChar = ref(null)
const editingRel = ref(null)
let originalTraits = {}   // 编辑打开时的大五快照：只提交用户实际改动过的维度

const mergeCandidates = computed(() =>
  chars.characters.filter(c => c.id !== activeChar.value?.id)
)
const completenessTooltip = computed(() => {
  const comp = profileView.value?.completeness
  if (!comp) return ''
  const parts = []
  if (comp.missing?.length) parts.push(`待补充：${comp.missing.join('、')}`)
  if (comp.thin?.length) parts.push(`内容偏薄：${comp.thin.join('、')}`)
  return parts.join('\n') || '档案已完整'
})

// 立体人物模型八维度渲染
const EXTENDED_DIM_META = [
  { key: 'values', label: '价值观' },
  { key: 'desires', label: '欲望层次' },
  { key: 'fears', label: '恐惧' },
  { key: 'interpersonal_patterns', label: '人际模式' },
  { key: 'key_experiences', label: '关键经历' },
  { key: 'speech_fingerprint', label: '语言指纹' },
  { key: 'contradictions', label: '矛盾性' },
  { key: 'self_image_vs_public', label: '自我认知 vs 外部印象' },
]
function extEntryText(entry) {
  if (entry == null) return ''
  if (typeof entry === 'string') return entry
  if (Array.isArray(entry)) return entry.filter(Boolean).join('、')
  if (typeof entry === 'object') {
    return Object.entries(entry).filter(([, v]) => v && (!Array.isArray(v) || v.length))
      .map(([k, v]) => `${dimSubLabel(k)}${Array.isArray(v) ? v.join('、') : v}`).join('，')
  }
  return String(entry)
}
const SUB_LABELS = { surface: '表层:', deep: '深层:', content: '', context: '', pattern: '', event: '', impact: '→', side_a: '', side_b: ' ↔ ', interpretation: '（', self: '自认:', public: '他评:', catchphrases: '口头禅:', sentence_style: '句式:', avoided_topics: '回避:' }
function dimSubLabel(k) { return SUB_LABELS[k] ?? `${k}:` }
const extendedDimensions = computed(() => {
  const ext = profileView.value?.extended_profile || {}
  const out = []
  for (const meta of EXTENDED_DIM_META) {
    const value = ext[meta.key]
    let lines = []
    if (Array.isArray(value)) lines = value.map(extEntryText).filter(Boolean)
    else if (value && typeof value === 'object') { const t = extEntryText(value); if (t) lines = [t] }
    if (lines.length) out.push({ key: meta.key, label: meta.label, lines })
  }
  return out
})
const hasExtendedProfile = computed(() => extendedDimensions.value.length > 0)
const DIMENSION_LABELS = {
  values: '价值观', desires: '欲望', fears: '恐惧', interpersonal_patterns: '人际模式',
  key_experiences: '经历', speech_fingerprint: '语言', contradictions: '矛盾', 心理特征: '心理特征',
}
function dimensionLabel(d) { return DIMENSION_LABELS[d] || d }
function hasRelAnalysis(rel) {
  const a = rel.analysis_json
  return a && (a.power_dynamic || a.interaction_pattern || a.perception_gap || a.trajectory || (a.tensions || []).length)
}

const graphCanvas = ref(null)
let animFrame = null
const expandedBehaviorKeys = ref([])

const tabs = [
  { key: 'profile', label: '角色档案' },
  { key: 'timeline', label: '时间线' },
  { key: 'relations', label: '关系' },
]

const BIG_FIVE_KEYS = ['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism']
function normalizeFormTraits(traits) {
  const source = traits || {}
  const result = {}
  for (const key of BIG_FIVE_KEYS) {
    result[key] = typeof source[key] === 'number' ? source[key] : 0.5
  }
  return result
}
const charForm = ref({ name:'', role:'', background:'', age:null, avatar_color:'#00d4ff', motivation:'', weakness:'', speaking_style:'', personality_tags_text:'', aliases_text:'', core_traits: normalizeFormTraits(null), behavior_patterns:[] })
const relForm = ref({ source_id:null, target_id:null, rel_type:'neutral', strength:0.5, sentiment:0.0, description:'' })
const eventForm = ref({ title:'', description:'', event_date:'', emotion_label:'', importance:3 })

const filteredChars = computed(() => {
  if (!searchQ.value) return chars.characters
  return chars.characters.filter(c =>
    c.name.includes(searchQ.value) || (c.role || '').includes(searchQ.value)
  )
})

const charRelationships = computed(() => {
  if (!activeChar.value) return []
  return chars.relationships.filter(
    r => r.source_id === activeChar.value.id || r.target_id === activeChar.value.id
  )
})

const pendingObs = computed(() => observations.value.filter(o => o.status === 'pending'))
const autoAppliedObs = computed(() => observations.value.filter(o => o.status === 'approved'))
const appliedBehaviorPatterns = computed(() => observations.value.filter(o => o.field === 'behavior_pattern' && o.status === 'approved'))
const behaviorPatternGroups = computed(() => profileView.value?.behavior_patterns || { '攻击型行为': [], '防御型行为': [], '互动策略': [] })
const currentProfile = computed(() => profileView.value || {
  basic_info: { name: activeChar.value?.name || '', role: activeChar.value?.role || null, background: activeChar.value?.background || null, age: activeChar.value?.age ?? null },
  personality_model: { tags: activeChar.value?.personality_tags || [], core_traits: activeChar.value?.core_traits || {} },
  behavior_patterns: { '攻击型行为': [], '防御型行为': [], '互动策略': [] },
  core_motivation: activeChar.value?.motivation || null,
  core_weakness: activeChar.value?.weakness || null,
  speaking_style: { summary: activeChar.value?.speaking_style || null, tags: [] },
  relationship_network: [],
  event_timeline: [],
})
const sortedEvents = computed(() => [...events.value].sort((a, b) => {
  const aKey = a.event_date || a.created_at || ''
  const bKey = b.event_date || b.created_at || ''
  return bKey.localeCompare(aKey)
}))

onMounted(async () => {
  await chars.fetchAll()
  const routeCharId = Number(route.query.charId || 0)
  if (routeCharId) {
    const matched = chars.characters.find(item => item.id === routeCharId)
    if (matched) selectChar(matched)
  }
  nextTick(renderGraph)
})

watch(() => chars.relationships, () => nextTick(renderGraph), { deep: true })
watch(() => chars.characters, () => nextTick(renderGraph), { deep: true })

// ── Character Actions ──────────────────────────────────────────────────────
function selectChar(c) {
  activeChar.value = c
  activeTab.value = 'profile'
  router.replace({ path: '/admin', query: { charId: c.id } })
  loadEvents(c.id)
  loadObservations(c.id)
  loadProfileView(c.id)
  loadAiUpdateSummary(c.id)
  loadSnapshots(c.id)
}
async function loadSnapshots(id) {
  try {
    const res = await characterApi.listSnapshots(id)
    snapshots.value = res.data || []
  } catch {
    snapshots.value = []
  }
}
function formatSnapDate(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
async function restoreSnapshot(snap) {
  if (!await confirmDialog(`将「${activeChar.value.name}」的档案回滚到 v${snap.version}（${snap.source || '未知来源'}）？当前档案会先存为新快照，可再次回滚。`)) return
  const res = await characterApi.restoreSnapshot(activeChar.value.id, snap.id)
  activeChar.value = res.data
  const idx = chars.characters.findIndex(c => c.id === res.data.id)
  if (idx >= 0) chars.characters[idx] = res.data
  await Promise.all([loadProfileView(res.data.id), loadObservations(res.data.id), loadSnapshots(res.data.id)])
  toast.success(`已恢复到快照 v${snap.version}`)
}
async function handleMergeCharacter() {
  const source = chars.characters.find(c => c.id === mergeSourceId.value)
  if (!source || !activeChar.value) return
  if (!await confirmDialog(`确认把「${source.name}」并入「${activeChar.value.name}」？\n「${source.name}」的全部数据将转移并删除该角色，其名字成为「${activeChar.value.name}」的别名。`)) return
  const res = await characterApi.mergeCharacter(activeChar.value.id, source.id)
  showMergeModal.value = false
  mergeSourceId.value = null
  await chars.fetchAll()
  const refreshed = chars.characters.find(c => c.id === res.data.id)
  if (refreshed) selectChar(refreshed)
  toast.success(`已合并「${source.name}」，其称呼已记为别名`)
}
async function loadEvents(id) {
  const res = await characterApi.listEvents(id)
  events.value = res.data
}
async function loadObservations(id) {
  const res = await characterApi.listObservations(id)
  observations.value = res.data
}
async function loadProfileView(id) {
  const res = await characterApi.getProfileView(id)
  profileView.value = res.data
}
async function loadAiUpdateSummary(id) {
  const res = await characterApi.getAiUpdateLog(id)
  aiUpdateSummary.value = res.data?.summary || { total: 0, approved: 0, pending: 0 }
}

function openCreateModal() {
  editingChar.value = null
  originalTraits = {}
  charForm.value = { name:'', role:'', background:'', age:null, avatar_color:'#00d4ff', motivation:'', weakness:'', speaking_style:'', personality_tags_text:'', aliases_text:'', core_traits: normalizeFormTraits(null), behavior_patterns:[] }
  showCharModal.value = true
}
function openImportModal() {
  showImportModal.value = true
  // 上次已完成/失败的导入，重新打开时回到上传步骤
  if (importStep.value === 'done' || importStep.value === 'failed') {
    importStep.value = 'upload'
    importPreview.value = null
    importResult.value = null
    importError.value = ''
    importNotice.value = ''
    importReviewSummary.value = ''
  }
}
function closeImportModal() {
  showImportModal.value = false
}
function openCharacterFromImport(name) {
  const matched = chars.characters.find(c => c.name === name)
  if (!matched) return
  closeImportModal()
  selectChar(matched)
}
function goToImportedConversation() {
  closeImportModal()
  router.push('/chat')
}
function openEditModal(c) {
  editingChar.value = c
  originalTraits = { ...(c.core_traits || {}) }
  charForm.value = {
    ...c,
    personality_tags_text: (c.personality_tags || []).join(', '),
    aliases_text: (c.aliases || []).join(', '),
    core_traits: normalizeFormTraits(c.core_traits),
    behavior_patterns: observations.value
      .filter(item => item.field === 'behavior_pattern' && item.status === 'approved')
      .map(item => ({ id:item.id, ...parseBehaviorPattern(item), new_value:item.new_value, localId:`existing-${item.id}` })),
  }
  showCharModal.value = true
}
function addBehaviorPatternForm() {
  charForm.value.behavior_patterns.push({
    localId: `new-${Date.now()}-${Math.random()}`,
    new_value: '',
    source: '手动编辑',
    confidence: 1,
    category: '互动策略',
    trigger: '',
    example: '',
  })
}
function removeBehaviorPatternForm(idx) {
  charForm.value.behavior_patterns.splice(idx, 1)
}
async function submitChar() {
  const personalityTags = (charForm.value.personality_tags_text || '')
    .split(/[,，]/)
    .map(item => item.trim())
    .filter(Boolean)

  const aliases = (charForm.value.aliases_text || '')
    .split(/[,，]/)
    .map(item => item.trim())
    .filter(Boolean)

  const payload = {
    name: charForm.value.name,
    aliases,
    role: charForm.value.role,
    background: charForm.value.background,
    age: charForm.value.age === '' ? null : charForm.value.age,
    avatar_color: charForm.value.avatar_color,
    motivation: charForm.value.motivation,
    weakness: charForm.value.weakness,
    speaking_style: charForm.value.speaking_style,
    personality_tags: personalityTags
  }

  if (editingChar.value) {
    // 大五增量提交：只发"原本就有值的维度 + 用户实际拖动过的维度"，
    // 避免默认 0.5 被固化成真实估值、之后污染 AI 融合
    const traitsPayload = {}
    for (const key of BIG_FIVE_KEYS) {
      const current = charForm.value.core_traits?.[key]
      const original = originalTraits[key]
      const hadValue = typeof original === 'number'
      const touched = typeof current === 'number' && (!hadValue ? current !== 0.5 : current !== original)
      if (hadValue || touched) traitsPayload[key] = current
    }
    if (Object.keys(traitsPayload).length) payload.core_traits = traitsPayload
    const updated = await chars.update(editingChar.value.id, payload)
    await syncBehaviorPatterns(editingChar.value.id)
    activeChar.value = updated
    await loadObservations(editingChar.value.id)
    await loadProfileView(editingChar.value.id)
    await loadAiUpdateSummary(editingChar.value.id)
    toast.success('角色已保存')
  } else {
    const created = await chars.create(payload)
    await syncBehaviorPatterns(created.id)
    selectChar(created)
    toast.success('角色已创建，AI 正在生成候选档案')
  }
  showCharModal.value = false
}

// ── AI 待确认建议（编辑弹窗内嵌） ────────────────────────────
const PROFILE_SUGGEST_FIELDS = ['role', 'background', 'motivation', 'weakness', 'speaking_style', 'personality_tags', 'core_traits']
const pendingProfileObs = computed(() =>
  observations.value.filter(o => o.status === 'pending' && PROFILE_SUGGEST_FIELDS.includes(o.field))
)
const PROFILE_FIELD_LABELS = {
  role: '角色定位', background: '背景故事', motivation: '核心动机',
  weakness: '核心弱点', speaking_style: '说话风格',
  personality_tags: '人格标签', core_traits: '大五人格',
}
function profileFieldLabel(field) { return PROFILE_FIELD_LABELS[field] || field }

async function adoptSuggestion(obs) {
  // 审核通过：后端直接写入角色档案，前端同步表单与视图
  await characterApi.reviewObservation(editingChar.value.id, obs.id, 'approved')
  const updated = await characterApi.get(editingChar.value.id)
  const char = updated.data
  activeChar.value = char
  const idx = chars.characters.findIndex(c => c.id === char.id)
  if (idx >= 0) chars.characters[idx] = char
  // 把已采纳的值同步进表单，避免随后"保存"用旧值覆盖
  if (obs.field === 'personality_tags') {
    charForm.value.personality_tags_text = (char.personality_tags || []).join(', ')
  } else if (obs.field === 'core_traits') {
    charForm.value.core_traits = { ...normalizeFormTraits(char.core_traits) }
  } else if (obs.field in charForm.value) {
    charForm.value[obs.field] = char[obs.field] || ''
  }
  await loadObservations(char.id)
  await loadProfileView(char.id)
  await loadAiUpdateSummary(char.id)
  toast.success('建议已采纳并写入档案')
}

async function dismissSuggestion(obs) {
  await characterApi.reviewObservation(editingChar.value.id, obs.id, 'rejected')
  await loadObservations(editingChar.value.id)
  await loadAiUpdateSummary(editingChar.value.id)
}
async function handleDelete(id) {
  if (!await confirmDialog('确定删除该角色？其档案、事件、关系与记忆将一并删除。')) return
  await chars.remove(id)
  activeChar.value = null
  toast.success('角色已删除')
}
async function handleSuggestUpdate() {
  if (!activeChar.value || loadingSuggest.value) return
  loadingSuggest.value = true
  try {
    await characterApi.suggestUpdate(activeChar.value.id)
    await loadObservations(activeChar.value.id)
    await loadAiUpdateSummary(activeChar.value.id)
  } finally {
    loadingSuggest.value = false
  }
}
async function reviewObs(obsId, status) {
  await characterApi.reviewObservation(activeChar.value.id, obsId, status)
  await loadObservations(activeChar.value.id)
  await loadAiUpdateSummary(activeChar.value.id)
  if (status === 'approved') {
    const updated = await characterApi.get(activeChar.value.id)
    activeChar.value = updated.data
    const idx = chars.characters.findIndex(c => c.id === activeChar.value.id)
    if (idx >= 0) chars.characters[idx] = updated.data
    await loadProfileView(activeChar.value.id)
  }
}
async function syncBehaviorPatterns(charId) {
  const existing = observations.value.filter(item => item.field === 'behavior_pattern' && item.status === 'approved')
  const existingMap = new Map(existing.map(item => [item.id, item]))
  const formPatterns = (charForm.value.behavior_patterns || [])
    .map(item => ({
      id: item.id,
      new_value: (item.new_value || '').trim(),
      source: item.source || '手动编辑',
      confidence: Number(item.confidence || 1),
      category: item.category || '互动策略',
      trigger: item.trigger || '',
      example: item.example || '',
    }))
    .filter(item => item.new_value)

  for (const pattern of formPatterns) {
    if (pattern.id && existingMap.has(pattern.id)) {
      await characterApi.updateBehaviorPattern(charId, pattern.id, pattern)
      existingMap.delete(pattern.id)
    } else {
      await characterApi.createBehaviorPattern(charId, pattern)
    }
  }
  for (const stale of existingMap.values()) {
    await characterApi.deleteBehaviorPattern(charId, stale.id)
  }
}

// ── Event Actions ─────────────────────────────────────────────────────────
async function submitEvent() {
  if (!eventForm.value.title.trim() || !activeChar.value) return
  await characterApi.createEvent(activeChar.value.id, { ...eventForm.value, character_id: activeChar.value.id })
  await loadEvents(activeChar.value.id)
  showEventModal.value = false
  eventForm.value = { title:'', description:'', event_date:'', emotion_label:'', importance:3 }
}
async function deleteEvent(eid) {
  await characterApi.deleteEvent(activeChar.value.id, eid)
  await loadEvents(activeChar.value.id)
  await loadProfileView(activeChar.value.id)
}

// ── Relationship Actions ───────────────────────────────────────────────────
function openEditRel(rel) {
  editingRel.value = rel
  relForm.value = { ...rel }
  showRelModal.value = true
}
async function submitRel() {
  if (editingRel.value) {
    await chars.updateRelationship(editingRel.value.id, {
      rel_type: relForm.value.rel_type,
      strength: relForm.value.strength,
      sentiment: relForm.value.sentiment,
      description: relForm.value.description,
    })
  } else {
    if (relForm.value.source_id === relForm.value.target_id) return
    await chars.createRelationship(relForm.value)
  }
  editingRel.value = null
  showRelModal.value = false
}
async function analyzeRel(id) {
  const res = await relationshipApi.analyze(id)
  relAnalysis.value = res.data
}

async function handleImportFileChange(e) {
  selectedImportFile.value = e.target.files?.[0] || null
  importPreview.value = null
  importResult.value = null
  importError.value = ''
  importNotice.value = ''
  importReviewSummary.value = ''
  importPreviewPending.value = false
  importStep.value = 'upload'
  previewTab.value = 'units'
  importPollCount = 0
  if (importPollTimer) window.clearTimeout(importPollTimer)
}
async function pollPreviewStatus(taskId) {
  if (!taskId) return
  if (importPollCount >= MAX_POLL_COUNT) {
    importPreviewPending.value = false
    importError.value = 'AI 预览增强超时，已显示基础预览结果，可直接确认导入。'
    return
  }
  try {
    const res = await characterApi.getImportStatus(taskId)
    const data = res.data || {}
    if (data.status === 'preview_processing') {
      importNotice.value = data.progress?.message || 'AI 预览增强正在后台处理中…'
      importPollCount++
      importPollTimer = window.setTimeout(() => pollPreviewStatus(taskId), getNextPollDelay(importPollCount))
      return
    }
    if (data.status === 'preview_ready') {
      importPreviewPending.value = false
      importPollCount = 0
      importPreview.value = data.preview_payload || importPreview.value
      importNotice.value = data.preview_warning || data.progress?.message || 'AI 预览增强完成'
      return
    }
    importPreviewPending.value = false
    importPollCount = 0
  } catch (err) {
    importPreviewPending.value = false
    importPollCount = 0
    importError.value = err?.response?.data?.detail || err?.message || '预览增强状态获取失败。'
  }
}
async function pollImportStatus(taskId) {
  if (!taskId) return
  if (importPollCount >= MAX_POLL_COUNT) {
    importTaskId.value = null
    importPollCount = 0
    importError.value = '导入任务超时，请查看后台日志确认状态。'
    importStep.value = 'failed'
    return
  }
  try {
    const res = await characterApi.getImportStatus(taskId)
    const data = res.data || {}
    if (data.status === 'queued' || data.status === 'reviewing' || data.status === 'processing') {
      importNotice.value = data.progress?.message || '导入任务正在后台处理中…'
      importPollCount++
      importPollTimer = window.setTimeout(() => pollImportStatus(taskId), getNextPollDelay(importPollCount))
      return
    }
    if (data.status === 'committed') {
      importTaskId.value = null
      importPollCount = 0
      importResult.value = data.result || null
      importReviewSummary.value = data.review_summary || ''
      importNotice.value = ''
      importStep.value = 'done'
      importCompletionNotice.value = `最近导入：角色 ${data.result?.created_characters?.length || 0} / 关系 ${data.relationship_count || data.result?.relationships || 0}`
      await chars.fetchAll()
      if (activeChar.value) {
        const refreshed = chars.characters.find(c => c.id === activeChar.value.id)
        if (refreshed) {
          activeChar.value = refreshed
          await loadEvents(refreshed.id)
          await loadObservations(refreshed.id)
          await loadProfileView(refreshed.id)
          await loadAiUpdateSummary(refreshed.id)
        }
      }
      return
    }
    importTaskId.value = null
    importPollCount = 0
    importError.value = data.progress?.message || '导入失败，请查看后台日志。'
    importStep.value = 'failed'
  } catch (err) {
    importTaskId.value = null
    importPollCount = 0
    importError.value = err?.response?.data?.detail || err?.message || '导入状态获取失败，请查看后台日志。'
    importStep.value = 'failed'
  }
}
async function previewImport() {
  if (!selectedImportFile.value || importLoading.value) return
  importLoading.value = true
  try {
    importError.value = ''
    importNotice.value = ''
    importPreviewPending.value = false
    const formData = new FormData()
    formData.append('file', selectedImportFile.value)
    const res = await characterApi.previewImport(formData)
    importPreview.value = res.data
    importOptions.value.self_name = ''   // 新预览：重置「我是谁」，由用户重新指定
    importResult.value = null
    importNotice.value = res.data?.warning_message || ''
    importPreviewPending.value = res.data?.preview_status === 'preview_processing'
    importTaskId.value = res.data?.import_file_id || null
    importStep.value = 'preview'
    // 资料型导入主要产出是人物事实，默认切到事实标签页
    previewTab.value = (res.data?.detected_type === 'profile_document' || (res.data?.persona_facts || []).length) ? 'facts' : 'units'
    if (importPreviewPending.value) {
      if (importPollTimer) window.clearTimeout(importPollTimer)
      importPollCount = 0
      importPollTimer = window.setTimeout(() => pollPreviewStatus(importTaskId.value), 2000)
    }
  } catch (err) {
    importPreview.value = null
    importResult.value = null
    importError.value = err?.response?.data?.detail || err?.message || '导入预览失败，请检查后端服务或文件内容。'
    importPreviewPending.value = false
    importStep.value = 'upload'
  } finally {
    importLoading.value = false
  }
}
async function commitImport() {
  if (!importPreview.value || importLoading.value) return
  importLoading.value = true
  try {
    importError.value = ''
    const res = await characterApi.commitImport({
      filename: selectedImportFile.value?.name || 'import.txt',
      file_type: importPreview.value.detected_type || 'dialogue',
      import_file_id: importPreview.value.import_file_id,
      scenario: importOptions.value.scenario,
      self_name: importOptions.value.self_name || '',
      create_readonly_conversation: importOptions.value.create_readonly_conversation,
      auto_archive: importOptions.value.auto_archive,
      preview_payload: importPreview.value,
      role_mappings: (importPreview.value.role_mappings || []).map(item => ({
        original_name: item.original_name,
        resolved_name: item.resolved_name,
        status: item.status,
        candidate_ids: item.candidate_ids || [],
        action: item.action,
      })),
    })
    importResult.value = null
    importTaskId.value = res.data?.import_file_id || null
    importNotice.value = res.data?.message || '导入任务已提交，后台处理中…'
    importCompletionNotice.value = ''
    // 不关闭弹窗：停留在"入库中"步骤，完成后直接展示结果页
    importStep.value = 'running'
    if (importPollTimer) window.clearTimeout(importPollTimer)
    importPollCount = 0
    importPollTimer = window.setTimeout(() => pollImportStatus(importTaskId.value), 2000)
  } catch (err) {
    importError.value = err?.response?.data?.detail || err?.message || '导入失败，请稍后重试。'
    importStep.value = 'failed'
  } finally {
    importLoading.value = false
  }
}
async function downloadExport() {
  try {
    importError.value = ''
    const res = await characterApi.exportAll()
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `btb-export-${new Date().toISOString().slice(0,19).replace(/[:T]/g, '-')}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    importError.value = err?.response?.data?.detail || err?.message || '导出失败，请稍后重试。'
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────
function getCharName(id) { return chars.characterMap[id]?.name || '未知' }
function getCharColor(id) { return chars.characterMap[id]?.avatar_color || '#475569' }
function getCharLetter(id) { return (chars.characterMap[id]?.name || '?')[0] }
function parseBehaviorPattern(obs) {
  // 新数据优先读结构化 metadata_json，老数据回退解析 reason 文本
  const meta = obs.metadata_json
  if (meta && meta.source) {
    return {
      source: meta.source || 'AI自动识别',
      confidence: String(meta.confidence ?? '1.00'),
      evidence: meta.evidence || '',
      category: meta.category || '互动策略',
      trigger: meta.trigger || '',
      example: meta.example || '',
    }
  }
  const lines = (obs.reason || '').split('\n').map(line => line.trim()).filter(Boolean)
  const getValue = (prefix) => (lines.find(line => line.startsWith(prefix)) || '').replace(prefix, '').trim()
  return {
    source: getValue('来源：') || 'AI自动识别',
    confidence: getValue('置信度：') || '1.00',
    evidence: getValue('依据：'),
    category: getValue('分类：') || '互动策略',
    trigger: getValue('触发：'),
    example: getValue('示例：'),
  }
}
function toggleBehaviorItem(key) {
  expandedBehaviorKeys.value = expandedBehaviorKeys.value.includes(key)
    ? expandedBehaviorKeys.value.filter(item => item !== key)
    : [...expandedBehaviorKeys.value, key]
}
function isBehaviorExpanded(key) {
  return expandedBehaviorKeys.value.includes(key)
}
function openAiUpdates() {
  if (!activeChar.value) return
  router.push({ path: '/ai-updates', query: { charId: activeChar.value.id } })
}

const traitLabels = { openness:'开放性', conscientiousness:'尽责性', extraversion:'外向性', agreeableness:'宜人性', neuroticism:'神经质' }
function traitLabel(k) { return traitLabels[k] || k }
function traitColor(v) { return v > 0.6 ? 'var(--cyan)' : v > 0.3 ? 'var(--amber)' : 'var(--red)' }
function completenessColor(score) { return score >= 75 ? 'var(--green)' : score >= 45 ? 'var(--amber)' : 'var(--red)' }
function importanceColor(i) { return ['#475569','#94a3b8','var(--amber)','#f97316','var(--red)'][Math.min(i,5)-1] }
const relTypeLabels = { ally:'盟友', rival:'对手', friend:'朋友', family:'家人', romantic:'恋人', neutral:'中立' }
function relTypeLabel(t) { return relTypeLabels[t] || t }
function trendLabel(t) { return { increasing:'上升', decreasing:'下降', stable:'稳定' }[t] || t }
function trendClass(t) { return { increasing:'green', decreasing:'red', stable:'amber' }[t] || '' }

// ── Force-directed Graph ───────────────────────────────────────────────────
function renderGraph() {
  const canvas = graphCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const W = canvas.offsetWidth
  const H = canvas.offsetHeight
  canvas.width = W
  canvas.height = H
  if (animFrame) cancelAnimationFrame(animFrame)

  const nodes = chars.characters.map((c, i) => ({
    id: c.id, label: c.name, color: c.avatar_color,
    x: W/2 + Math.cos(i * 2*Math.PI / chars.characters.length) * (Math.min(W,H) * 0.3),
    y: H/2 + Math.sin(i * 2*Math.PI / chars.characters.length) * (Math.min(W,H) * 0.3),
    vx: 0, vy: 0,
  }))
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]))
  const edges = chars.relationships.map(r => ({
    s: nodeMap[r.source_id], t: nodeMap[r.target_id],
    strength: r.strength, sentiment: r.sentiment, type: r.rel_type
  })).filter(e => e.s && e.t)

  function step() {
    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i+1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x
        const dy = nodes[j].y - nodes[i].y
        const dist = Math.sqrt(dx*dx + dy*dy) || 1
        const f = 3000 / (dist * dist)
        nodes[i].vx -= f * dx / dist; nodes[i].vy -= f * dy / dist
        nodes[j].vx += f * dx / dist; nodes[j].vy += f * dy / dist
      }
    }
    // Attraction (edges)
    for (const e of edges) {
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y
      const dist = Math.sqrt(dx*dx + dy*dy) || 1
      const f = (dist - 120) * 0.02 * e.strength
      e.s.vx += f * dx / dist; e.s.vy += f * dy / dist
      e.t.vx -= f * dx / dist; e.t.vy -= f * dy / dist
    }
    // Center pull
    for (const n of nodes) {
      n.vx += (W/2 - n.x) * 0.003; n.vy += (H/2 - n.y) * 0.003
      n.vx *= 0.85; n.vy *= 0.85
      n.x = Math.max(36, Math.min(W-36, n.x + n.vx))
      n.y = Math.max(36, Math.min(H-36, n.y + n.vy))
    }

    // Draw
    ctx.clearRect(0, 0, W, H)

    // Edges
    for (const e of edges) {
      const alpha = 0.3 + e.strength * 0.5
      const color = e.sentiment >= 0 ? `rgba(0,212,255,${alpha})` : `rgba(239,68,68,${alpha})`
      ctx.beginPath()
      ctx.moveTo(e.s.x, e.s.y)
      ctx.lineTo(e.t.x, e.t.y)
      ctx.strokeStyle = color
      ctx.lineWidth = 1 + e.strength * 3
      ctx.stroke()
      // Label at midpoint
      const mx = (e.s.x + e.t.x) / 2, my = (e.s.y + e.t.y) / 2
      ctx.fillStyle = 'rgba(148,163,184,0.7)'
      ctx.font = '10px IBM Plex Mono, monospace'
      ctx.textAlign = 'center'
      ctx.fillText(relTypeLabels[e.type] || e.type, mx, my - 5)
    }

    // Nodes
    for (const n of nodes) {
      // Glow
      const grad = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, 24)
      grad.addColorStop(0, n.color + 'aa')
      grad.addColorStop(1, n.color + '00')
      ctx.beginPath()
      ctx.arc(n.x, n.y, 24, 0, Math.PI*2)
      ctx.fillStyle = grad
      ctx.fill()
      // Circle
      ctx.beginPath()
      ctx.arc(n.x, n.y, 18, 0, Math.PI*2)
      ctx.fillStyle = n.color
      ctx.fill()
      // Active ring
      if (activeChar.value?.id === n.id) {
        ctx.beginPath()
        ctx.arc(n.x, n.y, 22, 0, Math.PI*2)
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 2
        ctx.stroke()
      }
      // Letter
      ctx.fillStyle = '#080c16'
      ctx.font = 'bold 13px Sora, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(n.label[0].toUpperCase(), n.x, n.y)
      // Name
      ctx.fillStyle = 'rgba(226,232,240,0.9)'
      ctx.font = '11px Sora, sans-serif'
      ctx.textBaseline = 'top'
      ctx.fillText(n.label, n.x, n.y + 22)
    }

    animFrame = requestAnimationFrame(step)
  }
  step()

  // Click detection
  canvas.onclick = (e) => {
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top
    for (const n of nodes) {
      const dx = mx - n.x, dy = my - n.y
      if (dx*dx + dy*dy < 18*18) {
        const c = chars.characters.find(c => c.id === n.id)
        if (c) selectChar(c)
        break
      }
    }
  }
}
</script>

<style scoped>
.admin-layout { display:flex; height:100vh; overflow:hidden; }

/* Char Panel */
.char-panel {
  width:220px; flex-shrink:0;
  background:var(--bg-surface);
  border-right:1px solid var(--border);
  display:flex; flex-direction:column;
}
.panel-header { padding:16px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
.panel-title { font-size:12px; font-family:var(--font-mono); color:var(--text-muted); text-transform:uppercase; letter-spacing:.08em; }
.count-badge { background:var(--cyan-dim); color:var(--cyan); border-radius:100px; padding:1px 7px; font-size:11px; }
.char-list { flex:1; overflow-y:auto; padding:8px; }
.char-item {
  display:flex; align-items:center; gap:10px;
  padding:10px 10px; border-radius:var(--radius-sm);
  cursor:pointer; transition:var(--transition); margin-bottom:2px;
}
.char-item:hover { background:var(--bg-hover); }
.char-item.active { background:var(--cyan-dim); border:1px solid rgba(0,212,255,.2); }
.char-avatar-sm { width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:#080c16; flex-shrink:0; }
.char-info { flex:1; min-width:0; }
.char-name { font-size:13px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.char-role { font-size:11px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.char-version { font-size:10px; font-family:var(--font-mono); color:var(--text-muted); }
.empty-hint { text-align:center; color:var(--text-muted); font-size:12px; padding:24px 0; }
.loading-state { display:flex; justify-content:center; padding:24px; }
.spinner { width:24px; height:24px; border:2px solid var(--border); border-top-color:var(--cyan); border-radius:50%; animation:spin 1s linear infinite; }
.import-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.import-card { padding:14px; }
.import-list { display:flex; flex-direction:column; gap:10px; max-height:320px; overflow:auto; }
.import-item { border:1px solid var(--border); background:var(--bg-elevated); border-radius:var(--radius-sm); padding:10px; }
.check-row { display:flex; gap:8px; align-items:center; font-size:12px; color:var(--text-secondary); }

/* 档案版本 */
.snapshot-row { display:flex; align-items:center; gap:10px; }

/* 立体人物模型 */
.extended-grid { display:flex; flex-direction:column; gap:14px; }
.ext-block { display:flex; flex-direction:column; gap:6px; }
.ext-label { font-size:11px; font-family:var(--font-mono); color:var(--cyan); letter-spacing:.04em; }
.ext-items { display:flex; flex-direction:column; gap:5px; }
.ext-item { font-size:13px; color:var(--text-secondary); line-height:1.6; padding-left:10px; border-left:2px solid var(--border); }

/* 进行中假设 */
.hypo-row { display:flex; align-items:center; gap:10px; }
.hypo-track { width:6px; height:32px; background:var(--bg-base); border-radius:3px; overflow:hidden; flex-shrink:0; display:flex; align-items:flex-end; }
.hypo-fill { width:100%; border-radius:3px; transition:height .4s; }
.hypo-body { flex:1; display:flex; flex-direction:column; gap:3px; min-width:0; }
.hypo-text { font-size:13px; color:var(--text-secondary); line-height:1.5; }
.hypo-conf { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); min-width:54px; text-align:right; }
.hypo-conf small { color:var(--green); margin-left:2px; }
.hypo-conf small.neg { color:var(--red); }

/* 关系深度 */
.rel-deep { margin-top:10px; padding-top:10px; border-top:1px solid var(--border); display:flex; flex-direction:column; gap:6px; }
.rel-deep-row { display:flex; gap:8px; font-size:12px; line-height:1.5; }
.rel-deep-k { color:var(--text-muted); font-family:var(--font-mono); font-size:11px; min-width:54px; flex-shrink:0; }
.rel-deep-row span:last-child { color:var(--text-secondary); }
.tl-impact { font-size:12px; color:var(--violet, #a78bfa); margin-top:6px; line-height:1.5; }
.arc-event { border-color:rgba(124,58,237,.4); }

/* 档案完整度 */
.completeness-row { display:flex; align-items:center; gap:8px; margin-top:10px; }
.completeness-track { width:120px; height:6px; background:var(--bg-base); border-radius:3px; overflow:hidden; }
.completeness-fill { height:100%; border-radius:3px; transition:width .4s; }
.completeness-text { font-size:11px; color:var(--text-secondary); font-family:var(--font-mono); }
.completeness-missing { font-size:11px; color:var(--text-muted); }

/* 编辑表单：大五滑条 + AI 建议卡 */
.form-traits { display:flex; flex-direction:column; gap:8px; }
.form-trait-row { display:flex; align-items:center; gap:10px; }
.form-trait-row .trait-name { min-width:48px; font-size:12px; color:var(--text-secondary); }
.form-trait-row .trait-val { min-width:28px; text-align:right; font-size:11px; font-family:var(--font-mono); color:var(--text-muted); }
.suggest-card { padding:10px 12px; border:1px solid rgba(124,58,237,.3); background:rgba(124,58,237,.06); }

/* 导入向导步骤 */
.import-steps { display:flex; gap:6px; align-items:center; margin-left:auto; margin-right:14px; }
.import-steps .step {
  font-size:11px; font-family:var(--font-mono); color:var(--text-muted);
  padding:3px 10px; border-radius:100px; border:1px solid var(--border);
}
.import-steps .step.active { color:var(--cyan); border-color:var(--cyan); background:var(--cyan-dim); }
.import-steps .step.done { color:var(--green); border-color:rgba(16,185,129,.35); }

/* 统计条 */
.import-stats { display:flex; gap:8px; flex-wrap:wrap; }
.stat-chip {
  font-size:12px; color:var(--text-secondary);
  border:1px solid var(--border); background:var(--bg-elevated);
  border-radius:8px; padding:6px 12px;
}
.stat-chip b { color:var(--text-primary); font-family:var(--font-mono); margin-left:2px; }
.stat-chip.green { border-color:rgba(16,185,129,.35); }
.stat-chip.green b { color:var(--green); }
.stat-chip.amber { border-color:rgba(245,158,11,.4); }
.stat-chip.amber b { color:var(--amber); }

/* 内容预览标签页 */
.preview-tabs { display:flex; gap:4px; margin-bottom:10px; }
.ptab {
  background:transparent; border:1px solid var(--border); border-radius:6px;
  color:var(--text-muted); font-size:12px; padding:4px 12px; cursor:pointer;
  transition:var(--transition);
}
.ptab.active { color:var(--cyan); border-color:var(--cyan); background:var(--cyan-dim); }

/* 入库进行中 / 完成 */
.import-running { display:flex; flex-direction:column; align-items:center; gap:12px; padding:36px 0; }
.running-title { font-size:16px; font-weight:600; color:var(--text-primary); text-align:center; }
.done-icon {
  width:42px; height:42px; border-radius:50%; flex-shrink:0;
  display:flex; align-items:center; justify-content:center;
  background:rgba(16,185,129,.12); color:var(--green);
  font-size:20px; font-weight:700; border:1px solid rgba(16,185,129,.4);
}
.done-icon.failed { background:rgba(239,68,68,.12); color:var(--red); border-color:rgba(239,68,68,.4); }
.import-done-head { display:flex; gap:14px; align-items:center; }
.tag-btn { cursor:pointer; transition:var(--transition); }
.tag-btn:hover { border-color:var(--cyan); color:var(--cyan); }

/* Detail Panel */
.detail-panel { flex:1; overflow:hidden; display:flex; flex-direction:column; min-width:0; border-right:1px solid var(--border); }
.no-select { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; opacity:.5; }
.ns-icon { font-size:48px; color:var(--cyan); margin-bottom:12px; }
.ns-title { font-size:16px; font-weight:600; }
.ns-desc { font-size:12px; color:var(--text-muted); margin-top:6px; }

.detail-tabs { display:flex; border-bottom:1px solid var(--border); padding:0 20px; flex-shrink:0; }
.tab-btn { padding:14px 16px; font-size:13px; background:transparent; border:none; color:var(--text-muted); cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-1px; transition:var(--transition); }
.tab-btn.active { color:var(--cyan); border-bottom-color:var(--cyan); }
.tab-btn:hover { color:var(--text-primary); }
.tab-content { flex:1; overflow-y:auto; padding:20px; }

/* Profile */
.profile-header { display:flex; align-items:flex-start; gap:16px; margin-bottom:24px; }
.big-avatar { width:60px; height:60px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:24px; font-weight:700; color:#080c16; flex-shrink:0; }
.profile-meta { flex:1; }
.profile-name { font-size:20px; font-weight:700; }
.profile-role { font-size:13px; color:var(--text-muted); margin-top:2px; }
.profile-actions { display:flex; flex-direction:column; gap:6px; }

.section { margin-bottom:24px; }
.section-title { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); text-transform:uppercase; letter-spacing:.08em; margin-bottom:12px; display:flex; align-items:center; gap:8px; }

.traits-grid { display:flex; flex-direction:column; gap:8px; }
.trait-row { display:flex; align-items:center; gap:10px; }
.trait-name { font-size:12px; color:var(--text-secondary); min-width:60px; }
.trait-bar-track { flex:1; height:6px; background:var(--bg-base); border-radius:3px; overflow:hidden; }
.trait-bar-fill { height:100%; border-radius:3px; transition:width .6s cubic-bezier(.4,0,.2,1); }
.trait-val { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); min-width:28px; text-align:right; }

.info-grid { display:flex; flex-direction:column; gap:12px; }
.info-item { background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px 14px; }
.info-label { font-size:10px; font-family:var(--font-mono); color:var(--text-muted); text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px; }
.info-value { font-size:13px; color:var(--text-secondary); line-height:1.6; }
.section-card { padding:14px; font-size:13px; color:var(--text-secondary); line-height:1.7; }
.behavior-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; }
.behavior-group { padding:12px; }
.behavior-tag-btn { border:none; cursor:pointer; }
.compact-list { display:flex; flex-direction:column; gap:8px; }
.update-summary-card { display:flex; align-items:center; justify-content:space-between; gap:12px; }

/* Observations */
.obs-list { display:flex; flex-direction:column; gap:8px; }
.obs-item { padding:12px 14px; border-radius:var(--radius-sm); border:1px solid var(--border); background:var(--bg-elevated); }
.obs-item.approved { border-color:rgba(16,185,129,.3); }
.obs-item.rejected { opacity:.5; }
.obs-field { font-size:10px; font-family:var(--font-mono); color:var(--text-muted); text-transform:uppercase; margin-bottom:6px; }
.obs-diff { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
.obs-old { font-size:12px; color:var(--red); text-decoration:line-through; }
.obs-new { font-size:12px; color:var(--green); }
.obs-reason { font-size:11px; color:var(--text-muted); line-height:1.5; margin-bottom:8px; }
.obs-actions { display:flex; gap:6px; }

/* Timeline */
.timeline-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
.timeline { display:flex; flex-direction:column; gap:0; position:relative; padding-left:24px; }
.timeline-item { display:flex; gap:14px; position:relative; padding-bottom:20px; }
.tl-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; margin-top:14px; position:absolute; left:-19px; }
.tl-line { position:absolute; left:-15px; top:24px; bottom:0; width:1px; background:var(--border); }
.tl-body { flex:1; padding:12px 14px; }
.tl-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px; }
.tl-title { font-size:13px; font-weight:600; }
.tl-date { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); }
.tl-desc { font-size:12px; color:var(--text-secondary); line-height:1.6; }
.importance-dots { display:flex; gap:4px; margin-top:8px; }
.imp-dot { width:6px; height:6px; border-radius:50%; background:var(--border); }
.imp-dot.filled { background:var(--cyan); }
.del-btn { background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:11px; padding:2px; }
.del-btn:hover { color:var(--red); }

/* Relationships */
.rel-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }
.rel-list { display:flex; flex-direction:column; gap:10px; }
.rel-card { padding:14px; }
.rel-parties { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
.rel-char { display:flex; align-items:center; gap:6px; font-size:13px; }
.rel-type-badge { padding:3px 12px; border-radius:100px; font-size:11px; font-family:var(--font-mono); background:var(--cyan-dim); color:var(--cyan); border:1px solid rgba(0,212,255,.2); }
.rel-metrics { display:flex; flex-direction:column; gap:6px; }
.rel-metric { display:flex; align-items:center; gap:8px; }
.rel-m-label { font-size:11px; color:var(--text-muted); min-width:56px; font-family:var(--font-mono); }
.mini-bar { flex:1; height:4px; background:var(--bg-base); border-radius:2px; overflow:hidden; }
.mini-fill { height:100%; border-radius:2px; transition:width .4s; }
.rel-m-val { font-size:11px; font-family:var(--font-mono); color:var(--text-muted); min-width:30px; text-align:right; }

/* Graph Panel */
.graph-panel { width:320px; flex-shrink:0; display:flex; flex-direction:column; background:var(--bg-surface); position:relative; }
.graph-canvas { flex:1; cursor:pointer; display:block; }
.graph-empty { position:absolute; inset:60px 0 0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.rel-analysis { position:absolute; bottom:16px; left:12px; right:12px; padding:12px 14px; }

/* Modal */
.modal-overlay { position:fixed; inset:0; background:rgba(8,12,22,.75); backdrop-filter:blur(4px); z-index:1000; display:flex; align-items:center; justify-content:center; }
.modal { padding:0; }
.modal-header { padding:18px 20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; font-size:15px; font-weight:600; }
.btn-close { background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:16px; }
.btn-close:hover { color:var(--text-primary); }

.loading { opacity:.6; pointer-events:none; }
</style>
