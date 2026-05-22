<template>
  <div class="p-4 max-w-4xl mx-auto w-full">

    <!-- Header -->
    <div class="mb-4">
      <h1 class="page-title">Health</h1>
      <p class="page-subtitle">AI-powered app diagnostics and auto-healing</p>
    </div>

    <!-- Status bar: scheduler + LLM + stats — all one compact row -->
    <div class="card mb-4">
      <div class="card-body !py-2.5 flex items-center gap-4 flex-wrap">

        <!-- Scheduler -->
        <div class="flex items-center gap-2 shrink-0">
          <span :class="['w-2 h-2 rounded-full shrink-0',
            schedulerStatus?.running ? 'bg-green-400' : 'bg-slate-300']"/>
          <span class="text-xs text-slate-600 font-medium">
            {{ schedulerStatus?.running ? 'Scheduler running' : 'Scheduler stopped' }}
          </span>
          <span v-if="schedulerStatus?.last_cycle_ago" class="text-xs text-slate-400">
            · {{ schedulerStatus.last_cycle_ago }}
          </span>
        </div>

        <span class="text-slate-200 hidden sm:block">|</span>

        <!-- LLM agent -->
        <div v-if="llmStatus" class="flex items-center gap-2 shrink-0">
          <span class="text-xs text-slate-500">🤖</span>
          <span class="text-xs text-slate-600 font-medium capitalize">
            {{ llmStatus.configured_provider || 'AI' }}
          </span>
          <span :class="['badge text-xs',
            llmStatus.status === 'active' ? 'badge-green' :
            llmStatus.status === 'degraded' ? 'badge-yellow' :
            llmStatus.status === 'offline' ? 'badge-red' : 'badge-gray']">
            {{ llmStatus.status }}
          </span>
          <span v-if="llmStatus.status === 'offline'" class="text-xs text-slate-400"
            :title="llmStatus.description">
            — {{ llmStatus.last_error_type === 'dns' ? 'not installed' :
                llmStatus.last_error_type === 'auth' ? 'bad API key' :
                llmStatus.last_error_type || 'check settings' }}
          </span>
        </div>
        <div v-else-if="llmInactive" class="flex items-center gap-1.5 shrink-0">
          <span class="text-xs text-slate-500">🤖</span>
          <span class="text-xs text-amber-600">AI inactive — install Ollama or add a cloud key in Settings → AI</span>
        </div>

        <!-- Stats -->
        <div class="flex items-center gap-3 ml-auto shrink-0">
          <span class="text-xs font-medium text-green-600">✓ {{ counts.ok }} healthy</span>
          <span v-if="counts.warning" class="text-xs font-medium text-amber-500">⚠ {{ counts.warning }} warning</span>
          <span v-if="counts.error" class="text-xs font-medium text-red-500">✗ {{ counts.error }} error</span>
          <button v-if="!running" @click="runCycle"
            class="text-xs text-sky-500 hover:text-sky-600 font-medium">
            {{ checks.length ? '↻ Run now' : '▶ Run first check' }}
          </button>
          <span v-if="running" class="flex items-center gap-1.5 text-xs text-slate-500">
            <span class="inline-block w-2.5 h-2.5 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin"/>
            Checking…
          </span>
          <RouterLink to="/settings?tab=health" class="text-xs text-slate-400 hover:text-slate-600">⚙</RouterLink>
        </div>
      </div>
    </div>

    <!-- AI Suggested Fixes — highest priority, show first -->
    <div v-if="pendingFixes.length" class="mb-4">
      <div class="flex items-center justify-between mb-2">
        <h2 class="section-label">AI suggested fixes
          <span class="text-slate-300 font-normal ml-1">· {{ pendingFixes.length }} pending</span>
        </h2>
        <button @click="loadPendingFixes" class="text-xs text-slate-400 hover:text-slate-600">↻</button>
      </div>
      <div class="space-y-2">
        <div v-for="fix in pendingFixes" :key="fix.id"
          class="card card-body !py-3 border-l-2 border-l-violet-400">
          <div class="flex items-start gap-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap mb-1">
                <span class="text-sm font-medium text-slate-900">{{ fix.app_key }}</span>
                <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{{ fix.check_name }}</span>
                <span :class="['text-xs px-1.5 py-0.5 rounded font-medium', actionColor(fix.action_type)]">
                  {{ fix.action_type.replace(/_/g, ' ') }}
                </span>
                <span :class="['text-xs px-1.5 py-0.5 rounded',
                  fix.confidence >= 0.7 ? 'bg-green-100 text-green-700' :
                  fix.confidence >= 0.4 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500']">
                  {{ Math.round(fix.confidence * 100) }}%
                </span>
              </div>
              <p class="text-xs text-slate-600 mb-1">{{ fix.problem }}</p>
              <div class="flex items-start gap-1.5">
                <span class="text-xs text-slate-400 shrink-0 mt-0.5">Fix:</span>
                <code class="text-xs font-mono bg-slate-50 border border-slate-200 rounded px-2 py-0.5 text-slate-700 flex-1 leading-relaxed">
                  {{ fix.suggested_fix }}
                </code>
              </div>
              <div class="flex items-center gap-2 mt-1">
                <span class="text-xs text-slate-400">{{ formatAge(fix.created_at) }}</span>
                <span v-if="fix.model" class="text-xs text-slate-400 font-mono">· {{ fix.model }}</span>
              </div>
            </div>
            <div class="flex flex-col gap-1.5 shrink-0">
              <button @click="approveFix(fix)" :disabled="approvingFix === fix.id"
                class="btn-primary btn-sm text-xs">
                {{ approvingFix === fix.id ? 'Applying…' : '✓ Approve' }}
              </button>
              <button @click="escalateFix(fix)" :disabled="escalatingFix === fix.id"
                class="btn-secondary btn-sm text-xs"
                title="Ask a cloud LLM for a more thorough diagnosis">
                {{ escalatingFix === fix.id ? '…' : '☁ Escalate' }}
              </button>
              <button @click="rejectFix(fix)" class="btn-secondary btn-sm text-xs text-red-500">
                ✕ Reject
              </button>
            </div>
          </div>
          <!-- Escalation result -->
          <div v-if="escalationResults[fix.id]" class="mt-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs font-medium text-sky-700">☁ Cloud diagnosis</span>
              <span v-if="escalationResults[fix.id].escalated_to"
                class="text-xs text-sky-500 font-mono">via {{ escalationResults[fix.id].escalated_to }}</span>
            </div>
            <p class="text-xs text-slate-700 mb-1">{{ escalationResults[fix.id].root_cause }}</p>
            <code class="text-xs font-mono bg-white border border-sky-200 rounded px-2 py-0.5 text-slate-700 block">
              {{ escalationResults[fix.id].suggested_fix }}
            </code>
            <button @click="approveEscalated(fix, escalationResults[fix.id])"
              class="btn-primary btn-sm text-xs mt-2">Apply cloud fix</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Manual command -->
    <div v-if="manualCommand" class="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <div class="flex items-start justify-between gap-2">
        <div class="flex-1">
          <p class="text-xs font-semibold text-amber-800 mb-1.5">⚙ Run this command on your server:</p>
          <code class="block text-xs font-mono bg-white border border-amber-200 rounded px-3 py-2 text-slate-800 select-all leading-relaxed whitespace-pre-wrap">
            {{ manualCommand.command }}
          </code>
        </div>
        <button @click="manualCommand = null" class="text-amber-400 hover:text-amber-600 shrink-0 text-lg">✕</button>
      </div>
    </div>

    <!-- Recurring issues -->
    <div v-if="anomalies.length" class="mb-4">
      <h2 class="section-label mb-2">Recurring issues
        <span class="text-slate-300 font-normal ml-1">· {{ anomalies.length }} pattern{{ anomalies.length > 1 ? 's' : '' }} detected</span>
      </h2>
      <div class="space-y-2">
        <div v-for="a in anomalies" :key="a.app_key + a.check_name"
          :class="['card card-body !py-2.5 border-l-2',
            a.is_recurring ? 'border-l-red-400' : 'border-l-amber-400']">
          <div class="flex items-center gap-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span :class="['text-sm font-medium', a.is_recurring ? 'text-red-800' : 'text-amber-800']">
                  {{ a.app_key }}
                </span>
                <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{{ a.check_name }}</span>
                <span :class="['text-xs font-medium px-2 py-0.5 rounded-full',
                  a.is_recurring ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700']">
                  {{ a.occurrences }}×
                </span>
              </div>
              <p :class="['text-xs mt-0.5', a.is_recurring ? 'text-red-600' : 'text-amber-600']">{{ a.description }}</p>
              <div v-if="a.can_schedule" class="text-xs text-slate-500 mt-1">
                📅 Looks scheduled (~{{ a.typical_hour }}:00 UTC).
                <button @click="createMaintenanceWindow(a)"
                  class="text-sky-600 hover:text-sky-800 font-medium ml-1">Mark as scheduled →</button>
              </div>
            </div>
            <button @click="snoozeAnomaly(a)"
              class="text-xs text-slate-400 hover:text-slate-600 shrink-0">Snooze 72h</button>
          </div>
        </div>
        <!-- Maintenance windows -->
        <div v-if="maintenanceWindows.length" class="pt-2 border-t border-slate-100">
          <div class="text-xs font-medium text-slate-500 mb-1.5">Scheduled maintenance</div>
          <div class="space-y-1">
            <div v-for="w in maintenanceWindows" :key="w.id"
              class="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 rounded px-2 py-1">
              <span class="text-green-500">✓</span>
              <span class="font-medium text-slate-700">{{ w.app_key }}</span>
              <span class="font-mono bg-slate-200 px-1 rounded">{{ w.check_name }}</span>
              <span class="flex-1 truncate">{{ w.label }}</span>
              <button @click="deleteMaintenanceWindow(w.id)" class="text-red-400 hover:text-red-600">✕</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- App checks — compact rows -->
    <div class="mb-4">
      <div class="flex items-center justify-between mb-2">
        <h2 class="section-label">App checks</h2>
        <!-- Inline progress during a run -->
        <div v-if="running && checkProgress.length" class="flex items-center gap-2">
          <span class="inline-block w-2.5 h-2.5 border-2 border-slate-300 border-t-sky-500 rounded-full animate-spin"/>
          <span class="text-xs text-slate-400">
            {{ checkProgress.filter(p => p.status !== 'running').length }}/{{ checkProgress.length }} done
          </span>
        </div>
      </div>

      <!-- Loading skeleton -->
      <div v-if="!checks.length && !healthCache" class="space-y-px">
        <div v-for="n in 4" :key="n" class="card animate-pulse">
          <div class="card-body !py-2.5 flex items-center gap-3">
            <div class="w-2 h-2 bg-slate-100 rounded-full shrink-0"/>
            <div class="h-3 bg-slate-100 rounded flex-1 max-w-32"/>
            <div class="h-2.5 bg-slate-100 rounded w-24 ml-auto"/>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-else-if="!checks.length"
        class="card card-body text-center py-8 text-slate-400 text-sm space-y-1">
        <div>No health data yet.</div>
        <div class="text-xs text-slate-300">
          Click <button @click="runCycle" class="text-sky-500 hover:text-sky-600 font-medium">↻ Run now</button>
          in the status bar above, or wait for the scheduler to run automatically.
        </div>
      </div>

      <!-- Per-app grouped rows -->
      <template v-else v-for="(appChecks, appKey) in byApp" :key="appKey">
        <div class="card overflow-hidden mb-2">
          <!-- App header row -->
          <div class="flex items-center gap-3 px-3 py-2 border-b border-slate-50 bg-slate-50/60">
            <span :class="['w-2 h-2 rounded-full shrink-0',
              appChecks.some(c => c.status === 'error') ? 'bg-red-500' :
              appChecks.some(c => c.status === 'warning') ? 'bg-amber-400' : 'bg-green-500']"/>
            <span class="text-sm font-semibold text-slate-800">{{ appKey }}</span>
            <span class="text-xs text-slate-400 ml-auto">
              {{ appChecks.filter(c => c.status === 'ok').length }}/{{ appChecks.length }} ok
            </span>
          </div>
          <!-- Check rows -->
          <div v-for="c in appChecks" :key="c.check_name">
            <div class="flex items-center gap-3 px-3 py-2 border-b border-slate-50 last:border-0">
              <span :class="['w-2 h-2 rounded-full shrink-0',
                c.status === 'ok' ? 'bg-green-500' :
                c.status === 'warning' ? 'bg-amber-400' :
                c.status === 'error' ? 'bg-red-500' : 'bg-slate-300']"/>
              <span class="text-xs font-medium text-slate-700 min-w-32">{{ c.check_name.replace(/_/g, ' ') }}</span>
              <span :class="['text-xs flex-1 truncate',
                c.summary?.includes('still initialising') || c.summary?.includes('still initializing')
                  ? 'text-slate-300 italic' : 'text-slate-400']">
                {{ c.summary }}
              </span>
              <!-- AI suggestion inline -->
              <div v-if="(c as any).suggested_fix" class="flex items-center gap-1.5 shrink-0">
                <span class="text-xs text-violet-500">🤖</span>
                <button @click="applyFix(c)" :disabled="applying === c.check_name"
                  class="text-xs px-2 py-0.5 rounded bg-violet-100 text-violet-700 hover:bg-violet-200 font-medium transition-colors">
                  {{ applying === c.check_name ? '…' : 'Apply fix' }}
                </button>
                <button @click="thumbsFeedback(c, 1)"
                  :class="['text-xs px-1 rounded', thumbs[c.check_name] === 1 ? 'text-green-600' : 'text-slate-300 hover:text-green-500']">👍</button>
                <button @click="thumbsFeedback(c, -1)"
                  :class="['text-xs px-1 rounded', thumbs[c.check_name] === -1 ? 'text-red-500' : 'text-slate-300 hover:text-red-400']">👎</button>
              </div>
            </div>
            <!-- AI suggestion detail (collapsible on click, shown inline under row) -->
            <div v-if="(c as any).suggested_fix && expandedFix === c.check_name"
              class="mx-3 mb-2 rounded-lg bg-violet-50 border border-violet-100 px-3 py-2 text-xs">
              <span class="font-medium text-violet-700">🤖 </span>
              <span class="text-violet-600">{{ (c as any).suggested_fix }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- Source availability — only shown when there are issues or a scan was run -->
    <div v-if="sources.issues.length || sources.last_scan_at" class="mb-4">
      <div class="flex items-center justify-between mb-2">
        <h2 class="section-label">Source availability
          <span class="text-slate-300 font-normal ml-1">
            · {{ sources.issues.length === 0 ? 'all reachable' : sources.issues.length + ' issue(s)' }}
          </span>
        </h2>
        <div class="flex items-center gap-2">
          <span v-if="sources.last_scan_at" class="text-xs text-slate-400">{{ formatAge(sources.last_scan_at) }}</span>
          <button @click="triggerSourceScan" :disabled="scanningSource"
            class="text-xs text-slate-400 hover:text-slate-600">
            {{ scanningSource ? 'Scanning…' : '↻ Scan' }}
          </button>
        </div>
      </div>
      <div v-if="sources.issues.length" class="space-y-2">
        <div v-for="item in sources.issues" :key="item.source_type + item.resource_key"
          class="card card-body !py-2.5 border-l-2 border-l-red-400">
          <div class="flex items-start gap-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="text-sm font-medium text-red-800">{{ item.resource_key }}</span>
                <span class="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-600 font-mono">{{ item.source_type }}</span>
                <span class="text-xs text-slate-500 font-mono truncate">{{ item.status }}{{ item.http_status ? ' · HTTP ' + item.http_status : '' }}</span>
              </div>
              <div class="text-xs text-slate-400 font-mono mt-0.5 truncate">{{ item.url }}</div>
              <div v-if="item.error" class="text-xs text-red-600 mt-0.5">{{ item.error }}</div>
              <!-- Replacement -->
              <div v-if="replacements[item.url]" class="mt-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2">
                <div v-if="replacements[item.url].loading" class="text-xs text-slate-500 animate-pulse">Asking AI…</div>
                <div v-else-if="replacements[item.url].suggested_url" class="space-y-1.5">
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-medium text-sky-700">Suggested:</span>
                    <code class="text-xs font-mono text-sky-800 bg-white px-1.5 py-0.5 rounded border border-sky-200 flex-1 truncate">
                      {{ replacements[item.url].suggested_url }}
                    </code>
                    <span class="text-xs text-slate-500 shrink-0">{{ Math.round(replacements[item.url].confidence * 100) }}%</span>
                  </div>
                  <div class="flex gap-2">
                    <button @click="applyReplacement(item, replacements[item.url].suggested_url)"
                      :disabled="applyingReplacement === item.url" class="btn-primary btn-sm text-xs">
                      {{ applyingReplacement === item.url ? 'Applying…' : 'Apply' }}
                    </button>
                    <button @click="delete replacements[item.url]" class="btn-secondary btn-sm text-xs">Dismiss</button>
                  </div>
                </div>
                <div v-else class="text-xs text-slate-500">{{ replacements[item.url].reason || 'No replacement found.' }}</div>
              </div>
            </div>
            <button @click="findReplacement(item)" :disabled="replacements[item.url]?.loading"
              class="btn-secondary btn-sm text-xs shrink-0">
              {{ replacements[item.url] ? '↻' : 'Find replacement' }}
            </button>
          </div>
        </div>
      </div>
      <div v-else class="text-xs text-slate-400 text-center py-2">✓ All sources reachable</div>
    </div>

    <!-- Weekly summary — single, at bottom, on demand -->
    <div class="mb-4">
      <div class="flex items-center justify-between mb-2">
        <h2 class="section-label">Weekly summary</h2>
        <button @click="loadWeeklySummary" :disabled="loadingSummary"
          class="text-xs text-violet-500 hover:text-violet-700 font-medium">
          {{ loadingSummary ? '…' : weeklySummary ? '↻ Refresh' : 'Generate' }}
        </button>
      </div>
      <div v-if="weeklySummary" class="card card-body rounded-xl border border-violet-100 bg-violet-50">
        <p class="text-sm text-violet-700 leading-relaxed">{{ weeklySummary.summary }}</p>
        <div class="flex gap-4 mt-2 text-xs text-violet-500">
          <span>{{ weeklySummary.error_count }} errors</span>
          <span>{{ weeklySummary.warning_count }} warnings</span>
          <span v-if="!weeklySummary.llm_used" class="text-slate-400">(rule-based — add LLM for narrative)</span>
        </div>
      </div>
      <div v-else-if="!loadingSummary" class="text-xs text-slate-400 text-center py-2">
        Click Generate for a 7-day narrative
      </div>
    </div>

  </div>

</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useToast } from '@/composables/useToast'
const toast = useToast()
import { health } from '../api/client'
import { healthCache, setHealthCache } from '../appCache'
import type { HealthCheck } from '../api/client'

