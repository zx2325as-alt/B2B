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
            </div>
            <div class="profile-actions">
              <button class="btn btn-ghost" @click="openEditModal(activeChar)">编辑</button>
              <button class="btn btn-ghost" @click="handleSuggestUpdate" :class="{ loading: loadingSuggest }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
                AI 建议
              </button>
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
              <div class="tl-dot" :style="{ background: importanceColor(ev.importance) }"></div>
              <div class="tl-line"></div>
              <div class="tl-body card">
                <div class="tl-top">
                  <span class="tl-title">{{ ev.title }}</span>
                  <div style="display:flex;gap:6px;align-items:center">
                    <span v-if="ev.emotion_label" class="tag" style="font-size:10px">{{ ev.emotion_label }}</span>
                    <span class="tl-date">{{ ev.event_date }}</span>
                    <button class="del-btn" @click="deleteEvent(ev.id)">✕</button>
                  </div>
                </div>
                <div class="tl-desc">{{ ev.description }}</div>
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
        <div class="modal card fade-up" style="width:980px;max-height:88vh;overflow-y:auto">
          <div class="modal-header">
            <span>统一智能导入 / 导出</span>
            <button class="btn-close" @click="showImportModal = false">✕</button>
          </div>
          <div style="padding:20px;display:flex;flex-direction:column;gap:18px">
            <div class="section" style="margin-bottom:0">
              <div class="section-title">文件入口</div>
              <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                <input ref="importFileInput" type="file" class="input" accept=".txt,.md,.pdf,.docx,.json,.csv" style="max-width:340px" @change="handleImportFileChange"/>
                <button type="button" class="btn btn-primary" :disabled="!selectedImportFile || importLoading" @click.prevent="previewImport">
                  {{ importLoading ? '解析中…' : (importPreviewPending ? 'AI增强处理中…' : '上传并预览') }}
                </button>
                <button type="button" class="btn btn-ghost" @click.prevent="downloadExport">导出全量 JSON</button>
              </div>
              <div v-if="importError" class="tag red" style="width:fit-content">{{ importError }}</div>
              <div v-else-if="importNotice" class="tag amber" style="width:fit-content">{{ importNotice }}</div>
              <div class="empty-hint" style="padding:8px 0 0;text-align:left">支持 TXT / MD / PDF / DOCX / JSON / CSV，统一进入 AI Harness 语义解析链路。</div>
            </div>

            <template v-if="importPreview">
              <div class="import-grid">
                <div class="card import-card">
                  <div class="section-title">角色预览</div>
                  <div v-if="!importPreview.role_mappings?.length" class="empty-hint">暂无角色</div>
                  <div v-else class="import-list">
                    <div v-for="mapping in importPreview.role_mappings" :key="mapping.original_name" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>{{ mapping.original_name }}</strong>
                        <span class="tag" :class="mapping.status === 'confirmed' ? 'green' : mapping.status === 'ambiguous' ? 'amber' : 'violet'">{{ mapping.status }}</span>
                      </div>
                      <div style="display:grid;grid-template-columns:1fr 100px;gap:8px;margin-top:8px">
                        <input class="input" v-model="mapping.resolved_name" placeholder="确认名称 / 合并名称"/>
                        <select class="input" v-model="mapping.action">
                          <option value="create">新建</option>
                          <option value="link">映射</option>
                          <option value="skip">跳过</option>
                        </select>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="card import-card">
                  <div class="section-title">心理语义预览</div>
                  <div v-if="!importPreview.interaction_units?.length" class="empty-hint">暂无交互单元</div>
                  <div v-else class="import-list">
                    <div v-for="(unit, idx) in importPreview.interaction_units.slice(0, 12)" :key="`${unit.speaker}-${idx}`" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>{{ unit.speaker }} → {{ unit.receiver || '待推断' }}</strong>
                        <span class="tag" :class="unit.receiver_confidence >= 0.6 ? 'green' : 'amber'">{{ Math.round((unit.receiver_confidence || 0) * 100) }}%</span>
                      </div>
                      <div class="obs-reason" style="margin-top:6px">{{ unit.content }}</div>
                      <div v-if="unit.psychological_label" class="tag violet" style="margin-top:8px;width:fit-content">{{ unit.psychological_label }}</div>
                      <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-top:8px">
                        <input class="input" v-model="unit.intent.value" placeholder="编辑意图"/>
                        <input class="input" v-model="unit.strategy.value" placeholder="编辑策略"/>
                        <input class="input" v-model="unit.emotion.value" placeholder="编辑情绪"/>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="import-grid">
                <div class="card import-card">
                  <div class="section-title">事件 / 关系 / 剧情结构</div>
                  <div class="import-list">
                    <div class="import-item">
                      <div><strong>导入版本</strong> v{{ importPreview.import_version?.version || 1 }}</div>
                      <div><strong>事件数</strong> {{ importPreview.events?.length || 0 }}</div>
                      <div><strong>关系数</strong> {{ importPreview.relationships?.length || 0 }}</div>
                      <div><strong>低置信交互</strong> {{ importPreview.low_confidence_units?.length || 0 }}</div>
                    </div>
                    <div class="import-item">
                      <div class="obs-field">主冲突</div>
                      <div class="obs-reason">{{ importPreview.plot_summary?.main_conflict || '暂无' }}</div>
                    </div>
                    <div class="import-item">
                      <div class="obs-field">关系演化</div>
                      <div class="obs-reason">{{ importPreview.plot_summary?.relationship_path || '暂无' }}</div>
                    </div>
                    <div class="import-item">
                      <div class="obs-field">关键转折</div>
                      <div class="obs-reason">{{ (importPreview.plot_summary?.turning_points || []).join(' / ') || '暂无' }}</div>
                    </div>
                  </div>
                </div>

                <div class="card import-card">
                  <div class="section-title">关系预览</div>
                  <div v-if="!importPreview.relationships?.length" class="empty-hint">暂无关系</div>
                  <div v-else class="import-list">
                    <div v-for="(rel, idx) in importPreview.relationships.slice(0, 10)" :key="`rel-${idx}`" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>{{ rel.source }} → {{ rel.target }}</strong>
                        <span class="tag">{{ rel.rel_type || 'neutral' }}</span>
                      </div>
                      <div class="obs-reason" style="margin-top:6px">{{ rel.description || '暂无关系说明' }}</div>
                      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
                        <span class="tag">强度 {{ Math.round((rel.strength || 0) * 100) }}%</span>
                        <span class="tag">极性 {{ ((rel.sentiment || 0) > 0 ? '+' : '') + Number(rel.sentiment || 0).toFixed(2) }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="card import-card">
                  <div class="section-title">写入选项</div>
                  <div style="display:flex;flex-direction:column;gap:10px">
                    <div class="tag violet" style="width:fit-content">AI 审核代理会自动审核并后台入库</div>
                    <label class="check-row"><input type="checkbox" v-model="importOptions.create_readonly_conversation"/> 创建只读会话并接入页面1</label>
                    <label class="check-row"><input type="checkbox" v-model="importOptions.auto_archive"/> 导入后自动进入归档/关系更新流程</label>
                    <select class="input" v-model="importOptions.scenario">
                      <option value="general">通用对话</option>
                      <option value="bar_chat">老友酒吧闲聊</option>
                      <option value="business">商务谈判</option>
                      <option value="hr_interview">HR面试</option>
                      <option value="counseling">心理咨询</option>
                    </select>
                    <button type="button" class="btn btn-primary" :disabled="importLoading || importPreviewPending" @click.prevent="commitImport">
                      {{ importLoading ? '导入中…' : (importPreviewPending ? '等待 AI 预览增强完成…' : '确认导入并写入系统') }}
                    </button>
                    <div v-if="importResult" class="obs-reason">导入完成：角色 {{ importResult.created_characters?.length || 0 }} / 交互 {{ importResult.interaction_units || 0 }} / 关系 {{ importResult.relationships || 0 }}</div>
                  </div>
                </div>
              </div>

              <div class="import-grid">
                <div class="card import-card">
                  <div class="section-title">伪对话上下文</div>
                  <div v-if="!importPreview.pseudo_conversation?.messages?.length" class="empty-hint">暂无伪对话流</div>
                  <div v-else class="import-list">
                    <div v-for="item in importPreview.pseudo_conversation.messages.slice(0, 10)" :key="`pseudo-${item.message_index}`" class="import-item">
                      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
                        <strong>#{{ item.message_index }} {{ item.speaker }} → {{ item.receiver || '待推断' }}</strong>
                        <span class="tag" :class="(item.receiver_confidence || 0) >= 0.6 ? 'green' : 'amber'">{{ Math.round((item.receiver_confidence || 0) * 100) }}%</span>
                      </div>
                      <div class="obs-reason" style="margin-top:6px">{{ item.content }}</div>
                      <div class="obs-field" style="margin-top:8px">上下文窗口</div>
                      <div class="obs-reason">{{ (item.context_window || []).map(ctx => `#${ctx.message_index} ${ctx.speaker}→${ctx.receiver || '待推断'}: ${ctx.content}`).join(' / ') || '无' }}</div>
                    </div>
                  </div>
                </div>

                <div class="card import-card">
                  <div class="section-title">角色档案预览（8模块）</div>
                  <div v-if="!Object.keys(importPreview.character_profiles || {}).length" class="empty-hint">暂无角色档案结果</div>
                  <div v-else class="import-list">
                    <div v-for="(profile, name) in importPreview.character_profiles" :key="`model-${name}`" class="import-item">
                      <strong>{{ name }}</strong>
                      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
                        <span v-for="trait in profile.personality_model?.tags || []" :key="`${name}-trait-${trait}`" class="tag green">{{ trait }}</span>
                      </div>
                      <div class="obs-reason" style="margin-top:8px">核心动机：{{ profile.core_motivation || 'null' }}</div>
                      <div class="obs-reason">核心弱点：{{ profile.core_weakness || 'null' }}</div>
                      <div class="obs-reason">说话风格：{{ profile.speaking_style?.summary || 'null' }}</div>
                      <div class="obs-reason">关系网络：{{ (profile.relationship_network || []).length }} 条</div>
                      <div class="obs-reason">事件时间线：{{ (profile.event_timeline || []).length }} 条</div>
                      <div class="obs-field" style="margin-top:8px">行为模式</div>
                      <div v-for="(items, category) in profile.behavior_patterns || {}" :key="`${name}-${category}`" class="obs-reason">
                        {{ category }}：{{ (items || []).map(item => item.label).join(' / ') || 'null' }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
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
const importOptions = ref({
  scenario: 'general',
  create_readonly_conversation: false,
  auto_archive: true,
})
let importPollTimer = null

const showCharModal = ref(false)
const showRelModal = ref(false)
const showEventModal = ref(false)
const editingChar = ref(null)
const editingRel = ref(null)

const graphCanvas = ref(null)
let animFrame = null
const expandedBehaviorKeys = ref([])

const tabs = [
  { key: 'profile', label: '角色档案' },
  { key: 'timeline', label: '时间线' },
  { key: 'relations', label: '关系' },
]

const charForm = ref({ name:'', role:'', background:'', age:null, avatar_color:'#00d4ff', motivation:'', weakness:'', speaking_style:'', personality_tags_text:'', behavior_patterns:[] })
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
  charForm.value = { name:'', role:'', background:'', age:null, avatar_color:'#00d4ff', motivation:'', weakness:'', speaking_style:'', personality_tags_text:'', behavior_patterns:[] }
  showCharModal.value = true
}
function openImportModal() {
  showImportModal.value = true
}
function closeImportModal() {
  showImportModal.value = false
}
function openEditModal(c) {
  editingChar.value = c
  charForm.value = {
    ...c,
    personality_tags_text: (c.personality_tags || []).join(', '),
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
    
  const payload = {
    name: charForm.value.name,
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
    const updated = await chars.update(editingChar.value.id, payload)
    await syncBehaviorPatterns(editingChar.value.id)
    activeChar.value = updated
    await loadObservations(editingChar.value.id)
    await loadProfileView(editingChar.value.id)
    await loadAiUpdateSummary(editingChar.value.id)
  } else {
    const created = await chars.create(payload)
    await syncBehaviorPatterns(created.id)
    selectChar(created)
  }
  showCharModal.value = false
}
async function handleDelete(id) {
  if (!confirm('确定删除该角色？')) return
  await chars.remove(id)
  activeChar.value = null
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
  importPreviewPending.value = false
}
async function pollPreviewStatus(taskId) {
  if (!taskId) return
  try {
    const res = await characterApi.getImportStatus(taskId)
    const data = res.data || {}
    if (data.status === 'preview_processing') {
      importNotice.value = data.progress?.message || 'AI 预览增强正在后台处理中…'
      importPollTimer = window.setTimeout(() => pollPreviewStatus(taskId), 1500)
      return
    }
    if (data.status === 'preview_ready') {
      importPreviewPending.value = false
      importPreview.value = data.preview_payload || importPreview.value
      importNotice.value = data.preview_warning || data.progress?.message || 'AI 预览增强完成'
      return
    }
    importPreviewPending.value = false
  } catch (err) {
    importPreviewPending.value = false
    importError.value = err?.response?.data?.detail || err?.message || '预览增强状态获取失败。'
  }
}
async function pollImportStatus(taskId) {
  if (!taskId) return
  try {
    const res = await characterApi.getImportStatus(taskId)
    const data = res.data || {}
    if (data.status === 'queued' || data.status === 'reviewing' || data.status === 'processing') {
      importNotice.value = data.progress?.message || '导入任务正在后台处理中…'
      importPollTimer = window.setTimeout(() => pollImportStatus(taskId), 1500)
      return
    }
    if (data.status === 'committed') {
      importTaskId.value = null
      importResult.value = data.result || null
      importNotice.value = data.progress?.message || '导入完成'
      importCompletionNotice.value = `导入完成：关系 ${data.relationship_count || data.result?.relationships || 0}`
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
    importError.value = data.progress?.message || '导入失败，请查看后台日志。'
  } catch (err) {
    importTaskId.value = null
    importError.value = err?.response?.data?.detail || err?.message || '导入状态获取失败，请查看后台日志。'
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
    importResult.value = null
    importNotice.value = res.data?.warning_message || ''
    importPreviewPending.value = res.data?.preview_status === 'preview_processing'
    importTaskId.value = res.data?.import_file_id || null
    if (importPreviewPending.value) {
      if (importPollTimer) window.clearTimeout(importPollTimer)
      importPollTimer = window.setTimeout(() => pollPreviewStatus(importTaskId.value), 600)
    }
  } catch (err) {
    importPreview.value = null
    importResult.value = null
    importError.value = err?.response?.data?.detail || err?.message || '导入预览失败，请检查后端服务或文件内容。'
    importPreviewPending.value = false
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
    closeImportModal()
    if (importPollTimer) window.clearTimeout(importPollTimer)
    importPollTimer = window.setTimeout(() => pollImportStatus(importTaskId.value), 600)
  } catch (err) {
    importError.value = err?.response?.data?.detail || err?.message || '导入失败，请稍后重试。'
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