const checks = ref<HealthCheck[]>(healthCache ?? [])
const llmStatus = ref<{ status: string; description: string; configured_provider?: string; last_error_type?: string; last_error?: string; model_tried?: string } | null>(null)
const running = ref(false)
const schedulerStatus = ref<any>(null)
const llmInactive = ref(false)
const thumbs = ref<Record<string, number>>({})
const applying = ref<string | null>(null)
const expandedFix = ref<string | null>(null)
const anomalies = ref<any[]>([])
const pendingFixes = ref<any[]>([])
const approvingFix = ref<number | null>(null)
const escalatingFix = ref<number | null>(null)
const escalationResults = ref<Record<number, any>>({})
const manualCommand = ref<{ command: string; fixId: number } | null>(null)
const sources = ref<{ items: any[]; issues: any[]; last_scan_at: number | null; summary: any }>({
  items: [], issues: [], last_scan_at: null, summary: {}
})
const scanningSource = ref(false)
let _sourceRefreshTimer: ReturnType<typeof setTimeout> | null = null
const replacements = ref<Record<string, any>>({})
const applyingReplacement = ref<string | null>(null)
const maintenanceWindows = ref<any[]>([])
const weeklySummary = ref<any>(null)
const loadingSummary = ref(false)

const byApp = computed(() => {
  const g: Record<string, HealthCheck[]> = {}
  for (const c of checks.value) { if (!g[c.app_key]) g[c.app_key] = []; g[c.app_key].push(c) }
  return g
})
const counts = computed(() => ({
  ok: checks.value.filter(c => c.status === 'ok').length,
  warning: checks.value.filter(c => c.status === 'warning').length,
  error: checks.value.filter(c => c.status === 'error').length,
}))

async function applyFix(check: any) {
  applying.value = check.check_name
  try {
    const res = await fetch('/api/v1/health/apply-fix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        app_key: check.app_key ?? 'unknown',
        action_type: (check as any).action_type ?? 'restart_container',
        suggested_fix: (check as any).suggested_fix ?? '',
      }),
    })
    const data = await res.json()
    if (data.executed) toast.success(`Fix applied: ${data.message}`)
    else if (data.requires_approval) toast.info(`Requires approval: ${data.message}`)
    else toast.warn(data.message ?? 'Fix could not be applied.')
  } catch (e) {
    toast.error('Could not apply fix.', String(e))
  } finally { applying.value = null }
}

function actionColor(action: string): string {
  const m: Record<string, string> = {
    restart_container: 'bg-blue-100 text-blue-700',
    reload_config: 'bg-sky-100 text-sky-700',
    pull_image: 'bg-indigo-100 text-indigo-700',
    rewire: 'bg-amber-100 text-amber-700',
    restart_managed_service: 'bg-orange-100 text-orange-700',
    remount_storage: 'bg-purple-100 text-purple-700',
    manual: 'bg-slate-100 text-slate-600',
    escalate: 'bg-violet-100 text-violet-700',
  }
  return m[action] ?? 'bg-slate-100 text-slate-500'
}

async function loadPendingFixes() {
  try {
    const r = await fetch('/api/v1/health/pending-fixes')
    if (r.ok) pendingFixes.value = await r.json()
  } catch {}
}

async function approveFix(fix: any) {
  approvingFix.value = fix.id
  try {
    const r = await fetch(`/api/v1/health/pending-fixes/${fix.id}/approve`, { method: 'POST' })
    const d = await r.json()
    if (d.executed) toast.success(`Applied: ${d.message}`)
    else if (d.requires_approval) toast.info(`${d.message}`)
    else toast.warn(d.message ?? 'Fix could not be applied.')
    await loadPendingFixes()
  } catch (e) {
    toast.error('Could not apply fix.', String(e))
  } finally { approvingFix.value = null }
}

async function rejectFix(fix: any) {
  try {
    await fetch(`/api/v1/health/pending-fixes/${fix.id}/reject`, { method: 'POST' })
    toast.info('Fix rejected.')
    await loadPendingFixes()
  } catch {}
}

async function escalateFix(fix: any) {
  escalatingFix.value = fix.id
  try {
    const r = await fetch('/api/v1/health/escalate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_key: fix.app_key, check_name: fix.check_name, problem: fix.problem, logs: '', context: '' }),
    })
    const d = await r.json()
    escalationResults.value[fix.id] = d
    if (!d.escalated_to) toast.warn('No cloud provider configured — add an API key in Settings → AI.')
  } catch (e) {
    toast.error('Escalation failed.', String(e))
  } finally { escalatingFix.value = null }
}

async function approveEscalated(fix: any, escalated: any) {
  approvingFix.value = fix.id
  try {
    const r = await fetch('/api/v1/health/apply-fix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        app_key: fix.app_key,
        action_type: escalated.action ?? fix.action_type,
        suggested_fix: escalated.suggested_fix,
      }),
    })
    const d = await r.json()
    toast.success(d.executed ? `Cloud fix applied: ${d.message}` : d.message)
    delete escalationResults.value[fix.id]
    await loadPendingFixes()
  } catch (e) {
    toast.error('Could not apply fix.', String(e))
  } finally { approvingFix.value = null }
}

function formatAge(ts: number): string {
  const diff = Math.floor(Date.now() / 1000) - ts
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

async function loadSources() {
  try {
    const r = await fetch('/api/v1/health/sources')
    if (r.ok) sources.value = await r.json()
  } catch {}
}

async function triggerSourceScan() {
  scanningSource.value = true
  try {
    await fetch('/api/v1/health/sources/scan', { method: 'POST' })
    toast.success('Source scan started — results in ~1 minute.')
    _sourceRefreshTimer = setTimeout(loadSources, 5000)
  } catch (e) {
    toast.error('Scan failed.', String(e))
  } finally { scanningSource.value = false }
}

async function findReplacement(item: any) {
  replacements.value[item.url] = { loading: true }
  try {
    const r = await fetch('/api/v1/health/sources/find-replacement', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_type: item.source_type, resource_key: item.resource_key, url: item.url }),
    })
    const d = await r.json()
    replacements.value[item.url] = { ...d, loading: false }
  } catch (e) {
    replacements.value[item.url] = { loading: false, reason: String(e), suggested_url: '', confidence: 0 }
  }
}

async function applyReplacement(item: any, newUrl: string) {
  applyingReplacement.value = item.url
  try {
    const r = await fetch('/api/v1/health/sources/apply-replacement', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_type: item.source_type, resource_key: item.resource_key, old_url: item.url, new_url: newUrl }),
    })
    const d = await r.json()
    if (d.ok) { toast.success(d.message); delete replacements.value[item.url]; await loadSources() }
    else toast.error(d.message)
  } catch (e) {
    toast.error('Apply failed.', String(e))
  } finally { applyingReplacement.value = null }
}

function dayName(d: number): string {
  return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d] ?? '?'
}

async function loadMaintenanceWindows() {
  try {
    const r = await fetch('/api/v1/health/maintenance-windows')
    if (r.ok) maintenanceWindows.value = await r.json()
  } catch {}
}

async function createMaintenanceWindow(a: any) {
  const label = `${a.app_key} ${a.check_name} scheduled downtime`
  const hStart = a.typical_hour ?? 0
  const hEnd = hStart + 2
  try {
    const r = await fetch('/api/v1/health/maintenance-windows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_key: a.app_key, check_name: a.check_name, label, day_of_week: a.typical_day ?? null, hour_start: hStart, hour_end: hEnd }),
    })
    if (r.ok) {
      toast.success(`Maintenance window set for ${a.app_key}`)
      await loadMaintenanceWindows()
      await loadSources()
      await loadPendingFixes()
      const ar = await fetch('/api/v1/health/anomalies')
      if (ar.ok) anomalies.value = Array.isArray(await ar.json()) ? await ar.clone().json() : []
    }
  } catch (e) { toast.error('Could not create maintenance window.', String(e)) }
}

async function deleteMaintenanceWindow(id: number) {
  try {
    await fetch(`/api/v1/health/maintenance-windows/${id}`, { method: 'DELETE' })
    await loadMaintenanceWindows()
    await loadSources()
    await loadPendingFixes()
  } catch {}
}

async function snoozeAnomaly(a: any) {
  try {
    const r = await fetch(`/api/v1/health/anomalies/${a.app_key}/${a.check_name}/snooze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_key: a.app_key, check_name: a.check_name, hours: 72 }),
    })
    const data = await r.json()
    if (r.ok) {
      anomalies.value = anomalies.value.filter(x => !(x.app_key === a.app_key && x.check_name === a.check_name))
      toast.info(data.message)
    }
  } catch (e) { toast.error('Could not snooze anomaly.', String(e)) }
}

async function loadWeeklySummary() {
  loadingSummary.value = true
  try {
    const res = await fetch('/api/v1/health/weekly-summary')
    weeklySummary.value = await res.json()
  } catch (e) { toast.error('Could not generate summary.', String(e)) }
  finally { loadingSummary.value = false }
}

async function thumbsFeedback(check: any, value: number) {
  thumbs.value[check.check_name] = value
  try {
    await fetch('/api/v1/models/fix-history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        app_key: check.app_key ?? 'unknown',
        error_type: check.check_name,
        context: check.summary ?? '',
        suggested_fix: check.suggested_fix ?? '',
        outcome: value === 1 ? 'success' : 'failure',
      }),
    })
    if (value === 1) toast.success('Thanks — helps the AI improve.')
    else toast.info('Noted — suggestion will be deprioritised.')
  } catch {}
}

const checkProgress = ref<{ app: string; status: 'running' | 'ok' | 'warning' | 'error'; detail: string }[]>([])

async function runCycle() {
  running.value = true
  // Seed progress from existing checks if we have them, otherwise placeholder
  const appKeys = [...new Set(checks.value.map(c => c.app_key ?? ''))].filter(Boolean)
  checkProgress.value = appKeys.map(k => ({ app: k, status: 'running' as const, detail: '' }))

  try {
    // Await and READ the cycle response — it contains apps_checked and per-app results
    const cycleResult: any = await health.runCycle()
    const appsChecked: number = cycleResult?.apps_checked ?? 0
    const appsHealthy: number = cycleResult?.apps_healthy ?? 0
    const cycleResults: any[] = cycleResult?.results ?? []

    // Build progress from actual results returned by the cycle
    if (cycleResults.length > 0) {
      checkProgress.value = cycleResults.map((r: any) => ({
        app: r.app,
        status: (r.ok ? 'ok' : 'error') as 'ok' | 'error' | 'warning' | 'running',
        detail: r.message ?? '',
      }))
    } else if (appsChecked === 0) {
      checkProgress.value = []
    }

    // Refresh checks from DB — now has results written by the cycle
    checks.value = await health.allApps()
    setHealthCache(checks.value)
    await loadPendingFixes()

    // Toast with honest counts
    const nonRunning: string[] = cycleResult?.non_running_apps ?? []
    if (appsChecked === 0) {
      if (nonRunning.length > 0)
        toast.warn(`No running apps to check. ${nonRunning.length} app(s) installed but not running: ${nonRunning.slice(0,3).join(', ')}${nonRunning.length > 3 ? '…' : ''}`)
      else
        toast.warn('No installed apps found. Install apps from the Catalog first.')
    } else {
      const errorCount = checks.value.filter(c => c.status === 'error').length
      if (errorCount > 0)
        toast.warn(`${errorCount} app${errorCount > 1 ? 's' : ''} unhealthy — ${appsHealthy} healthy.`)
      else
        toast.success(`All ${appsChecked} apps healthy.`)
    }
  } catch (e) {
    checkProgress.value = [{ app: 'Error', status: 'error', detail: e instanceof Error ? e.message : String(e) }]
    toast.error('Health cycle failed.', e instanceof Error ? e.message : String(e))
  } finally { running.value = false }
}

onUnmounted(() => {
  if (_sourceRefreshTimer) clearTimeout(_sourceRefreshTimer)
})

onMounted(async () => {
  // Scheduler status
  try {
    const r = await fetch('/api/v1/health/scheduler')
    schedulerStatus.value = await r.json()
  } catch {}

  const [c, l, a] = await Promise.allSettled([
    health.allApps(),
    health.llmAgent(),
    fetch('/api/v1/health/anomalies').then(r => r.json()),
  ])
  if (a.status === 'fulfilled') anomalies.value = Array.isArray(a.value) ? a.value : []
  if (c.status === 'fulfilled') { checks.value = c.value; setHealthCache(c.value) }
  if (l.status === 'fulfilled') {
    llmStatus.value = l.value
    llmInactive.value = !l.value || l.value.status === 'inactive'
  }

  await Promise.all([loadMaintenanceWindows(), loadSources(), loadPendingFixes()])
  
  // Auto-load weekly summary only if it already exists (not force-generate)
  try {
    const res = await fetch('/api/v1/health/weekly-summary')
    const d = await res.json()
    if (d.has_summary) weeklySummary.value = d
  } catch {}
})
</script>

<style scoped>
.section-label {
  font-size: 11px;
  font-weight: 500;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
</style>
